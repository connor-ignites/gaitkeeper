# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose Adapt: change one pose and the whole clip follows. Runs inside Blender.

The animator poses bones on one frame (without keying them) and presses Adapt. GaitKeeper reads the
change against the clip's own pose on that frame and bakes it into a COPY of the clip, so the old
motion never fights the new pose (a layer on top would keep pulling the limb back). Where it lands is
set by adapt_math.blend_plan: the whole clip, the same moment of every step (mirrored on the other foot's
step), or just around the frame. Then:
- legs you didn't touch keep their feet exactly where they were (two-bone IK), so a lower hip or a
  new lean bends the knees instead of sinking or sliding the feet;
- legs you did touch keep their new placement, with planted feet locked so they don't skate;
- the loop still joins (the weights wrap round the seam);
- the GaitKeeper checks run on the result, new snaps are smoothed, and anything the edit made worse
  is listed. The original clip is never changed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import adapt_math as am
from . import motion_math as mm
from .checks import measure, verdicts
from .edit import write_action
from .fix import smooth_pops, two_bone_ik
from .names import says_loop
from .rig import (
    Sample,
    body_axes,
    clip_range,
    contact_flags,
    key_rotation,
    leg_sides,
    sample,
    set_action,
    split_name,
)

Pose = dict[str, tuple[tuple, tuple, tuple]]
Delta = dict[str, tuple[Vector, Quaternion]]
Key = tuple[int, Delta, Pose]  # (clip frame index, change per bone, the pose as made)
Track = dict[str, dict[float, tuple[Vector, Quaternion, list[float] | None]]]  # bone -> position -> change, gate
Leg = tuple[str, str, str, str, bool]  # (side, thigh, calf, foot, touched)
FootPlan = tuple[list[bool], list[float], bool]  # (planted per frame, plant weight per frame, keep its toe angle)
Gate = Callable[[str, int, str | None, bool], list[float] | None]
LEG_ROLES = ("thigh", "calf", "foot", "toe")
CLEAR = 0.08  # m: a touched swinging ankle keeps at least this much (or its old height) above its floor
CLEAR_BALL = 0.05  # m: and the ball of the foot this much, so the toes don't brush the ground mid-swing


def capture_pose(arm: bpy.types.Object) -> Pose:
    """Every bone's pose as it is on screen now (keyed or not): (location, rotation, scale)."""
    out = {}
    for pb in arm.pose.bones:
        loc, rot, sca = pb.matrix_basis.decompose()
        out[pb.name] = (tuple(loc), tuple(rot), tuple(sca))
    return out


def pose_delta(
    edited: Pose, original: Pose, min_deg: float = 0.05, min_move: float = 5e-4
) -> dict[str, tuple[Vector, Quaternion]]:
    """Bones the animator changed: (location change, rotation change in the bone's own axes)."""
    out = {}
    for name, (loc, q, _) in edited.items():
        if name not in original:
            continue
        l0, q0, _ = original[name]
        dq = Quaternion(q0).inverted() @ Quaternion(q)
        dl = Vector(loc) - Vector(l0)
        if mm.q_angle_deg((1, 0, 0, 0), tuple(dq)) > min_deg or dl.length > min_move:
            if dq.w < 0:
                dq.negate()
            out[name] = (dl, dq)
    return out


def pairs(arm: bpy.types.Object) -> dict[str, str]:
    """Each bone's mirror twin (upperarm_l <-> upperarm_r); centre bones (spine, head) are their own."""
    by: dict[tuple[str, str], str] = {}
    for b in arm.data.bones:
        by.setdefault(split_name(b.name), b.name)
    out = {}
    for b in arm.data.bones:
        side, core = split_name(b.name)
        if not side:
            out[b.name] = b.name
        elif twin := by.get(("r" if side == "l" else "l", core)):
            out[b.name] = twin
    return out


