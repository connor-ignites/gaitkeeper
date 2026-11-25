# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper skin checks: is the model rigged so it bends well and loads in a game engine?

Runs inside Blender. Lessons behind each check are in tools/motion/BODY.md (rigging, topology).
- weights: every vertex follows some bone; weights add up to 1 (auto-normalise)
- influences: game engines skin with 4 bones a vertex (Unity's default, Godot, Unreal's mobile)
- control bones: IK targets, poles and controls must not deform the mesh
- Preserve Volume: without it, joints pinch in Blender renders (engines skin linearly and ignore it,
  so for games the fix is topology and twist bones)
- bend test: each elbow and knee is bent 90 degrees and the skin around it is measured; if it
  shrinks a lot, the joint needs supporting edge loops (or Preserve Volume plus Corrective Smooth)
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import bpy
from mathutils import Quaternion, Vector

from .names import has_word
from .rig import body_axes

CONTROL_WORDS = ("ik", "pole", "target", "ctrl", "control", "mch", "helper")
MAX_INFLUENCES = 4
COLLAPSE_WARN = 0.25  # the skin round a bent joint shrinks by more than a quarter


def _meshes(arm: bpy.types.Object) -> list[bpy.types.Object]:
    out = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        if any(m.type == "ARMATURE" and m.object == arm for m in o.modifiers):
            out.append(o)
    return out


def _is_control(name: str) -> bool:
    """An IK target, pole or other control bone, by whole words of its name."""
    return has_word(name, CONTROL_WORDS)


def skin_report(arm: bpy.types.Object, roles: dict[str, str], view_layer: bpy.types.ViewLayer) -> dict:
    meshes = _meshes(arm)
    out: dict = {"meshes": [m.name for m in meshes]}
    if not meshes:
        return out
    bone_names = {b.name for b in arm.data.bones}
    deforming = {b.name for b in arm.data.bones if b.use_deform}
    unweighted = over = unnormal = total = 0
    worst_inf = 0
    control_deform = set()
    preserve = []
    for ob in meshes:
        gname = {g.index: g.name for g in ob.vertex_groups}
        for mod in ob.modifiers:
            if mod.type == "ARMATURE" and mod.object == arm:
                preserve.append(bool(mod.use_deform_preserve_volume))
        for v in ob.data.vertices:
            total += 1
            ws = [(gname.get(g.group, ""), g.weight) for g in v.groups]
            ws = [(n, w) for n, w in ws if n in bone_names and n in deforming and w > 0.001]
            s = sum(w for _, w in ws)
            if s < 0.01:
                unweighted += 1
                continue
            if abs(s - 1) > 0.05:
                unnormal += 1
            if len(ws) > MAX_INFLUENCES:
                over += 1
            worst_inf = max(worst_inf, len(ws))
            for n, w in ws:
                if w > 0.05 and _is_control(n):
                    control_deform.add(n)
    out.update(
        vertices=total,
        unweighted=unweighted,
        not_normalised=unnormal,
        over_4_bones=over,
        most_bones_on_a_vertex=worst_inf,
        control_bones_deforming=sorted(control_deform),
        preserve_volume=all(preserve) if preserve else None,
    )
    out["bend_test"] = bend_test(arm, roles, meshes, view_layer)
    return out


def _skin_near(
    meshes: list, upper: str, lower: str, centre: Vector, radius: float
) -> list[tuple[bpy.types.Object, int]]:
    picked = []
    for ob in meshes:
        groups = {g.name: g.index for g in ob.vertex_groups}
        ids = {groups[n] for n in (upper, lower) if n in groups}
        mw = ob.matrix_world
        for v in ob.data.vertices:
            if any(g.group in ids and g.weight > 0.1 for g in v.groups) and (mw @ v.co - centre).length < radius:
                picked.append((ob, v.index))
    return picked


def _evaluated_positions(meshes: list, view_layer: bpy.types.ViewLayer) -> dict:
    """Every mesh's deformed vertices in world space, read from the view layer (updated by the caller)."""
    dg = view_layer.depsgraph
    out = {}
    for ob in meshes:
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        out[ob.name] = [ev.matrix_world @ v.co for v in me.vertices]
        ev.to_mesh_clear()
    return out


TRANSFORMS = ("location", "rotation_quaternion", "rotation_euler", "rotation_axis_angle", "scale")


@contextmanager
def kept_pose(arm: bpy.types.Object) -> Iterator[None]:
    """Put the armature's clip (and its slot, Blender 4.4+) and every pose bone's rotation mode and
    transform back afterwards, even if what runs inside fails. A bone's rotation mode is shared by every
    clip (FBX bones are often Euler), so a changed mode would change how every clip plays."""
    ad = arm.animation_data
    action = ad.action if ad else None
    slot = getattr(ad, "action_slot", None) if ad else None
    modes = {pb.name: pb.rotation_mode for pb in arm.pose.bones}
    values = {pb.name: [tuple(getattr(pb, t)) for t in TRANSFORMS] for pb in arm.pose.bones}
    try:
        yield
    finally:
        for pb in arm.pose.bones:
            pb.rotation_mode = modes[pb.name]  # first: changing the mode converts the rotation values
            for t, value in zip(TRANSFORMS, values[pb.name]):
                setattr(pb, t, value)
        if ad is not None:
            ad.action = action
            if slot is not None:
                ad.action_slot = slot


