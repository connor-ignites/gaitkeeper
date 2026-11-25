# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: fixes. Two-bone IK and foot locking (feet planted, never below the floor)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import bpy
from mathutils import Matrix, Vector

from . import motion_math
from .rig import key_rotation, set_rotation

DRAG_LIFT = 0.012  # m: a dragged foot is lifted until the ball of the foot is this far above its planted height
MAX_FOOT_NUDGE_M = 0.08  # a lock may nudge a planted foot this far; past it, it would change the move, not fix a slide
STEADY_STEP_SLIDE = 0.1  # m/s: a step that slides less than this is left exactly as made
PLANT_MAX_DEV = 2.0  # m/s: wider than the checks' 1 m/s, since a stumble hurries a planted foot on purpose
SOFTEN_MAX_M = 0.02  # the hand-over between locked and free frames moves a foot sideways by at most this


@dataclass(frozen=True)
class FixContext:
    """The rig and scene a person fix works on: the clip plays on `scene`, bone edits are evaluated through
    `view_layer`, and `cyclic` says whether the clip loops."""

    arm: bpy.types.Object
    roles: dict[str, str]
    fps: float
    cyclic: bool
    scene: bpy.types.Scene
    view_layer: bpy.types.ViewLayer


Leg = tuple[bpy.types.PoseBone, bpy.types.PoseBone, bpy.types.PoseBone]  # thigh, calf, foot


def two_bone_ik(
    arm: bpy.types.Object,
    thigh: bpy.types.PoseBone,
    calf: bpy.types.PoseBone,
    foot: bpy.types.PoseBone,
    target: Vector,
    foot_rot: Matrix,
    view_layer: bpy.types.ViewLayer,
) -> None:
    """Analytic IK in armature space: knee stays in its current bending plane, foot ends at
    `target` with the rotation it had before the edit."""
    hip, knee_now, ankle_now = thigh.head.copy(), calf.head.copy(), foot.head.copy()
    l1 = (arm.data.bones[calf.name].head_local - arm.data.bones[thigh.name].head_local).length
    l2 = (arm.data.bones[foot.name].head_local - arm.data.bones[calf.name].head_local).length
    to_t = target - hip
    d = max(1e-5, min(to_t.length, (l1 + l2) * 0.9995))
    dirn = to_t.normalized()
    # bend plane: from the current knee
    pole = (knee_now - hip) - dirn * (knee_now - hip).dot(dirn)
    if pole.length < 1e-6:
        pole = (ankle_now - hip).cross(Vector((1, 0, 0)))
    pole.normalize()
    cos_a = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
    a = math.acos(cos_a)
    knee = hip + dirn * (l1 * math.cos(a)) + pole * (l1 * math.sin(a))
    r1 = (knee_now - hip).rotation_difference(knee - hip).to_matrix().to_4x4()
    thigh.matrix = Matrix.Translation(hip) @ r1 @ Matrix.Translation(-hip) @ thigh.matrix
    view_layer.update()
    knee_new, ankle_new = calf.head.copy(), foot.head.copy()
    r2 = (ankle_new - knee_new).rotation_difference(target - knee_new).to_matrix().to_4x4()
    calf.matrix = Matrix.Translation(knee_new) @ r2 @ Matrix.Translation(-knee_new) @ calf.matrix
    view_layer.update()
    m = foot_rot.copy()
    m.translation = foot.head
    foot.matrix = m
    view_layer.update()


def foot_targets(
    ctx: FixContext,
    legs: list[Leg],
    n: int,
    ankle_heights: dict[str, list[float]],
    max_nudge: float | None = None,
) -> dict[str, list[Vector]]:
    """Where each ankle should be on each frame: planted feet are locked (moving only at the clip's
    steady in-place ground speed), fading in and out over a frame or two, and never below the
    original ankle's height on that frame (`ankle_heights`, per foot bone). Planted = the ball of the foot
    is down and still. The lock is worked out on the ball of the foot, the part on the ground (as the
    checks measure it): when the heel lifts the ankle slows while the ball keeps its path, so locking the
    ankle would push the ball off. The ankle then moves by the same correction."""
    ankles, balls = _sample_feet(ctx, legs, n)
    m = n - 1 if ctx.cyclic and n > 2 else n  # a loop's last frame repeats its first
    out = {}
    for _, _, foot in legs:
        path = _foot_path(ankles[foot.name][:m], balls[foot.name][:m], ankle_heights.get(foot.name), ctx, max_nudge)
        if m < n:
            path.append(path[0].copy())
        out[foot.name] = path
    return out