def mirror_delta(
    arm: bpy.types.Object, bone: str, twin: str, dl: Vector, dq: Quaternion, right: Vector
) -> tuple[Vector, Quaternion]:
    """The same change for the twin bone, mirrored across the body's centre line (in the rest pose:
    'swing out' on the left thigh becomes 'swing out' on the right)."""
    n = right.normalized()
    S = Matrix.Identity(3) - 2 * Matrix(
        [[n.x * n.x, n.x * n.y, n.x * n.z], [n.y * n.x, n.y * n.y, n.y * n.z], [n.z * n.x, n.z * n.y, n.z * n.z]]
    )
    ra = arm.data.bones[bone].matrix_local.to_3x3().normalized()
    rb = arm.data.bones[twin].matrix_local.to_3x3().normalized()
    d_arm = ra @ dq.to_matrix() @ ra.inverted()
    dqm = (rb.inverted() @ (S @ d_arm @ S) @ rb).to_quaternion()
    if dqm.w < 0:
        dqm.negate()
    dlm = rb.inverted() @ (S @ (ra @ dl))
    return dlm, dqm


def leg_label(side: str, sides: Sequence[str]) -> str:
    """ "left", or for a four-legged animal "back left" / "front left"."""
    word = "left" if side.endswith("l") else "right"
    if not any(s.startswith("f") for s in sides):
        return word
    return ("front " if side.startswith("f") else "back ") + word


def same_words(line: str) -> str:
    """A verdict line without its numbers, to tell an old problem from a new one."""
    return re.sub(r"[-+]?\d+(\.\d+)?", "#", line)


def _apply(fr: Pose, name: str, dl: Vector, dq: Quaternion, w: float) -> None:
    if w <= 0 or name not in fr:
        return
    loc, q, sc = fr[name]
    part = Quaternion().slerp(dq, w)
    fr[name] = (tuple(Vector(loc) + dl * w), tuple(Quaternion(q) @ part), sc)


def gait_channels(s: object, roles: dict[str, str], arm: bpy.types.Object, m: int) -> tuple[list, list]:
    """Per side: the ankle's height and how far ahead of the hips it is, frame by frame. Both repeat
    once per full gait cycle."""
    fwd = body_axes(arm, roles)[0]
    out = []
    for side in "lr":
        key = f"ankle_{side}"
        if key not in s.world[0] or "hips" not in s.world[0]:  # type: ignore[attr-defined]
            out.append([])
            continue
        w = s.world[:m]  # type: ignore[attr-defined]
        out.append([[p[key][2] for p in w], [(Vector(p[key]) - Vector(p["hips"])).dot(fwd) for p in w]])
    return out[0], out[1]


@dataclass
class _Spread:
    """Where the changes land: the spread mode actually used, laid out on the clip's axis."""

    mode: str
    n: int  # frames in the clip
    cyclic: bool
    period: int | None  # frames per full gait cycle, when one was found
    length: float
    wraps: bool
    radius: float | None
    mirror: bool
    alternate: bool  # the legs take turns
    together: bool  # the legs move together (a hop)

    def at(self, i: int) -> float:
        """Clip frame index i's position on the axis."""
        return am.position(i, self.n, self.mode, self.cyclic, self.period)


def adapt_clip(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    roles: dict[str, str],
    fps: float,
    frame: int,
    edited: Pose,
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    mode: str = "whole",
    spread: float = 6,
    mirror: bool = True,
    keep_feet: bool = True,
    name: str | None = None,
    more: Sequence[tuple[int, Pose]] = (),
    judge: Callable | None = None,
    cyclic: bool | None = None,
) -> tuple[bpy.types.Action, dict]:
    """Bake edited poses into a copy of `act`: the pose on screen at scene frame `frame`, plus any kept
    poses `more` ((frame, pose) pairs; the one on screen wins on its own frame). Returns (copy, report).
    The clip is played on `scene`; bone edits are evaluated through `view_layer`.
    `judge(action) -> verdict lines` checks an animal (roles from creature.leg_roles); None: a person,
    judged by the person checks."""
    a, poses = _poses_in_clip(act, mode, frame, edited, more)
    before = sample(arm, act, roles, scene)
    keys = _edit_keys(poses, before, a)
    if cyclic is None:
        cyclic = says_loop(act.name)
    report = _start_report(arm, act, before, keys, a, fps, cyclic, judge)
    travels = _travels(report, before, judge)
    sp = _choose_spread(arm, roles, before, fps, cyclic, mode, spread, mirror, report["notes"])
    report["period"] = sp.period
    side_of = _bone_sides(roles)
    gate = partial(_gate, _contacts(before, roles, fps, sp), side_of, cyclic)
    track, mirrored_any = _track(arm, roles, keys, sp, gate, side_of)
    _note_spread(report, sp, spread, keys, track, mirrored_any)
    frames = _blend_frames(before, sp, track)

    touched = set(track)  # the bones the animator changed, directly or through the mirror
    legs = _legs(roles, touched)
    orig_feet = _foot_matrices(arm, scene, legs, roles, a, sp.n) if keep_feet else {}
    new = write_action(arm, frames, name or f"{act.name.split('|')[-1]}_adapted")
    if keep_feet and legs:
        _keep_feet(arm, scene, view_layer, legs, orig_feet, before, roles, sp.n, fps, cyclic and not travels, touched)
        report["notes"] += _feet_notes(legs, leg_sides(roles))
    if judge is None:
        _judge_person(report, arm, act, new, roles, fps, cyclic, sp.n, scene)
    else:
        _judge_animal(report, act, new, judge)
    report["pose_kept_deg"] = _pose_kept_deg(arm, scene, new, keys)
    new.use_fake_user = True
    return new, report


