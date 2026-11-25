# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: fixes. Two-bone IK and foot locking (feet planted, never below the floor)."""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Vector

from . import motion_math as mm
from .rig import key_rotation, set_rotation

DRAG_LIFT = 0.012  # m: a dragged foot is lifted until the ball of the foot is this far above its planted height


def two_bone_ik(
    arm: bpy.types.Object,
    thigh: bpy.types.PoseBone,
    calf: bpy.types.PoseBone,
    foot: bpy.types.PoseBone,
    target: Vector,
    foot_rot: Matrix,
) -> None:
    """Analytic IK in armature space: knee stays in its current bending plane, foot ends at
    `target` with the rotation it had before the edit."""
    H, K, A = thigh.head.copy(), calf.head.copy(), foot.head.copy()
    l1 = (arm.data.bones[calf.name].head_local - arm.data.bones[thigh.name].head_local).length
    l2 = (arm.data.bones[foot.name].head_local - arm.data.bones[calf.name].head_local).length
    to_t = target - H
    d = max(1e-5, min(to_t.length, (l1 + l2) * 0.9995))
    dirn = to_t.normalized()
    # bend plane: from the current knee
    pole = (K - H) - dirn * (K - H).dot(dirn)
    if pole.length < 1e-6:
        pole = (A - H).cross(Vector((1, 0, 0)))
    pole.normalize()
    cos_a = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
    a = math.acos(cos_a)
    knee = H + dirn * (l1 * math.cos(a)) + pole * (l1 * math.sin(a))
    r1 = (K - H).rotation_difference(knee - H).to_matrix().to_4x4()
    thigh.matrix = Matrix.Translation(H) @ r1 @ Matrix.Translation(-H) @ thigh.matrix
    bpy.context.view_layer.update()
    K2, A2 = calf.head.copy(), foot.head.copy()
    r2 = (A2 - K2).rotation_difference(target - K2).to_matrix().to_4x4()
    calf.matrix = Matrix.Translation(K2) @ r2 @ Matrix.Translation(-K2) @ calf.matrix
    bpy.context.view_layer.update()
    m = foot_rot.copy()
    m.translation = foot.head
    foot.matrix = m
    bpy.context.view_layer.update()


