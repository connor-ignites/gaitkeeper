# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: the Fix button's edit of a person's clip, in Blender.

fix_clip samples the clip, closes its loop seam on the sampled local poses, keys the result as a new
action (write_action, also used by Pose Adapt), then re-plants the feet with two-bone IK
(replant_feet) so the fix never pushes a foot through the floor or skates it. Pops left over are
smoothed and the result is checked again; a fix that makes the clip worse is thrown away.
"""

from __future__ import annotations

import dataclasses

import bpy
from mathutils import Matrix, Quaternion

from . import motion_math
from .checks import measure, verdicts
from .fix import MAX_FOOT_NUDGE_M, FixContext, Leg, foot_targets, root_motion_pass, smooth_pops, two_bone_ik
from .fix_guard import REFUSED_WORSE, all_or_nothing
from .rig import Sample, clip_range, key_rotation, sample, set_action, set_rotation

LOOP_BLEND_FRAMES = 4  # a loop's last frames are blended into its first pose over this many frames
POP_PASSES = 3  # smoothing pops can leave new ones next to them: smooth and measure again up to this often


def close_loop_seam(frames: list[dict], blend: int) -> list[dict]:
    """The local poses with the first pose blended into the last `blend` frames, so the loop joins up."""
    first = frames[0]
    out = list(frames)
    for i, weight in enumerate(motion_math.loop_blend_weights(len(frames), blend)):
        if weight <= 0:
            continue
        pose = {}
        for name, (loc, q, scale) in frames[i].items():
            loc0, q0, _ = first[name]
            pose[name] = (
                tuple(x + (y - x) * weight for x, y in zip(loc, loc0)),
                motion_math.q_slerp(q, q0, weight),
                scale,
            )
        out[i] = pose
    return out


def write_action(arm: bpy.types.Object, frames: list[dict], name: str) -> bpy.types.Action:
    """Key every bone's local pose on every frame into a new action, made current."""
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


def leg_chains(arm: bpy.types.Object, roles: dict[str, str]) -> list[Leg]:
    """(thigh, calf, foot) pose bones of each leg whose three bones were all found."""
    legs = []
    for side in "lr":
        names = [roles.get(f"{r}_{side}") for r in ("thigh", "calf", "foot")]
        if all(names):
            legs.append(tuple(arm.pose.bones[nm] for nm in names))  # type: ignore[index]
    return legs


def ankle_heights(s: Sample, roles: dict[str, str]) -> dict[str, list[float]]:
    """Each foot bone's original ankle height on every frame."""
    return {
        roles[f"foot_{side}"]: [w[f"ankle_{side}"][2] for w in s.world]
        for side in "lr"
        if roles.get(f"foot_{side}") and f"ankle_{side}" in s.world[0]
    }


def foot_rotations(s: Sample, roles: dict[str, str]) -> dict[str, list[tuple]]:
    """Each foot bone's original world rotation on every frame (kept on one hemisphere), so a re-planted
    foot keeps its roll."""
    out = {}
    for side in "lr":
        name = roles.get(f"foot_{side}")
        if name:
            ref = s.world_q[0][name]
            out[name] = [motion_math.q_norm(motion_math.q_align(w[name], ref)) for w in s.world_q]
    return out


def replant_feet(ctx: FixContext, n: int, heights: dict[str, list[float]], rotations: dict[str, list[tuple]]) -> None:
    """Lock each planted foot in place (nudged at most MAX_FOOT_NUDGE_M) with two-bone IK, giving it back
    its original world rotation, and key the result on every frame."""
    arm = ctx.arm
    legs = leg_chains(arm, ctx.roles)
    targets = foot_targets(ctx, legs, n, heights, MAX_FOOT_NUDGE_M)
    to_armature = arm.matrix_world.to_3x3().inverted()

    def foot_matrix(foot: bpy.types.PoseBone, f: int) -> Matrix:
        if foot.name in rotations:
            return (to_armature @ Quaternion(rotations[foot.name][f]).to_matrix()).to_4x4()
        return foot.matrix.to_3x3().to_4x4()

    for f in range(n):
        ctx.scene.frame_set(f)
        plant = {foot.name: (targets[foot.name][f], foot_matrix(foot, f)) for _, _, foot in legs}
        for thigh, calf, foot in legs:
            target, rotation = plant[foot.name]
            two_bone_ik(arm, thigh, calf, foot, target, rotation, ctx.view_layer)
        for pb in arm.pose.bones:
            pb.keyframe_insert("location", frame=f, group=pb.name)
            key_rotation(pb, f)