def _poses_in_clip(
    act: bpy.types.Action, mode: str, frame: int, edited: Pose, more: Sequence[tuple[int, Pose]]
) -> tuple[int, dict[int, Pose]]:
    """The clip's first frame and the poses to bake by scene frame (the one on screen wins on its own
    frame). Refuses an unknown spread mode or a pose outside the clip."""
    if mode not in am.MODES:
        raise ValueError(f"unknown spread mode {mode!r}")
    a, b = clip_range(act)
    poses = dict(more)
    poses[frame] = edited
    for f in poses:
        if not a <= f <= b:
            raise ValueError(f"frame {f} is outside the clip ({a} to {b})")
    return a, poses


def _edit_keys(poses: dict[int, Pose], before: Sample, a: int) -> list[Key]:
    """Each pose that differs from the clip's own pose on its frame, in frame order."""
    keys = []
    for f in sorted(poses):
        d = pose_delta(poses[f], before.basis[f - a])
        if d:
            keys.append((f - a, d, poses[f]))
    if not keys:
        raise ValueError("nothing changed: pose a bone on this frame first (without keying it), then Adapt")
    return keys


def _start_report(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    before: Sample,
    keys: list[Key],
    a: int,
    fps: float,
    cyclic: bool,
    judge: Callable | None,
) -> dict:
    """The report so far: the original clip measured (people only), the changed bones and their frames."""
    return {
        "original": measure(before, fps, cyclic, arm, act.name) if judge is None else {},
        "notes": [],
        "changed": sorted({bn for _, d, _ in keys for bn in d}),
        "frame": ", ".join(str(k[0] + a) for k in keys),
    }


def _travels(report: dict, before: Sample, judge: Callable | None) -> bool:
    """Whether the clip moves the body along (then a loop's feet don't wrap round the seam)."""
    if judge is None:
        return report["original"].get("travels", False)
    return "hips" in before.world[0] and mm.dist2d(before.world[0]["hips"], before.world[-1]["hips"]) > 0.3


def _step_pattern(
    arm: bpy.types.Object, roles: dict[str, str], before: Sample, fps: float, cyclic: bool, m: int
) -> tuple[int | None, bool, bool]:
    """(frames per gait cycle or None, the legs take turns, the legs move together)."""
    left, right = gait_channels(before, roles, arm, m)
    if not (left and right):
        return None, False, False
    period = am.step_period(left, fps, cyclic)
    alternate = bool(period) and am.sides_alternate(left, right, period, cyclic)
    together = not alternate and am.sides_together(left, right, cyclic)
    return period, alternate, together


def _spread_mode(
    mode: str, mirror: bool, period: int | None, alternate: bool, together: bool, notes: list[str]
) -> tuple[str, bool]:
    """The spread mode and mirroring the clip allows, noting any change from what was asked."""
    use_mode = mode
    if mode == "steps" and not period:
        use_mode = "here"
        notes.append("no repeating step found in this clip, so the change fades in and out around the frame instead")
    use_mirror = mirror
    if use_mode == "steps" and mirror and not alternate:
        if together:
            notes.append(
                "both legs move together in this clip (a hop), so the other side got the same change at the same moment"
            )
        else:
            use_mirror = False
            notes.append("the two sides don't take turns in this clip, so the other side was left alone")
    if use_mode == "here":
        use_mirror = False
    return use_mode, use_mirror