def foot_targets(
    arm: bpy.types.Object,
    legs: list[tuple],
    n: int,
    fps: float,
    cyclic: bool,
    floor: dict[str, float],
    roles: dict[str, str],
    orig_z: dict[str, list[float]],
    max_nudge: float | None = None,
) -> dict[str, list[Vector]]:
    """Where each ankle should be on each frame: planted feet are locked (moving only at the clip's
    steady in-place ground speed), fading in and out over a frame or two, and never below the
    original clip's lowest ankle height. Planted = the ball of the foot is down and still. The lock is
    worked out on the ball of the foot, the part on the ground (as the checks measure it): when the
    heel lifts the ankle slows while the ball keeps its path, so locking the ankle would push the ball
    off. The ankle then moves by the same correction."""
    scn = bpy.context.scene
    cur: dict[str, list[Vector]] = {foot.name: [] for _, _, foot in legs}
    ball: dict[str, list[float]] = {foot.name: [] for _, _, foot in legs}
    ballp: dict[str, list[Vector]] = {foot.name: [] for _, _, foot in legs}
    toe_of = {roles.get("foot_l"): roles.get("toe_l"), roles.get("foot_r"): roles.get("toe_r")}
    for f in range(n):
        scn.frame_set(f)
        for _, _, foot in legs:
            cur[foot.name].append(foot.head.copy())
            tb = toe_of.get(foot.name)
            ball[foot.name].append(arm.pose.bones[tb].head.z if tb else foot.head.z)
            ballp[foot.name].append(arm.pose.bones[tb].head.copy() if tb else foot.head.copy())
    out = {}
    m = n - 1 if cyclic and n > 2 else n  # a loop's last frame repeats its first
    for _, _, foot in legs:
        pos = cur[foot.name][:m]
        bp = ballp[foot.name][:m]
        tup = [tuple(p) for p in bp]
        h = ball[foot.name][:m]
        sp = []
        for i in range(m):
            j = (i + 1) % m if cyclic else min(i + 1, m - 1)
            sp.append(abs(h[j] - h[i]) * fps)
        # a wider margin than the checks' 1 m/s: a limp or a stumble hurries a planted foot on purpose,
        # and a planted frame left unlocked keeps its slide
        down = mm.contacts(h, sp, min(h))
        flags = mm.drop_sweeps(tup, down, fps, cyclic, heights=h, max_dev=2.0, lift=-1.0)
        # a drag: the foot races along with its toes on the floor. Locking can't fix that (the foot has
        # to travel), so it is lifted just clear (DRAG_LIFT above its lowest point) and swings instead
        drag = [a and not b for a, b in zip(mm.drop_sweeps(tup, down, fps, cyclic, heights=h, max_dev=2.0), flags)]
        rest = sorted(h[i] for i in range(m) if flags[i]) or [min(h)]
        ground = rest[len(rest) // 2]  # the ball's usual planted height (lifting drags removes the lowest)
        raise_by = [max(0.0, ground + DRAG_LIFT - h[i]) if drag[i] else 0.0 for i in range(m)]
        raise_by = [
            max(r, 0.5 * max(raise_by[(i - 1) % m], raise_by[(i + 1) % m]) if cyclic or 0 < i < m - 1 else r)
            for i, r in enumerate(raise_by)
        ]  # ease the lift in and out over a frame
        tm = mm.treadmill_velocity(tup, flags, fps, robust=True)
        locked = [p.copy() for p in pos]
        for start, length in mm.runs(flags, cyclic):
            idx = [(start + k) % m for k in range(length)]
            if length >= 2 and mm.slide_per_contact([tup[i] for i in idx], [True] * length, fps, False, tm)[0] < 0.1:
                continue  # this step doesn't slide: leave it exactly as made
            # the steady path through the typical (median) planted frame, not one pinned to the first
            # frame: the part of the step that is already steady stays put, the odd frames are nudged
            offs = [(bp[i].x - tm[0] * k / fps, bp[i].y - tm[1] * k / fps) for k, i in enumerate(idx)]
            cx = sorted(o[0] for o in offs)[length // 2]
            cy = sorted(o[1] for o in offs)[length // 2]
            fixes = [
                Vector((cx + tm[0] * k / fps - bp[i].x, cy + tm[1] * k / fps - bp[i].y, 0)) for k, i in enumerate(idx)
            ]
            if max_nudge is not None and max(f.length for f in fixes) > max_nudge:
                continue  # it would take more than a nudge: that changes the move, so leave this step as made
            for f, i in zip(fixes, idx):
                locked[i] = pos[i] + f
        w = mm.smooth_weights([1.0 if c else 0.0 for c in flags], 2, cyclic)  # 2-frame fade in and out
        fz = floor.get(foot.name, -math.inf)
        oz = orig_z.get(foot.name)
        tg = []
        for i in range(m):
            # a lock may nudge a foot, not drag it: past 8 cm it is changing the move, not fixing a slide
            d = locked[i] - pos[i]
            if max_nudge is not None and d.length > max_nudge:
                locked[i] = pos[i] + d.normalized() * max_nudge
            t = pos[i].lerp(locked[i], w[i])
            # never lower than the original foot at this moment (keeps toe clearance in the swing)
            t.z = max(t.z, fz, oz[i] if oz else -math.inf) + raise_by[i]
            tg.append(t)
        # soften the hand-over between locked and free so the knee doesn't snap
        hard = [t.copy() for t in tg]
        tg = [
            sum((tg[(i + k) % m] if cyclic else tg[max(0, min(m - 1, i + k))] for k in (-1, 0, 1)), Vector((0, 0, 0)))
            / 3
            if 0 < w[i] < 1
            else tg[i]
            for i in range(m)
        ]
        for i in range(m):  # soften sideways only (averaging heights pulled a foot coming down too low),
            # and by 2 cm at most: next to a fast-moving frame an average drags a planted foot along
            d = Vector((tg[i].x - hard[i].x, tg[i].y - hard[i].y, 0))
            if d.length > 0.02:
                d = d.normalized() * 0.02
            tg[i] = Vector((hard[i].x + d.x, hard[i].y + d.y, hard[i].z))
        if m < n:
            tg.append(tg[0].copy())
        out[foot.name] = tg
    return out


def root_motion_pass(arm: bpy.types.Object, roles: dict[str, str], n: int, mode: str) -> str:
    """mode "extract": the body's steady travel moves onto the root bone (sway stays on the hips).
    mode "in_place": the steady travel is removed, so the clip walks on the spot.
    Returns a plain-English note."""
    hips = arm.pose.bones.get(roles.get("hips", ""))
    if hips is None or hips.parent is None:
        return "root motion: skipped (no root bone above the hips)"
    root = hips
    while root.parent is not None:
        root = root.parent
    flat = Vector((1, 1, 0))
    scn = bpy.context.scene
    scn.frame_set(0)
    h0, r0 = hips.head.copy(), root.head.copy()
    scn.frame_set(n - 1)
    total = (hips.head - h0) * flat  # how far the body travels
    on_root = (root.head - r0) * flat  # how much of that the root already carries
    own = total - on_root  # travel stored on the hips
    for f in range(n):
        scn.frame_set(f)
        u = f / max(1, n - 1)
        root_now = (root.head - r0) * flat
        want_root = total * u if mode == "extract" else Vector((0, 0, 0))
        root.matrix = Matrix.Translation(want_root - root_now) @ root.matrix
        bpy.context.view_layer.update()
        # the hips lose their own steady travel; in "in_place" they also lose what the root carried
        # (moving the root already took that away), so only `own` is removed in both modes
        hips.matrix = Matrix.Translation(-own * u) @ hips.matrix
        bpy.context.view_layer.update()
        for pb in (root, hips):
            pb.keyframe_insert("location", frame=f, group=pb.name)
            key_rotation(pb, f)
    word = "moved onto the root bone" if mode == "extract" else "removed (walks on the spot)"
    return f"root motion: {total.length:.2f} m of travel {word}"


def smooth_pops(arm: bpy.types.Object, pops: dict[str, list[int]], n: int, start: int = 0) -> int:
    """Spread each one-frame snap over its neighbours: the poses either side of the jump are
    re-keyed halfway between their own neighbours. `pops` holds sample indices; sample j is frame
    start + j. Returns how many keys were changed."""
    scn = bpy.context.scene
    changed = 0
    for name, frames in pops.items():
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        rots = []
        for j in range(n):
            scn.frame_set(start + j)
            rots.append(tuple(pb.matrix_basis.to_quaternion()))
        for i in frames:
            for j in (i, i + 1):
                if 0 < j < n - 1:
                    rots[j] = mm.q_slerp(rots[j - 1], rots[j + 1], 0.5)
                    scn.frame_set(start + j)
                    set_rotation(pb, rots[j])
                    key_rotation(pb, start + j)
                    changed += 1
    return changed
