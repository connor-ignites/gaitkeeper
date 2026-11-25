# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: editing a clip in Blender (the Fix button and Pose Adapt).

apply_local_and_time works on sampled frames (local pose of every bone); write_action keys them as a
new action; world_pass then makes the world-space changes per frame (leans, pelvis, bounce) and
re-plants the feet with two-bone IK so an edit never pushes a foot through the floor or skates it.
fix_clip runs the standard fix (re-plant feet, close the loop seam, smooth new pops) on a copy.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import motion_math as mm
from .checks import measure, verdicts
from .fix import foot_targets, root_motion_pass, smooth_pops, two_bone_ik
from .rig import (
    Sample,
    body_axes,
    clip_range,
    contact_flags,
    interp_basis,
    interp_list,
    key_rotation,
    sample,
    set_action,
    set_rotation,
)


def bone_group(group: str, roles: dict[str, str], arm: bpy.types.Object) -> list[str]:
    g = {
        "arms": ["upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r"],
        "legs": ["thigh_l", "thigh_r", "calf_l", "calf_r", "foot_l", "foot_r"],
        "spine": ["spine1", "spine2", "spine3"],
        "head": ["neck", "head"],
    }
    if group == "all":
        skip = {"root"}
        return [pb.name for pb in arm.pose.bones if pb.name.lower() not in skip and pb.parent is not None]
    if group in g:
        return [roles[r] for r in g[group] if r in roles]
    if group in roles:
        return [roles[group]]
    return [group] if group in arm.pose.bones else []


def apply_local_and_time(
    s: Sample, ops: list[dict], roles: dict[str, str], arm: bpy.types.Object, fps: float, cyclic: bool
) -> tuple[list[dict], list[dict], list[str]]:
    """Returns (frames, per-frame world-pass weights, notes)."""
    frames = [dict(f) for f in s.basis]
    n = len(frames)
    notes: list[str] = []
    wts: dict[str, list[float]] = {}

    # 1. local, axis-free edits at the original timing
    for op in ops:
        kind = op["op"]
        if kind == "exaggerate":
            names = bone_group(op.get("bones", "all"), roles, arm)
            fac = float(op["factor"])
            for nm in names:
                mean = mm.q_mean([f[nm][1] for f in frames])
                for f in frames:
                    loc, q, sc = f[nm]
                    f[nm] = (loc, mm.q_scale_from(q, mean, fac), sc)
            notes.append(f"{op.get('bones', 'all')} motion x{fac:.2f}")
        elif kind == "limp":
            side = op.get("side", "l")
            a = float(op.get("amount", 0.6))
            for role, fac in ((f"calf_{side}", 1 - 0.65 * a), (f"thigh_{side}", 1 - 0.3 * a)):
                nm = roles.get(role)
                if not nm:
                    continue
                mean = mm.q_mean([f[nm][1] for f in frames])
                for f in frames:
                    loc, q, sc = f[nm]
                    f[nm] = (loc, mm.q_scale_from(q, mean, fac), sc)
            other = "r" if side == "l" else "l"
            hurt = mm.smooth_weights([1.0 if c else 0.0 for c in contact_flags(s, side, fps, cyclic)], 2, cyclic)
            good = mm.smooth_weights([1.0 if c else 0.0 for c in contact_flags(s, other, fps, cyclic)], 2, cyclic)
            wts["limp_hurt"] = hurt
            wts["limp_rates"] = [1 + 0.7 * a * h - 0.3 * a * g for h, g in zip(hurt, good)]
            wts["limp_amount"] = [a] * n
            wts["limp_side"] = [0.0 if side == "l" else 1.0] * n
            notes.append(f"limp on the {'left' if side == 'l' else 'right'} leg ({a:.2f})")

    # the original feet's world rotation travels with the timing, so planted feet keep their roll
    for side in "lr":
        nm = roles.get(f"foot_{side}")
        if nm:
            ref = s.world_q[0][nm]
            qs = [mm.q_align(w[nm], ref) for w in s.world_q]
            for c in range(4):
                wts[f"footq_{side}_{c}"] = [q[c] for q in qs]
        if f"ankle_{side}" in s.world[0]:
            wts[f"anklez_{side}"] = [w[f"ankle_{side}"][2] for w in s.world]

    # 2. time edits
    times = list(range(n))
    if "limp_rates" in wts:
        times = mm.timewarp(wts["limp_rates"])
    speed = 1.0
    for op in ops:
        if op["op"] == "speed":
            speed *= float(op["factor"])
    if abs(speed - 1) > 1e-3:
        src = mm.resample_times(len(times), speed)
        times = [interp_list([float(t) for t in times], t) for t in src]
        notes.append(f"{speed:.2f}x as long ({'slower' if speed > 1 else 'faster'})")
    if times != list(range(n)):
        frames = [interp_basis(frames, t) for t in times]
        wts = {k: [interp_list(v, t) for t in times] for k, v in wts.items()}

    # 3. smoothing and loop seam
    for op in ops:
        if op["op"] == "smooth":
            r = int(op.get("radius", 1))
            names = list(frames[0].keys())
            new = []
            for i in range(len(frames)):
                fr = {}
                for nm in names:
                    qs, ls = [], []
                    for k in range(-r, r + 1):
                        j = (i + k) % len(frames) if cyclic else max(0, min(len(frames) - 1, i + k))
                        qs.append(frames[j][nm][1])
                        ls.append(frames[j][nm][0])
                    loc = tuple(sum(c) / len(ls) for c in zip(*ls))
                    fr[nm] = (loc, mm.q_mean(qs), frames[i][nm][2])
                new.append(fr)
            frames = new
            notes.append(f"smoothed (radius {r})")
    if cyclic or any(op["op"] == "fix_loop" for op in ops):
        blend = next((int(op.get("frames", 4)) for op in ops if op["op"] == "fix_loop"), 3)
        w = mm.loop_blend_weights(len(frames), blend)
        first = frames[0]
        for i, wi in enumerate(w):
            if wi <= 0:
                continue
            fr = {}
            for nm, (loc, q, sc) in frames[i].items():
                l0, q0, _s0 = first[nm]
                fr[nm] = (tuple(x + (y - x) * wi for x, y in zip(loc, l0)), mm.q_slerp(q, q0, wi), sc)
            frames[i] = fr

    world_ops = [op for op in ops if op["op"] in ("lean", "head", "pelvis", "bounce")]
    per_frame: list[dict] = [{} for _ in frames]
    for i in range(len(frames)):
        for k, v in wts.items():
            per_frame[i][k] = v[i]
    for op in world_ops:
        notes.append(describe(op))
    return frames, per_frame, notes