def _choose_spread(
    arm: bpy.types.Object,
    roles: dict[str, str],
    before: Sample,
    fps: float,
    cyclic: bool,
    mode: str,
    spread: float,
    mirror: bool,
    notes: list[str],
) -> _Spread:
    """Read the clip's step pattern (when stepping or mirroring needs it) and lay out the spread."""
    n = len(before.basis)
    period, alternate, together = None, False, False
    if mode == "steps" or mirror:
        period, alternate, together = _step_pattern(arm, roles, before, fps, cyclic, am.loop_frames(n, cyclic))
    use_mode, use_mirror = _spread_mode(mode, mirror, period, alternate, together, notes)
    length, wraps, radius = am.axis(n, use_mode, cyclic, spread, period)
    return _Spread(use_mode, n, cyclic, period, length, wraps, radius, use_mirror, alternate, together)


def _bone_sides(roles: dict[str, str]) -> dict[str, str]:
    """Each leg bone's side."""
    sides = leg_sides(roles)
    return {roles[f"{r}_{sd}"]: sd for r in LEG_ROLES for sd in sides if f"{r}_{sd}" in roles}


def _contacts(before: Sample, roles: dict[str, str], fps: float, sp: _Spread) -> dict[str, list[bool]]:
    """Each side's planted flags per frame; none for the whole clip, where every frame gets the change."""
    if sp.mode == "whole":
        return {}
    return {
        sd: contact_flags(before, sd, fps, sp.cyclic) for sd in leg_sides(roles) if f"ankle_{sd}" in before.world[0]
    }


def _gate(
    down: dict[str, list[bool]],
    side_of: dict[str, str],
    cyclic: bool,
    bone: str,
    key_idx: int,
    src_side: str | None,
    mirrored: bool,
) -> list[float] | None:
    """How much of a leg change each frame takes. A leg changed mid-swing stays in the swing, one changed
    while planted stays in the stance: otherwise the fade would carry the change onto a planted foot and
    drag it. None for a bone that isn't on a leg."""
    sd = side_of.get(bone)
    if sd not in down:
        return None
    state = down.get(src_side or sd, down[sd])[key_idx]
    g = mm.smooth_weights([1.0 if c == state else 0.0 for c in down[sd]], 2, cyclic)
    top = max(g) if mirrored else g[key_idx]
    return [min(1.0, x / max(top, 1e-6)) for x in g]


def _track(
    arm: bpy.types.Object, roles: dict[str, str], keys: list[Key], sp: _Spread, gate: Gate, side_of: dict[str, str]
) -> tuple[Track, bool]:
    """Every bone's changes on the axis: (position -> location change, rotation change, gate), and whether
    any were mirrored onto a twin."""
    track: Track = {}
    for ki, d, _ in keys:
        for bone, (dl, dq) in d.items():
            track.setdefault(bone, {})[sp.at(ki)] = (dl, dq, gate(bone, ki, None, False))
    mirrored = sp.mirror and _mirror_track(arm, roles, keys, sp, gate, side_of, track)
    return track, mirrored


def _mirror_track(
    arm: bpy.types.Object,
    roles: dict[str, str],
    keys: list[Key],
    sp: _Spread,
    gate: Gate,
    side_of: dict[str, str],
    track: Track,
) -> bool:
    """Add each change, mirrored, to the twin bone (on the other foot's step when the legs take turns).
    Returns whether anything was mirrored."""
    right = arm.matrix_world.to_3x3().inverted() @ body_axes(arm, roles)[1]
    twin_of = pairs(arm)
    mirrored = False
    for ki, d, _ in keys:
        for bone, (dl, dq) in d.items():
            twin = twin_of.get(bone)
            if twin is None or (sp.mode == "whole" and (twin == bone or twin in d)):
                continue  # whole clip: a centre bone mirrored onto itself would cancel; an edited twin is yours
            pos = (sp.at(ki) + sp.length / 2) % sp.length if sp.mode == "steps" and sp.alternate else sp.at(ki)
            if pos == sp.at(ki) and (twin == bone or twin in d):
                continue  # at the same moment: a centre bone would cancel; an edited twin is yours
            if pos in track.get(twin, {}):
                continue  # a pose made on the twin itself there wins
            dlm, dqm = mirror_delta(arm, bone, twin, dl, dq, right)
            track.setdefault(twin, {})[pos] = (dlm, dqm, gate(twin, ki, side_of.get(bone), True))
            mirrored = True
    return mirrored


