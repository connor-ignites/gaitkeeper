# SPDX-License-Identifier: GPL-3.0-or-later
"""A tiny two-legged rig built from code, so the tests need no downloaded models.

Bones use the common Hips / LeftUpLeg / LeftArm naming. Two clips:
- Idle: stands still, breathing a little (should not FAIL);
- Walk_Glide: the body travels 1.5 m while both feet stay flat on the floor (the feet skate).
"""

from __future__ import annotations

import math

import bpy

# bone: (parent, head, tail); the rig faces -Y, metres
BONES: dict[str, tuple[str | None, tuple[float, float, float], tuple[float, float, float]]] = {
    "Hips": (None, (0, 0, 1.0), (0, 0, 1.1)),
    "Spine": ("Hips", (0, 0, 1.1), (0, 0, 1.25)),
    "Spine1": ("Spine", (0, 0, 1.25), (0, 0, 1.4)),
    "Spine2": ("Spine1", (0, 0, 1.4), (0, 0, 1.5)),
    "Neck": ("Spine2", (0, 0, 1.5), (0, 0, 1.6)),
    "Head": ("Neck", (0, 0, 1.6), (0, 0, 1.8)),
}
for side, x in (("Left", 0.1), ("Right", -0.1)):
    BONES |= {
        f"{side}UpLeg": ("Hips", (x, 0, 1.0), (x, -0.01, 0.55)),
        f"{side}Leg": (f"{side}UpLeg", (x, -0.01, 0.55), (x, 0.02, 0.1)),
        f"{side}Foot": (f"{side}Leg", (x, 0.02, 0.1), (x, -0.1, 0.03)),
        f"{side}ToeBase": (f"{side}Foot", (x, -0.1, 0.03), (x, -0.18, 0.03)),
        f"{side}Shoulder": ("Spine2", (x * 0.3, 0, 1.45), (x * 1.6, 0, 1.45)),
        f"{side}Arm": (f"{side}Shoulder", (x * 1.6, 0, 1.45), (x * 1.8, 0.01, 1.17)),
        f"{side}ForeArm": (f"{side}Arm", (x * 1.8, 0.01, 1.17), (x * 1.8, -0.01, 0.92)),
        f"{side}Hand": (f"{side}ForeArm", (x * 1.8, -0.01, 0.92), (x * 1.8, -0.01, 0.82)),
    }


def build_rig(name: str = "Person") -> bpy.types.Object:
    """Create the armature in the current scene and make it active."""
    arm = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for bone, (_, head, tail) in BONES.items():
        eb = arm.data.edit_bones.new(bone)
        eb.head, eb.tail = head, tail
    for bone, (parent, _, _) in BONES.items():
        if parent:
            arm.data.edit_bones[bone].parent = arm.data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for bone in ("Hips", "LeftUpLeg", "RightUpLeg"):  # FBX imports are often Euler: Fix must keep the mode
        arm.pose.bones[bone].rotation_mode = "XYZ"
    return arm


def key_other_object() -> bpy.types.Action:
    """A clip on another object, which Check must leave out."""
    empty = bpy.data.objects.new("Prop", None)
    bpy.context.scene.collection.objects.link(empty)
    for f in (1, 20):
        empty.location.x = f / 10
        empty.keyframe_insert("location", frame=f)
    empty.animation_data.action.name = "PropMove"
    return empty.animation_data.action


def new_clip(arm: bpy.types.Object, name: str, frames: int) -> bpy.types.Action:
    """An empty action, made current, with the scene range set to it."""
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data_create().action = act
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, frames
    return act


def key_idle(arm: bpy.types.Object, frames: int = 48) -> bpy.types.Action:
    """Standing still; the chest rises 5 mm with each breath."""
    act = new_clip(arm, "Idle", frames)
    chest = arm.pose.bones["Spine1"]
    for f in range(1, frames + 1, 4):
        chest.location = (0, 0.005 * math.sin(2 * math.pi * (f - 1) / (frames - 1)), 0)
        chest.keyframe_insert("location", frame=f)
    return act


def key_glide(arm: bpy.types.Object, frames: int = 40, distance: float = 1.5) -> bpy.types.Action:
    """The hips travel forward at a steady speed with no stepping: both planted feet slide with them."""
    act = new_clip(arm, "Walk_Glide", frames)
    hips = arm.pose.bones["Hips"]
    for f in (1, frames):
        # bone-local Y is world Z for an upright hips bone, so travel along -world Y is +local Z
        hips.location = (0, 0, distance * (f - 1) / (frames - 1))
        hips.keyframe_insert("location", frame=f)
    return act