def describe(op: dict) -> str:
    k = op["op"]
    if k == "lean":
        return f"lean {op.get('dir', 'forward')} {float(op.get('degrees', 0)):.0f} degrees"
    if k == "head":
        return (
            f"head {'down' if float(op.get('degrees', 0)) > 0 else 'up'} {abs(float(op.get('degrees', 0))):.0f} degrees"
        )
    if k == "pelvis":
        drop = float(op.get("drop", 0))
        return f"hips {'lower' if drop > 0 else 'higher'} by {abs(drop) * 100:.0f} cm"
    if k == "bounce":
        return f"up-down bounce x{float(op.get('factor', 1)):.2f}"
    return k


def write_action(arm: bpy.types.Object, frames: list[dict], name: str) -> bpy.types.Action:
    act = bpy.data.actions.new(name)
    set_action(arm, act)
    for i, fr in enumerate(frames):
        for pb in arm.pose.bones:
            loc, q, sc = fr[pb.name]
            pb.location, pb.scale = loc, sc
            set_rotation(pb, q)
            pb.keyframe_insert("location", frame=i, group=pb.name)
            key_rotation(pb, i)
            pb.keyframe_insert("scale", frame=i, group=pb.name)
    return act


def rotate_about(
    pb: bpy.types.PoseBone, axis: Vector, deg: float, arm: bpy.types.Object, view_layer: bpy.types.ViewLayer
) -> None:
    """Rotate a pose bone about a world axis through its head, keeping children attached."""
    if abs(deg) < 1e-4:
        return
    inv = arm.matrix_world.to_3x3().inverted()
    ax = (inv @ axis).normalized()
    R = Quaternion(ax, math.radians(deg)).to_matrix().to_4x4()
    h = pb.head.copy()
    pb.matrix = Matrix.Translation(h) @ R @ Matrix.Translation(-h) @ pb.matrix
    view_layer.update()