def _note_spread(report: dict, sp: _Spread, spread: float, keys: list[Key], track: Track, mirrored: bool) -> None:
    """Say how the change was spread, and the notes that go with it."""
    report["how"] = am.describe(sp.mode, sp.n, sp.cyclic, spread, sp.period, [k[0] for k in keys], mirrored)
    if sp.together and sp.mode == "steps":
        report["how"] = report["how"].replace("mirrored on the other foot's step", "both legs together")
    if any(g is not None for t in track.values() for (_, _, g) in t.values()):
        report["notes"].append(
            "leg changes kept to the part of the step they were made in (swing or planted), so planted feet don't drag"
        )
    if len(keys) > 1:
        report["notes"].append("between poses close together the change runs smoothly from one to the next")


def _blend_frames(before: Sample, sp: _Spread, track: Track) -> list[Pose]:
    """The clip's poses with every change blended in by its place on the axis and its gate."""
    frames = []
    plans = {bone: sorted(t) for bone, t in track.items()}
    for i in range(sp.n):
        fr = dict(before.basis[i])
        x = sp.at(i)
        for bone, spots in plans.items():
            plan = am.blend_plan(spots, x, sp.length, sp.wraps, sp.radius)
            if plan is None:
                continue
            ka, kb, u, w = plan
            dla, dqa, ga = track[bone][spots[ka]]
            dlb, dqb, gb = track[bone][spots[kb]]
            g = (ga[i] if ga else 1.0) * (1 - u) + (gb[i] if gb else 1.0) * u
            _apply(fr, bone, dla.lerp(dlb, u), dqa.slerp(dqb, u), w * g)
        frames.append(fr)
    return frames


def _legs(roles: dict[str, str], touched: set[str]) -> list[Leg]:
    """Every whole leg (thigh, calf and foot found), and whether the animator touched any of its bones."""
    legs = []
    for side in leg_sides(roles):
        names = [roles.get(f"{r}_{side}") for r in ("thigh", "calf", "foot")]
        if all(names):
            own = {roles.get(f"{r}_{side}") for r in LEG_ROLES}
            legs.append((side, *names, bool(own & touched)))
    return legs


def _foot_matrices(
    arm: bpy.types.Object, scene: bpy.types.Scene, legs: list[Leg], roles: dict[str, str], a: int, n: int
) -> dict[str, list[Matrix]]:
    """Each foot's pose matrix on every frame of the original clip, and the ball of the foot (the toe's
    head) as a translation-only matrix."""
    orig_feet: dict[str, list[Matrix]] = {}
    for f in range(n):
        scene.frame_set(a + f)
        for side, _, _, foot, _ in legs:
            orig_feet.setdefault(foot, []).append(arm.pose.bones[foot].matrix.copy())
            toe = roles.get(f"toe_{side}")
            if toe:
                orig_feet.setdefault(toe, []).append(Matrix.Translation(arm.pose.bones[toe].head))
    return orig_feet


def _feet_notes(legs: list[Leg], sides: Sequence[str]) -> list[str]:
    """Report notes on which feet were kept where they were and which follow the new pose."""
    notes = []
    kept = [leg_label(s, sides) for s, *_, t in legs if not t]
    moved = [leg_label(s, sides) for s, *_, t in legs if t]
    if kept:
        notes.append(
            f"{', '.join(kept)} {'feet' if len(kept) > 1 else 'foot'} kept where "
            f"{'they were' if len(kept) > 1 else 'it was'}".replace("left, right feet", "both feet").replace(
                "back left, back right, front left, front right feet", "all four feet"
            )
        )
    if moved:
        notes.append(
            f"{', '.join(moved)} {'feet follow' if len(moved) > 1 else 'foot follows'} your "
            "pose, planted steps held on the ground".replace("left, right feet", "both feet")
        )
    return notes