def _sample_feet(ctx: FixContext, legs: list[Leg], n: int) -> tuple[dict[str, list[Vector]], dict[str, list[Vector]]]:
    """Each foot's ankle and ball (its toe joint, or the ankle if it has no toe) on every frame."""
    ankles: dict[str, list[Vector]] = {foot.name: [] for _, _, foot in legs}
    balls: dict[str, list[Vector]] = {foot.name: [] for _, _, foot in legs}
    toe_of = {ctx.roles.get("foot_l"): ctx.roles.get("toe_l"), ctx.roles.get("foot_r"): ctx.roles.get("toe_r")}
    for f in range(n):
        ctx.scene.frame_set(f)
        for _, _, foot in legs:
            ankles[foot.name].append(foot.head.copy())
            toe = toe_of.get(foot.name)
            balls[foot.name].append(ctx.arm.pose.bones[toe].head.copy() if toe else foot.head.copy())
    return ankles, balls


def _foot_path(
    pos: list[Vector], ball: list[Vector], orig_z: list[float] | None, ctx: FixContext, max_nudge: float | None
) -> list[Vector]:
    """One ankle's target on each frame of the loop (or clip): locked where planted, eased in and out."""
    track = [tuple(p) for p in ball]
    heights = [p.z for p in ball]
    flags, raise_by = _plants_and_lifts(track, heights, ctx.fps, ctx.cyclic)
    locked = _locked_positions(pos, ball, track, flags, ctx.fps, ctx.cyclic, max_nudge)
    weights = motion_math.smooth_weights([1.0 if c else 0.0 for c in flags], 2, ctx.cyclic)  # 2-frame fade
    targets = []
    for i in range(len(pos)):
        # a lock may nudge a foot, not drag it: past the limit it is changing the move, not fixing a slide
        d = locked[i] - pos[i]
        if max_nudge is not None and d.length > max_nudge:
            locked[i] = pos[i] + d.normalized() * max_nudge
        t = pos[i].lerp(locked[i], weights[i])
        # never lower than the original foot at this moment (keeps toe clearance in the swing)
        t.z = max(t.z, orig_z[i] if orig_z else -math.inf) + raise_by[i]
        targets.append(t)
    return _soften_handover(targets, weights, ctx.cyclic)


