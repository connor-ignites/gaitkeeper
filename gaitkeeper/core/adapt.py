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

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import adapt_math as am
from . import motion_math as mm
from .checks import measure, verdicts
from .edit import write_action
from .fix import smooth_pops, two_bone_ik
from .rig import body_axes, clip_range, contact_flags, leg_sides, sample, set_action, split_name

Pose = dict[str, tuple[tuple, tuple, tuple]]
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


def adapt_clip(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    roles: dict[str, str],
    fps: float,
    frame: int,
    edited: Pose,
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
    `judge(action) -> verdict lines` checks an animal (roles from creature.leg_roles); None: a person,
    judged by the person checks."""
    if mode not in am.MODES:
        raise ValueError(f"unknown spread mode {mode!r}")
    a, b = clip_range(act)
    poses = dict(more)
    poses[frame] = edited
    for f in poses:
        if not a <= f <= b:
            raise ValueError(f"frame {f} is outside the clip ({a} to {b})")
    before = sample(arm, act, roles)
    n = len(before.basis)
    keys = []  # (clip frame index, change per bone, the pose as made)
    for f in sorted(poses):
        d = pose_delta(poses[f], before.basis[f - a])
        if d:
            keys.append((f - a, d, poses[f]))
    if not keys:
        raise ValueError("nothing changed: pose a bone on this frame first (without keying it), then Adapt")
    idx = keys[0][0]
    changed = sorted({bn for _, d, _ in keys for bn in d})
    if cyclic is None:
        cyclic = "loop" in act.name.lower()
    report: dict = {
        "original": measure(before, fps, cyclic, arm, act.name) if judge is None else {},
        "notes": [],
        "changed": changed,
        "frame": ", ".join(str(k[0] + a) for k in keys),
    }
    travels = (
        report["original"].get("travels", False)
        if judge is None
        else "hips" in before.world[0] and mm.dist2d(before.world[0]["hips"], before.world[-1]["hips"]) > 0.3
    )
    sides = leg_sides(roles)
    m = am.loop_frames(n, cyclic)

    period, alternate, together = None, False, False
    if mode == "steps" or mirror:
        left, right = gait_channels(before, roles, arm, m)
        if left and right:
            period = am.step_period(left, fps, cyclic)
            alternate = bool(period) and am.sides_alternate(left, right, period, cyclic)
            together = not alternate and am.sides_together(left, right, cyclic)
    report["period"] = period
    use_mode = mode
    if mode == "steps" and not period:
        use_mode = "here"
        report["notes"].append(
            "no repeating step found in this clip, so the change fades in and out around the frame instead"
        )
    use_mirror = mirror
    if use_mode == "steps" and mirror and not alternate:
        if together:
            report["notes"].append(
                "both legs move together in this clip (a hop), so the other side got the same change at the same moment"
            )
        else:
            use_mirror = False
            report["notes"].append("the two sides don't take turns in this clip, so the other side was left alone")
    if use_mode == "here":
        use_mirror = False
    length, wraps, radius = am.axis(n, use_mode, cyclic, spread, period)

    def at(i: int) -> float:
        return am.position(i, n, use_mode, cyclic, period)

    # a leg changed mid-swing stays in the swing, one changed while planted stays in the stance:
    # otherwise the fade would carry the change onto a planted foot and drag it
    down = (
        {sd: contact_flags(before, sd, fps, cyclic) for sd in sides if f"ankle_{sd}" in before.world[0]}
        if use_mode != "whole"
        else {}
    )
    side_of = {roles[f"{r}_{sd}"]: sd for r in LEG_ROLES for sd in sides if f"{r}_{sd}" in roles}

    def gate(bone: str, key_idx: int, src_side: str | None, mirrored: bool) -> list[float] | None:
        sd = side_of.get(bone)
        if sd not in down:
            return None
        state = down.get(src_side or sd, down[sd])[key_idx]
        g = mm.smooth_weights([1.0 if c == state else 0.0 for c in down[sd]], 2, cyclic)
        top = max(g) if mirrored else g[key_idx]
        return [min(1.0, x / max(top, 1e-6)) for x in g]

    # every bone's poses on the axis: (position, location change, rotation change, gate)
    right = arm.matrix_world.to_3x3().inverted() @ body_axes(arm, roles)[1]
    twin_of = pairs(arm)
    track: dict[str, dict[float, tuple[Vector, Quaternion, list[float] | None]]] = {}
    mirrored_any = False
    for ki, d, _ in keys:
        for bone, (dl, dq) in d.items():
            track.setdefault(bone, {})[at(ki)] = (dl, dq, gate(bone, ki, None, False))
    if use_mirror:
        for ki, d, _ in keys:
            for bone, (dl, dq) in d.items():
                twin = twin_of.get(bone)
                if twin is None or (use_mode == "whole" and (twin == bone or twin in d)):
                    continue  # whole clip: a centre bone mirrored onto itself would cancel; an edited twin is yours
                pos = (at(ki) + length / 2) % length if use_mode == "steps" and alternate else at(ki)
                if pos == at(ki) and (twin == bone or twin in d):
                    continue  # at the same moment: a centre bone would cancel; an edited twin is yours
                if pos in track.get(twin, {}):
                    continue  # a pose made on the twin itself there wins
                dlm, dqm = mirror_delta(arm, bone, twin, dl, dq, right)
                track.setdefault(twin, {})[pos] = (dlm, dqm, gate(twin, ki, side_of.get(bone), True))
                mirrored_any = True
    report["how"] = am.describe(use_mode, n, cyclic, spread, period, [k[0] for k in keys], mirrored_any)
    if together and use_mode == "steps":
        report["how"] = report["how"].replace("mirrored on the other foot's step", "both legs together")
    if any(g is not None for t in track.values() for (_, _, g) in t.values()):
        report["notes"].append(
            "leg changes kept to the part of the step they were made in (swing or planted), so planted feet don't drag"
        )
    if len(keys) > 1:
        report["notes"].append("between poses close together the change runs smoothly from one to the next")

    frames = []
    plans = {bone: sorted(t) for bone, t in track.items()}
    for i in range(n):
        fr = dict(before.basis[i])
        x = at(i)
        for bone, spots in plans.items():
            plan = am.blend_plan(spots, x, length, wraps, radius)
            if plan is None:
                continue
            ka, kb, u, w = plan
            dla, dqa, ga = track[bone][spots[ka]]
            dlb, dqb, gb = track[bone][spots[kb]]
            g = (ga[i] if ga else 1.0) * (1 - u) + (gb[i] if gb else 1.0) * u
            _apply(fr, bone, dla.lerp(dlb, u), dqa.slerp(dqb, u), w * g)
        frames.append(fr)
    mdelta = {bn for bn in track if not any(bn in d for _, d, _ in keys)}
    delta = {bn: None for _, d, _ in keys for bn in d}

    # which legs the animator touched (directly or through the mirror)
    touched = set(delta) | set(mdelta)
    legs = []
    for side in sides:
        names = [roles.get(f"{r}_{side}") for r in ("thigh", "calf", "foot")]
        if all(names):
            own = {roles.get(f"{r}_{side}") for r in LEG_ROLES}
            legs.append((side, *names, bool(own & touched)))
    scn = bpy.context.scene
    orig_feet: dict[str, list[Matrix]] = {}
    if keep_feet:
        for f in range(n):
            scn.frame_set(a + f)
            for side, _, _, foot, _ in legs:
                orig_feet.setdefault(foot, []).append(arm.pose.bones[foot].matrix.copy())
                toe = roles.get(f"toe_{side}")
                if toe:  # the ball of the foot, kept as a translation-only matrix
                    orig_feet.setdefault(toe, []).append(Matrix.Translation(arm.pose.bones[toe].head))

    new = write_action(arm, frames, name or f"{act.name.split('|')[-1]}_adapted")
    if keep_feet and legs:
        _keep_feet(arm, legs, orig_feet, before, roles, n, fps, cyclic and not travels, touched)
        kept = [leg_label(s, sides) for s, *_, t in legs if not t]
        moved = [leg_label(s, sides) for s, *_, t in legs if t]
        if kept:
            report["notes"].append(
                f"{', '.join(kept)} {'feet' if len(kept) > 1 else 'foot'} kept where "
                f"{'they were' if len(kept) > 1 else 'it was'}".replace("left, right feet", "both feet").replace(
                    "back left, back right, front left, front right feet", "all four feet"
                )
            )
        if moved:
            report["notes"].append(
                f"{', '.join(moved)} {'feet follow' if len(moved) > 1 else 'foot follows'} your "
                "pose, planted steps held on the ground".replace("left, right feet", "both feet")
            )

    if judge is None:
        report["result"] = measure(sample(arm, new, roles), fps, cyclic, arm, act.name)
        for _ in range(3):  # an edit must not add snaps: smooth any new pops, then measure again
            fresh = {bn: f for bn, f in report["result"]["pops"].items() if bn not in report["original"]["pops"]}
            if not fresh:
                break
            smooth_pops(arm, fresh, n)
            report["result"] = measure(sample(arm, new, roles), fps, cyclic, arm, act.name)
        report["verdict"] = verdicts(report["original"], report["result"], fixing=True)
        was = verdicts(report["original"], None)
        report["worse"] = [v for v in report["verdict"] if v.startswith(("FAIL", "WARN")) and v not in was]
    else:
        was, now = judge(act), judge(new)
        report["verdict"] = now
        report["worse"] = [
            v for v in now if v.startswith(("FAIL", "WARN")) and same_words(v) not in {same_words(x) for x in was}
        ]

    # how close the result is to the poses the animator made, on their frames
    set_action(arm, new)
    worst = 0.0
    for ki, d, pose in keys:
        scn.frame_set(ki)
        for bone in d:
            q_now = tuple(arm.pose.bones[bone].matrix_basis.to_quaternion())
            worst = max(worst, mm.q_angle_deg(q_now, pose[bone][1]))
    scn.frame_set(idx)
    report["pose_kept_deg"] = round(worst, 2)
    new.use_fake_user = True
    return new, report


def _keep_feet(
    arm: bpy.types.Object,
    legs: list,
    orig_feet: dict[str, list[Matrix]],
    before: object,
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
    scn = bpy.context.scene
    pb = arm.pose.bones
    m = am.loop_frames(n, cyclic)
    floor, plan = {}, {}
    for side, _, _, foot, leg_touched in legs:
        if not leg_touched or f"ankle_{side}" not in before.world[0]:  # type: ignore[attr-defined]
            continue
        floor[foot] = min(w[f"ankle_{side}"][2] for w in before.world)  # type: ignore[attr-defined]
        down = contact_flags(before, side, fps, cyclic)[:m]  # type: ignore[arg-type]
        own_foot = {roles.get(f"foot_{side}"), roles.get(f"toe_{side}")} & touched
        plan[foot] = (down, mm.smooth_weights([1.0 if c else 0.0 for c in down], 2, cyclic), not own_foot)
    new_pos: dict[str, list[Vector]] = {foot: [] for foot in plan}
    for f in range(m):
        scn.frame_set(f)
        for foot in plan:
            new_pos[foot].append(pb[foot].head.copy())
    targets: dict[str, list[Vector]] = {}
    for foot, (down, w, _) in plan.items():
        old = [orig_feet[foot][i].translation for i in range(m)]
        locked = list(new_pos[foot])
        for start, length in mm.runs(down, cyclic):
            run = [(start + k) % m for k in range(length)]
            anchor = max(run, key=lambda i: (new_pos[foot][i] - old[i]).length)  # where the edit moved it most
            shift = new_pos[foot][anchor] - old[anchor]
            for i in run:
                locked[i] = old[i] + shift
        tg = []
        for i in range(m):
            t = new_pos[foot][i].lerp(locked[i], w[i])
            # toe clearance: near the ground a swinging foot never drops below where it was (it would
            # scuff), higher up it may come down to CLEAR above the floor
            t.z = max(t.z, floor[foot], min(old[i].z, floor[foot] + CLEAR))
            tg.append(t)
        if m < n:
            tg.append(tg[0].copy())
        targets[foot] = tg
    ball_floor = {
        sd: min(w[f"ball_{sd}"][2] for w in before.world)  # type: ignore[attr-defined]
        for sd in leg_sides(roles)
        if f"ball_{sd}" in before.world[0]
    }  # type: ignore[attr-defined]
    # pass 1: where each foot goes and how it's turned, and how far the toes would dip below their
    # clearance. The foot is lifted by exactly that much: the ball then follows max(new height, clearance),
    # and both change smoothly, so the lift can't pop and needs no blur (a blur would lift planted frames)
    goal: dict[str, list[tuple[Vector, Matrix]]] = {}
    dip: dict[str, list[float]] = {}
    for f in range(n):
        scn.frame_set(f)
        for side, _, _, foot, leg_touched in legs:
            fb = pb[foot]
            if leg_touched and foot in targets:
                target, rot = targets[foot][f], fb.matrix.to_3x3().to_4x4()
                _, w, keep_flat = plan[foot]
                wf = w[f % m]
                if keep_flat:
                    rot = _keep_pitch(fb.matrix.to_3x3(), orig_feet[foot][f].to_3x3()).to_4x4()
                if keep_flat and wf > 0:
                    q = fb.matrix.to_quaternion().slerp(orig_feet[foot][f].to_quaternion(), wf)
                    rot = q.to_matrix().to_4x4()
                toe = roles.get(f"toe_{side}")
                low = 0.0
                if toe in orig_feet and side in ball_floor:
                    # the ball's height once the foot is at target with rotation rot
                    ball = target + rot.to_3x3() @ (fb.matrix.to_3x3().inverted() @ (pb[toe].head - fb.head))
                    need = min(orig_feet[toe][f].translation.z, ball_floor[side] + CLEAR_BALL)
                    low = max(0.0, need - ball.z)
                dip.setdefault(foot, []).append(low)
            else:
                target, rot = orig_feet[foot][f].translation.copy(), orig_feet[foot][f].to_3x3().to_4x4()
            goal.setdefault(foot, []).append((target, rot))
    lift = dip
    # pass 2: put every foot there with two-bone IK and key the leg
    for f in range(n):
        scn.frame_set(f)
        for _, thigh, calf, foot, _ in legs:
            fb = pb[foot]
            target, rot = goal[foot][f]
            if foot in lift and lift[foot][f] > 0:
                target = target + Vector((0, 0, lift[foot][f]))
            off = (fb.head - target).length
            turn = mm.q_angle_deg(tuple(fb.matrix.to_quaternion()), tuple(rot.to_quaternion()))
            if off < 5e-4 and turn < 0.1:
                continue
            two_bone_ik(arm, pb[thigh], pb[calf], fb, target, rot)
            for bone in (pb[thigh], pb[calf], fb):
                bone.keyframe_insert("rotation_quaternion", frame=f, group=bone.name)
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