def _judge_person(
    report: dict,
    arm: bpy.types.Object,
    act: bpy.types.Action,
    new: bpy.types.Action,
    roles: dict[str, str],
    fps: float,
    cyclic: bool,
    n: int,
    scene: bpy.types.Scene,
) -> None:
    """Measure the copy with the person checks, smoothing any snaps the edit added, and list what got worse."""
    report["result"] = measure(sample(arm, new, roles, scene), fps, cyclic, arm, act.name)
    for _ in range(3):  # an edit must not add snaps: smooth any new pops, then measure again
        fresh = {bn: f for bn, f in report["result"]["pops"].items() if bn not in report["original"]["pops"]}
        if not fresh:
            break
        smooth_pops(arm, fresh, n, scene)
        report["result"] = measure(sample(arm, new, roles, scene), fps, cyclic, arm, act.name)
    report["verdict"] = verdicts(report["original"], report["result"], fixing=True)
    was = verdicts(report["original"], None)
    report["worse"] = [v for v in report["verdict"] if v.startswith(("FAIL", "WARN")) and v not in was]


def _judge_animal(report: dict, act: bpy.types.Action, new: bpy.types.Action, judge: Callable) -> None:
    """Check the copy with the animal's own judge and list what got worse (ignoring the numbers)."""
    was, now = judge(act), judge(new)
    report["verdict"] = now
    report["worse"] = [
        v for v in now if v.startswith(("FAIL", "WARN")) and same_words(v) not in {same_words(x) for x in was}
    ]


def _pose_kept_deg(arm: bpy.types.Object, scene: bpy.types.Scene, new: bpy.types.Action, keys: list[Key]) -> float:
    """How close the copy comes to the poses the animator made, on their frames (worst bone, degrees).
    Leaves the copy on the armature at the first edited frame."""
    set_action(arm, new)
    worst = 0.0
    for ki, d, pose in keys:
        scene.frame_set(ki)
        for bone in d:
            q_now = tuple(arm.pose.bones[bone].matrix_basis.to_quaternion())
            worst = max(worst, mm.q_angle_deg(q_now, pose[bone][1]))
    scene.frame_set(keys[0][0])
    return round(worst, 2)


@dataclass
class _Feet:
    """What every step of keeping the feet needs: the rig, the legs and the original foot matrices."""

    arm: bpy.types.Object
    scene: bpy.types.Scene
    view_layer: bpy.types.ViewLayer
    legs: list[Leg]
    roles: dict[str, str]
    orig_feet: dict[str, list[Matrix]]
    n: int  # frames in the clip
    m: int  # frames in one loop (n, or n - 1 when the last frame repeats the first)


def _keep_feet(
    arm: bpy.types.Object,
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    legs: list[Leg],
    orig_feet: dict[str, list[Matrix]],
    before: Sample,
    roles: dict[str, str],
    n: int,
    fps: float,
    cyclic: bool,
    touched: set[str],
) -> None:
    """Untouched legs: the foot goes back exactly where it was on every frame. Touched legs: each
    planted step (planted in the original clip) follows the original foot's own path on the ground,
    shifted by however far the edit moved that step, so it neither skates nor sinks. The foot
    keeps its original toe angle (unless the foot itself was turned): planted it stays flat, so a bent
    knee doesn't dig the toes in, and swinging it doesn't dangle toes-down.
    Off the ground, a touched foot goes where the new pose puts it, keeping its toe clearance."""
    ft = _Feet(arm, scene, view_layer, legs, roles, orig_feet, n, am.loop_frames(n, cyclic))
    floor, plan = _foot_plans(ft, before, fps, cyclic, touched)
    new_pos = _foot_heads(ft, plan)
    targets = {
        foot: _foot_target(ft, foot, down, w, new_pos[foot], floor[foot], cyclic) for foot, (down, w, _) in plan.items()
    }
    goal, lift = _foot_goals(ft, plan, targets, _ball_floors(before, roles))
    _place_legs(ft, goal, lift)