def world_pass(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    ops: list[dict],
    per_frame: list[dict],
    roles: dict[str, str],
    fps: float,
    cyclic: bool,
    floor: dict[str, float],
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
) -> None:
    world_ops = [op for op in ops if op["op"] in ("lean", "head", "pelvis", "bounce")]
    limp = any("limp_hurt" in p for p in per_frame)
    lock = limp or any(op["op"] in ("lock_feet", "limp", "speed", "exaggerate", "smooth") for op in ops)
    if not world_ops and not lock:
        return
    fwd, right, _up = body_axes(arm, roles)
    inv = arm.matrix_world.inverted()
    hips = arm.pose.bones.get(roles.get("hips", ""))
    legs = []
    for side in "lr":
        names = [roles.get(f"{r}_{side}") for r in ("thigh", "calf", "foot")]
        if all(names):
            legs.append(tuple(arm.pose.bones[nm] for nm in names))  # type: ignore[index]
    n = len(per_frame)
    # pelvis heights of the (time-edited) motion, for bounce
    hz = []
    for f in range(n):
        scene.frame_set(f)
        hz.append(hips.head.z if hips else 0.0)
    mean_z = sum(hz) / max(1, len(hz))
    spine = [arm.pose.bones[roles[r]] for r in ("spine1", "spine2", "spine3") if r in roles]
    headb = [arm.pose.bones[roles[r]] for r in ("neck", "head") if r in roles]
    orig_z = {
        roles[f"foot_{sd}"]: [p.get(f"anklez_{sd}", -math.inf) for p in per_frame]
        for sd in "lr"
        if roles.get(f"foot_{sd}") and f"anklez_{sd}" in per_frame[0]
    }
    targets = (
        foot_targets(
            arm,
            legs,
            n,
            fps,
            cyclic,
            floor,
            roles,
            orig_z,
            scene,
            0.08 if any(op["op"] == "lock_feet" for op in ops) else None,
        )
        if lock
        else {}
    )
    side_of = {roles.get("foot_l"): "l", roles.get("foot_r"): "r"}
    inv3 = arm.matrix_world.to_3x3().inverted()

    def foot_rot(foot: bpy.types.PoseBone, f: int) -> Matrix:
        p, sd = per_frame[f], side_of.get(foot.name)
        if lock and sd and f"footq_{sd}_0" in p:
            q = Quaternion(mm.q_norm([p[f"footq_{sd}_{c}"] for c in range(4)]))
            return (inv3 @ q.to_matrix()).to_4x4()
        return foot.matrix.to_3x3().to_4x4()

    for f in range(n):
        scene.frame_set(f)
        plant = {
            foot.name: (targets[foot.name][f] if lock else foot.head.copy(), foot_rot(foot, f)) for _, _, foot in legs
        }
        moved_hips = lock
        for op in world_ops:
            k = op["op"]
            if k == "lean" and spine:
                deg = float(op.get("degrees", 0)) / len(spine)
                d = op.get("dir", "forward")
                axis, sign = {"forward": (right, -1), "back": (right, 1), "left": (fwd, -1), "right": (fwd, 1)}[d]
                for pb in spine:
                    rotate_about(pb, axis, sign * deg, arm, view_layer)
            elif k == "head" and headb:
                deg = float(op.get("degrees", 0)) / len(headb)
                for pb in headb:
                    rotate_about(pb, right, -deg, arm, view_layer)
            elif k == "pelvis" and hips:
                drop = float(op.get("drop", 0))
                hips.matrix = Matrix.Translation(inv.to_3x3() @ Vector((0, 0, -drop))) @ hips.matrix
                view_layer.update()
                moved_hips = True
            elif k == "bounce" and hips:
                fac = float(op.get("factor", 1))
                dz = (hz[f] - mean_z) * (fac - 1)
                hips.matrix = Matrix.Translation(Vector((0, 0, dz))) @ hips.matrix
                view_layer.update()
                moved_hips = True
        if limp and spine:
            p = per_frame[f]
            a, w = p.get("limp_amount", 0.0), p.get("limp_hurt", 0.0)
            toward = "left" if p.get("limp_side", 0.0) < 0.5 else "right"
            axis, sign = (fwd, -1) if toward == "left" else (fwd, 1)
            for pb in spine:
                rotate_about(pb, axis, sign * 9 * a * w / len(spine), arm, view_layer)
            if hips:  # the body dips onto the hurt leg and hurries off it
                hips.matrix = Matrix.Translation(Vector((0, 0, -0.025 * a * w))) @ hips.matrix
                view_layer.update()
                moved_hips = True
        if moved_hips:
            for thigh, calf, foot in legs:
                tgt, rot = plant[foot.name]
                two_bone_ik(arm, thigh, calf, foot, tgt, rot, view_layer)
        for pb in arm.pose.bones:
            pb.keyframe_insert("location", frame=f, group=pb.name)
            key_rotation(pb, f)