def _plants_and_lifts(
    track: list[tuple], heights: list[float], fps: float, cyclic: bool
) -> tuple[list[bool], list[float]]:
    """(planted flags, how far to lift each frame). A drag (the foot races along with its toes on the
    floor) can't be fixed by locking, since the foot has to travel: it is lifted just clear (DRAG_LIFT
    above its usual planted height) and swings instead."""
    m = len(heights)
    speeds = []
    for i in range(m):
        j = (i + 1) % m if cyclic else min(i + 1, m - 1)
        speeds.append(abs(heights[j] - heights[i]) * fps)
    down = motion_math.contacts(heights, speeds, min(heights))
    flags = motion_math.drop_sweeps(track, down, fps, cyclic, heights=heights, max_dev=PLANT_MAX_DEV, lift=-1.0)
    swept = motion_math.drop_sweeps(track, down, fps, cyclic, heights=heights, max_dev=PLANT_MAX_DEV)
    drag = [a and not b for a, b in zip(swept, flags)]
    rest = sorted(heights[i] for i in range(m) if flags[i]) or [min(heights)]
    ground = rest[len(rest) // 2]  # the ball's usual planted height (lifting drags removes the lowest)
    raise_by = [max(0.0, ground + DRAG_LIFT - heights[i]) if drag[i] else 0.0 for i in range(m)]
    raise_by = [
        max(r, 0.5 * max(raise_by[(i - 1) % m], raise_by[(i + 1) % m]) if cyclic or 0 < i < m - 1 else r)
        for i, r in enumerate(raise_by)
    ]  # ease the lift in and out over a frame
    return flags, raise_by


def _locked_positions(
    pos: list[Vector],
    ball: list[Vector],
    track: list[tuple],
    flags: list[bool],
    fps: float,
    cyclic: bool,
    max_nudge: float | None,
) -> list[Vector]:
    """The ankle on each frame with every sliding planted step moved onto the steady in-place path."""
    m = len(pos)
    tm = motion_math.treadmill_velocity(track, flags, fps, robust=True)
    locked = [p.copy() for p in pos]
    for start, length in motion_math.runs(flags, cyclic):
        idx = [(start + k) % m for k in range(length)]
        step = [track[i] for i in idx]
        if length >= 2 and motion_math.slide_per_contact(step, [True] * length, fps, False, tm)[0] < STEADY_STEP_SLIDE:
            continue  # this step doesn't slide: leave it exactly as made
        # the steady path through the typical (median) planted frame, not one pinned to the first
        # frame: the part of the step that is already steady stays put, the odd frames are nudged
        offs = [(ball[i].x - tm[0] * k / fps, ball[i].y - tm[1] * k / fps) for k, i in enumerate(idx)]
        cx = sorted(o[0] for o in offs)[length // 2]
        cy = sorted(o[1] for o in offs)[length // 2]
        fixes = [
            Vector((cx + tm[0] * k / fps - ball[i].x, cy + tm[1] * k / fps - ball[i].y, 0)) for k, i in enumerate(idx)
        ]
        if max_nudge is not None and max(f.length for f in fixes) > max_nudge:
            continue  # it would take more than a nudge: that changes the move, so leave this step as made
        for f, i in zip(fixes, idx):
            locked[i] = pos[i] + f
    return locked


def _soften_handover(targets: list[Vector], weights: list[float], cyclic: bool) -> list[Vector]:
    """Soften the hand-over between locked and free frames so the knee doesn't snap: sideways only
    (averaging heights pulled a foot coming down too low), and by SOFTEN_MAX_M at most (next to a
    fast-moving frame an average drags a planted foot along)."""
    m = len(targets)
    out = []
    for i, hard in enumerate(targets):
        if not 0 < weights[i] < 1:
            out.append(Vector((hard.x, hard.y, hard.z)))
            continue
        near = (targets[(i + k) % m] if cyclic else targets[max(0, min(m - 1, i + k))] for k in (-1, 0, 1))
        avg = sum(near, Vector((0, 0, 0))) / 3
        d = Vector((avg.x - hard.x, avg.y - hard.y, 0))
        if d.length > SOFTEN_MAX_M:
            d = d.normalized() * SOFTEN_MAX_M
        out.append(Vector((hard.x + d.x, hard.y + d.y, hard.z)))
    return out


def root_motion_pass(ctx: FixContext, n: int, mode: str) -> str:
    """mode "extract": the body's steady travel moves onto the root bone (sway stays on the hips).
    mode "in_place": the steady travel is removed, so the clip walks on the spot.
    Returns a plain-English note."""
    scene, view_layer = ctx.scene, ctx.view_layer
    hips = ctx.arm.pose.bones.get(ctx.roles.get("hips", ""))
    if hips is None or hips.parent is None:
        return "root motion: skipped (no root bone above the hips)"
    root = hips
    while root.parent is not None:
        root = root.parent
    flat = Vector((1, 1, 0))
    scene.frame_set(0)
    h0, r0 = hips.head.copy(), root.head.copy()
    scene.frame_set(n - 1)
    total = (hips.head - h0) * flat  # how far the body travels
    on_root = (root.head - r0) * flat  # how much of that the root already carries
    own = total - on_root  # travel stored on the hips
    for f in range(n):
        scene.frame_set(f)
        u = f / max(1, n - 1)
        root_now = (root.head - r0) * flat
        want_root = total * u if mode == "extract" else Vector((0, 0, 0))
        root.matrix = Matrix.Translation(want_root - root_now) @ root.matrix
        view_layer.update()
        # the hips lose their own steady travel; in "in_place" they also lose what the root carried
        # (moving the root already took that away), so only `own` is removed in both modes
        hips.matrix = Matrix.Translation(-own * u) @ hips.matrix
        view_layer.update()
        for pb in (root, hips):
            pb.keyframe_insert("location", frame=f, group=pb.name)
            key_rotation(pb, f)
    word = "moved onto the root bone" if mode == "extract" else "removed (walks on the spot)"
    return f"root motion: {total.length:.2f} m of travel {word}"


def smooth_pops(
    arm: bpy.types.Object, pops: dict[str, list[int]], n: int, scene: bpy.types.Scene, start: int = 0
) -> int:
    """Spread each one-frame snap over its neighbours: the poses either side of the jump are
    re-keyed halfway between their own neighbours. `pops` holds sample indices; sample j is frame
    start + j. Returns how many keys were changed."""
    changed = 0
    for name, frames in pops.items():
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        rots = []
        for j in range(n):
            scene.frame_set(start + j)
            rots.append(tuple(pb.matrix_basis.to_quaternion()))
        for i in frames:
            for j in (i, i + 1):
                if 0 < j < n - 1:
                    rots[j] = motion_math.q_slerp(rots[j - 1], rots[j + 1], 0.5)
                    scene.frame_set(start + j)
                    set_rotation(pb, rots[j])
                    key_rotation(pb, start + j)
                    changed += 1
    return changed