def _foot_plans(
    ft: _Feet, before: Sample, fps: float, cyclic: bool, touched: set[str]
) -> tuple[dict[str, float], dict[str, FootPlan]]:
    """For each touched foot: its floor (the ankle's lowest height in the original clip) and its plan."""
    floor, plan = {}, {}
    for side, _, _, foot, leg_touched in ft.legs:
        if not leg_touched or f"ankle_{side}" not in before.world[0]:
            continue
        floor[foot] = min(w[f"ankle_{side}"][2] for w in before.world)
        down = contact_flags(before, side, fps, cyclic)[: ft.m]
        own_foot = {ft.roles.get(f"foot_{side}"), ft.roles.get(f"toe_{side}")} & touched
        plan[foot] = (down, mm.smooth_weights([1.0 if c else 0.0 for c in down], 2, cyclic), not own_foot)
    return floor, plan


def _foot_heads(ft: _Feet, plan: dict[str, FootPlan]) -> dict[str, list[Vector]]:
    """Where the new pose puts each planned foot's ankle, frame by frame over one loop."""
    pb = ft.arm.pose.bones
    new_pos: dict[str, list[Vector]] = {foot: [] for foot in plan}
    for f in range(ft.m):
        ft.scene.frame_set(f)
        for foot in plan:
            new_pos[foot].append(pb[foot].head.copy())
    return new_pos


def _lock_planted(down: list[bool], old: list[Vector], new: list[Vector], cyclic: bool, m: int) -> list[Vector]:
    """The new ankle path, with each planted run following the original path shifted by however far
    the edit moved that step most."""
    locked = list(new)
    for start, length in mm.runs(down, cyclic):
        run = [(start + k) % m for k in range(length)]
        anchor = max(run, key=lambda i: (new[i] - old[i]).length)  # where the edit moved it most
        shift = new[anchor] - old[anchor]
        for i in run:
            locked[i] = old[i] + shift
    return locked


def _foot_target(
    ft: _Feet, foot: str, down: list[bool], w: list[float], new: list[Vector], floor: float, cyclic: bool
) -> list[Vector]:
    """A touched foot's ankle target on every frame: planted steps locked, swinging ones free but clear
    of the ground."""
    old = [ft.orig_feet[foot][i].translation for i in range(ft.m)]
    locked = _lock_planted(down, old, new, cyclic, ft.m)
    tg = []
    for i in range(ft.m):
        t = new[i].lerp(locked[i], w[i])
        # toe clearance: near the ground a swinging foot never drops below where it was (it would
        # scuff), higher up it may come down to CLEAR above the floor
        t.z = max(t.z, floor, min(old[i].z, floor + CLEAR))
        tg.append(t)
    if ft.m < ft.n:
        tg.append(tg[0].copy())
    return tg


def _ball_floors(before: Sample, roles: dict[str, str]) -> dict[str, float]:
    """Each side's floor for the ball of the foot: its lowest height in the original clip."""
    return {
        sd: min(w[f"ball_{sd}"][2] for w in before.world) for sd in leg_sides(roles) if f"ball_{sd}" in before.world[0]
    }


def _foot_turn(fb: bpy.types.PoseBone, was: Matrix, w: float, keep_flat: bool) -> Matrix:
    """A touched foot's rotation: as the new pose turns it, or (keep_flat) with the original toe angle,
    blending to the original rotation by the plant weight w."""
    rot = fb.matrix.to_3x3().to_4x4()
    if keep_flat:
        rot = _keep_pitch(fb.matrix.to_3x3(), was.to_3x3()).to_4x4()
    if keep_flat and w > 0:
        q = fb.matrix.to_quaternion().slerp(was.to_quaternion(), w)
        rot = q.to_matrix().to_4x4()
    return rot


def _toe_dip(
    fb: bpy.types.PoseBone, toe: bpy.types.PoseBone, target: Vector, rot: Matrix, was_z: float, floor: float
) -> float:
    """How far the ball of the foot would dip below its clearance with the foot at target, turned rot."""
    ball = target + rot.to_3x3() @ (fb.matrix.to_3x3().inverted() @ (toe.head - fb.head))
    need = min(was_z, floor + CLEAR_BALL)
    return max(0.0, need - ball.z)