def bend_test(arm: bpy.types.Object, roles: dict[str, str], meshes: list, view_layer: bpy.types.ViewLayer) -> dict:
    """Bend each elbow and knee 90 degrees the anatomical way, and measure how much the skin
    within reach of the joint pulls in towards it (the joint collapsing or pinching). The rig's clip,
    rotation modes and pose are put back afterwards, even on an error."""
    with kept_pose(arm):
        out = _bend_joints(arm, roles, meshes, view_layer)
    view_layer.update()
    return out


def _bend_joints(arm: bpy.types.Object, roles: dict[str, str], meshes: list, view_layer: bpy.types.ViewLayer) -> dict:
    """The bend test itself, from the rest pose; changes the clip, rotation modes and pose (bend_test
    puts them back)."""
    fwd, _, _ = body_axes(arm, roles)
    mw = arm.matrix_world
    if arm.animation_data:
        arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.location, pb.rotation_quaternion, pb.scale = (0, 0, 0), (1, 0, 0, 0), (1, 1, 1)
    view_layer.update()
    rest = _evaluated_positions(meshes, view_layer)
    out = {}
    for joint, up_role, low_role, sign in (
        ("knee_l", "thigh_l", "calf_l", -1),
        ("knee_r", "thigh_r", "calf_r", -1),
        ("elbow_l", "upperarm_l", "lowerarm_l", 1),
        ("elbow_r", "upperarm_r", "lowerarm_r", 1),
    ):
        up, low = roles.get(up_role), roles.get(low_role)
        if not up or not low:
            continue
        ub, lb = arm.data.bones[up], arm.data.bones[low]
        centre = mw @ lb.head_local
        radius = 0.35 * lb.length * mw.to_scale().x
        verts = _skin_near(meshes, up, low, centre, radius)
        if len(verts) < 8:
            continue
        # the bend axis in world space: knees fold the shin back, elbows fold the forearm forward
        u = (mw.to_3x3() @ (ub.tail_local - ub.head_local)).normalized()
        axis = u.cross(fwd * sign)
        if axis.length < 1e-6:
            continue
        local_axis = (mw.to_3x3() @ lb.matrix_local.to_3x3()).inverted() @ axis.normalized()
        pb = arm.pose.bones[low]
        pb.rotation_quaternion = Quaternion(local_axis, 1.5708)
        view_layer.update()
        bent = _evaluated_positions(meshes, view_layer)
        pb.rotation_quaternion = (1, 0, 0, 0)
        view_layer.update()
        before = sum((rest[o.name][i] - centre).length for o, i in verts) / len(verts)
        after = sum((bent[o.name][i] - centre).length for o, i in verts) / len(verts)
        out[joint] = {"vertices": len(verts), "shrink": round(1 - after / before, 3) if before > 0 else 0.0}
    return out


def skin_verdicts(r: dict, blend_file: bool = False) -> list[str]:
    if not r.get("meshes"):
        return ["WARN no skinned mesh found on this skeleton: only the bones were checked."]
    msgs = []
    if r["unweighted"]:
        msgs.append(f"FAIL {r['unweighted']} vertices follow no bone: they'll stay behind when the character moves.")
    if r["not_normalised"]:
        msgs.append(
            f"WARN {r['not_normalised']} vertices have weights that don't add up to 1: turn on Auto Normalize "
            "(weight paint options) and normalise all."
        )
    if r["over_4_bones"]:
        most = r["most_bones_on_a_vertex"]
        msgs.append(
            f"WARN {r['over_4_bones']} vertices follow more than 4 bones (up to {most}): "
            "game engines keep the 4 strongest, so those spots shift. Limit Total to 4 in Blender."
        )
    if r["control_bones_deforming"]:
        msgs.append(
            "FAIL control bones move the mesh: "
            + ", ".join(r["control_bones_deforming"][:5])
            + ". Turn Deform off on IK targets, poles and controls."
        )
    if blend_file and r.get("preserve_volume") is False:
        # game engines skin linearly and never see this setting, so only say it for Blender renders
        msgs.append(
            "WARN Preserve Volume is off on the Armature modifier: for renders in Blender, twisting joints "
            "will pinch (the candy-wrapper look). Turn it on, and add Corrective Smooth if elbows go round."
        )
    for joint, b in r.get("bend_test", {}).items():
        if b["shrink"] > COLLAPSE_WARN:
            msgs.append(
                f"WARN the {joint.replace('_l', ' (left)').replace('_r', ' (right)')} collapses when bent "
                f"90 degrees (the skin pulls in {b['shrink'] * 100:.0f}%): add supporting edge loops, closer "
                "together on the outside of the bend, or turn on Preserve Volume."
            )
    return msgs