def fix_clip(
    ctx: FixContext, act: bpy.types.Action, root_motion: str | None = None, label: str | None = None
) -> tuple[bpy.types.Action | None, dict]:
    """The standard fix on a COPY of the clip: feet re-planted (nudged at most MAX_FOOT_NUDGE_M), the loop
    seam closed, pops smoothed (the clip's own too), root motion extracted or removed if asked. The
    original is never touched. Returns (new action, report); the new action is None (and deleted) if the
    fix made anything worse that the checks call a FAIL. If anything fails midway, every action it made is
    removed and the original clip made current again before the error is raised."""
    with all_or_nothing(ctx.arm):
        label = label or act.name
        before = sample(ctx.arm, act, ctx.roles, ctx.scene)
        report: dict = {"original": measure(before, ctx.fps, ctx.cyclic, ctx.arm, label)}
        if report["original"].get("travels"):
            # a travelling loop keeps its seam: blending end into start would undo the travel
            ctx = dataclasses.replace(ctx, cyclic=False)
        if report["original"]["pops"]:
            before = _without_own_pops(ctx, act, report["original"]["pops"], len(before.world))
        new, notes = _fixed_copy(ctx, act, before, root_motion)
        report["result"] = _smoothed_result(ctx, new, len(before.world), label)
        notes.append("feet re-planted" + (", loop seam closed" if ctx.cyclic else ""))
        report["changes"] = notes
        report["verdict"] = verdicts(report["original"], report["result"], fixing=True)
        was = verdicts(report["original"], None)
        if any(v.startswith("FAIL") and v not in was for v in report["verdict"]):
            report["verdict"].append(REFUSED_WORSE)
            bpy.data.actions.remove(new)
            set_action(ctx.arm, act)
            return None, report
        new.use_fake_user = True
        return new, report


def _without_own_pops(ctx: FixContext, act: bpy.types.Action, pops: dict[str, list[int]], n: int) -> Sample:
    """The clip sampled after smoothing its own pops on a scratch copy; the clip itself is left as it was."""
    scratch = act.copy()
    try:
        set_action(ctx.arm, scratch)
        smooth_pops(ctx.arm, pops, n, ctx.scene, clip_range(act)[0])
        return sample(ctx.arm, scratch, ctx.roles, ctx.scene)
    finally:
        set_action(ctx.arm, act)
        bpy.data.actions.remove(scratch)


def _fixed_copy(
    ctx: FixContext, act: bpy.types.Action, before: Sample, root_motion: str | None
) -> tuple[bpy.types.Action, list[str]]:
    """The new action: loop seam closed, feet re-planted, root motion handled. Returns it and its notes."""
    frames = [dict(f) for f in before.basis]
    if ctx.cyclic:
        frames = close_loop_seam(frames, LOOP_BLEND_FRAMES)
    new = write_action(ctx.arm, frames, f"{act.name}_fixed")
    replant_feet(ctx, len(frames), ankle_heights(before, ctx.roles), foot_rotations(before, ctx.roles))
    notes = []
    if root_motion in ("extract", "in_place"):
        notes.append(root_motion_pass(ctx, len(frames), root_motion))
    return new, notes


def _smoothed_result(ctx: FixContext, new: bpy.types.Action, n: int, label: str) -> dict:
    """Smooth every pop left in `new` (the clip's own and any the fix made) and measure it again."""
    result = measure(sample(ctx.arm, new, ctx.roles, ctx.scene), ctx.fps, ctx.cyclic, ctx.arm, label)
    for _ in range(POP_PASSES):
        fresh = dict(result["pops"])
        if not fresh:
            break
        smooth_pops(ctx.arm, fresh, n, ctx.scene)
        result = measure(sample(ctx.arm, new, ctx.roles, ctx.scene), ctx.fps, ctx.cyclic, ctx.arm, label)
    return result