def _foot_goals(
    ft: _Feet, plan: dict[str, FootPlan], targets: dict[str, list[Vector]], ball_floor: dict[str, float]
) -> tuple[dict[str, list[tuple[Vector, Matrix]]], dict[str, list[float]]]:
    """Pass 1: where each foot goes and how it's turned, and how far its toes would dip below their
    clearance. The foot is lifted by exactly that much: the ball then follows max(new height, clearance),
    and both change smoothly, so the lift can't pop and needs no blur (a blur would lift planted frames)."""
    pb = ft.arm.pose.bones
    goal: dict[str, list[tuple[Vector, Matrix]]] = {}
    dip: dict[str, list[float]] = {}
    for f in range(ft.n):
        ft.scene.frame_set(f)
        for side, _, _, foot, leg_touched in ft.legs:
            was = ft.orig_feet[foot][f]
            if leg_touched and foot in targets:
                _, w, keep_flat = plan[foot]
                target, rot = targets[foot][f], _foot_turn(pb[foot], was, w[f % ft.m], keep_flat)
                toe = ft.roles.get(f"toe_{side}")
                low = 0.0
                if toe in ft.orig_feet and side in ball_floor:
                    low = _toe_dip(pb[foot], pb[toe], target, rot, ft.orig_feet[toe][f].translation.z, ball_floor[side])
                dip.setdefault(foot, []).append(low)
            else:
                target, rot = was.translation.copy(), was.to_3x3().to_4x4()
            goal.setdefault(foot, []).append((target, rot))
    return goal, dip


def _place_legs(ft: _Feet, goal: dict[str, list[tuple[Vector, Matrix]]], lift: dict[str, list[float]]) -> None:
    """Pass 2: put every foot at its goal (lifted clear of the ground) with two-bone IK and key the leg."""
    pb = ft.arm.pose.bones
    for f in range(ft.n):
        ft.scene.frame_set(f)
        for _, thigh, calf, foot, _ in ft.legs:
            fb = pb[foot]
            target, rot = goal[foot][f]
            if foot in lift and lift[foot][f] > 0:
                target = target + Vector((0, 0, lift[foot][f]))
            off = (fb.head - target).length
            turn = mm.q_angle_deg(tuple(fb.matrix.to_quaternion()), tuple(rot.to_quaternion()))
            if off < 5e-4 and turn < 0.1:
                continue
            two_bone_ik(ft.arm, pb[thigh], pb[calf], fb, target, rot, ft.view_layer)
            for bone in (pb[thigh], pb[calf], fb):
                key_rotation(bone, f)
                bone.keyframe_insert("location", frame=f, group=bone.name)


def _keep_pitch(now: Matrix, was: Matrix) -> Matrix:
    """The foot as the new pose turns it, but tipped back to the original clip's toe-up/toe-down angle:
    a lifted or swung leg shouldn't leave the foot dangling toes-down (the ankle flexes to clear the
    ground). Heading and roll still follow the new pose, so a turned-out leg keeps its turned-out foot."""
    d_now = (now @ Vector((0, 1, 0))).normalized()
    d_was = (was @ Vector((0, 1, 0))).normalized()
    flat = Vector((d_now.x, d_now.y, 0))
    if flat.length < 1e-3:  # the foot points straight up or down: no heading to keep
        return now
    flat.normalize()
    el = max(-1.0, min(1.0, d_was.z))
    want = flat * (1 - el * el) ** 0.5 + Vector((0, 0, el))
    return d_now.rotation_difference(want).to_matrix() @ now


def report_lines(new_name: str, rep: dict) -> list[str]:
    """The report's text lines for a finished Pose Adapt."""
    many = "," in str(rep["frame"])
    lines = [
        f"Pose Adapt: made {new_name} from your pose{'s' if many else ''} on frame{'s' if many else ''} {rep['frame']}",
        "",
        f"  changed: {', '.join(rep['changed'][:12])}{' ...' if len(rep['changed']) > 12 else ''}",
        f"  spread over: {rep['how']}",
    ]
    lines += [f"  note: {x}" for x in rep["notes"]]
    lines.append(f"  your pose kept on that frame to within {rep['pose_kept_deg']:.1f} degrees")
    if rep["worse"]:
        lines.append("  CHECK THIS: the edit made these worse (the copy is kept so you can judge):")
        lines += [f"    {v}" for v in rep["worse"]]
    lines += [f"  {v}" for v in rep["verdict"]]
    return lines