def fix_clip(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    roles: dict[str, str],
    fps: float,
    cyclic: bool,
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    root_motion: str | None = None,
    name: str | None = None,
    label: str | None = None,
) -> tuple[bpy.types.Action | None, dict]:
    """The standard fix on a COPY of the clip: feet re-planted (nudged at most 8 cm), the loop seam
    closed, pops smoothed (the clip's own too), root motion extracted or removed if asked. The clip is
    played on `scene`; bone edits are evaluated through `view_layer`. The original is never touched.
    Returns (new action, report); the new action is None (and deleted) if the fix made anything worse that
    the checks call a FAIL."""
    label = label or act.name
    before = sample(arm, act, roles, scene)
    report: dict = {"original": measure(before, fps, cyclic, arm, label)}
    if report["original"].get("travels"):
        cyclic = False  # a travelling loop keeps its seam: blending end into start would undo the travel
    if report["original"]["pops"]:  # smooth the clip's own pops first, on a scratch copy
        src = act.copy()
        try:
            set_action(arm, src)
            smooth_pops(arm, report["original"]["pops"], len(before.world), scene, clip_range(act)[0])
            before = sample(arm, src, roles, scene)
        finally:
            set_action(arm, act)
            bpy.data.actions.remove(src)
    ops = [{"op": "lock_feet"}] + ([{"op": "fix_loop", "frames": 4}] if cyclic else [])
    frames, per_frame, notes = apply_local_and_time(before, ops, roles, arm, fps, cyclic)
    new = write_action(arm, frames, name or f"{act.name}_fixed")
    floor = {}
    for side in "lr":
        fb = roles.get(f"foot_{side}")
        if fb and f"ankle_{side}" in before.world[0]:
            floor[fb] = min(w[f"ankle_{side}"][2] for w in before.world)
    world_pass(arm, new, ops, per_frame, roles, fps, cyclic, floor, scene, view_layer)
    if root_motion in ("extract", "in_place"):
        notes.append(root_motion_pass(arm, roles, len(frames), root_motion, scene, view_layer))
    report["result"] = measure(sample(arm, new, roles, scene), fps, cyclic, arm, label)
    for _ in range(3):  # smooth every pop left (the clip's own and any the fix made), measure again
        fresh = dict(report["result"]["pops"])
        if not fresh:
            break
        smooth_pops(arm, fresh, len(frames), scene)
        report["result"] = measure(sample(arm, new, roles, scene), fps, cyclic, arm, label)
    notes.append("feet re-planted" + (", loop seam closed" if cyclic else ""))
    report["changes"] = notes
    report["verdict"] = verdicts(report["original"], report["result"], fixing=True)
    was = verdicts(report["original"], None)
    if any(v.startswith("FAIL") and v not in was for v in report["verdict"]):
        report["verdict"].append("REFUSED the fix made this clip worse, so it was thrown away.")
        bpy.data.actions.remove(new)
        set_action(arm, act)
        return None, report
    new.use_fake_user = True
    return new, report
