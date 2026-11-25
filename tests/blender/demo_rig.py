# SPDX-License-Identifier: GPL-3.0-or-later
"""A tiny two-legged rig built from code, so the tests need no downloaded models.

Bones use the common Hips / LeftUpLeg / LeftArm naming. Clips:
- Idle: stands still, breathing a little (should not FAIL);
- Walk_Glide: the body travels 1.5 m while both feet stay flat on the floor (the feet skate);
- Crouch_Idle: holding a crouch, knees bent forward.

build_unity_rig makes the same body the way Unity exports reach Blender (Kevin Iglesias packs): a Root bone
above the hips holds a -90 degree X turn and a 100x scale on every frame, so the rest pose lies flat at a
hundredth of the size (face down) while every frame stands up at normal size. Key its clips with UNITY_UNIT,
then hold_root.

build_bird makes a two-legged animal with a tail; key_strides swings its legs in turn (an emu) or together
(a kangaroo). build_centimetre_bird makes the same bird the way a Unity export in centimetres arrives.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import bpy
from mathutils import Quaternion

Point = tuple[float, float, float]
UNITY_SCALE = 100.0  # the Root bone's held scale
UNITY_UNIT = 1 / UNITY_SCALE  # rest units per metre on the Unity-style rig

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

# a two-legged animal with a tail (an emu or a kangaroo), facing -Y, metres
BIRD_BONES: dict[str, tuple[str | None, Point, Point]] = {
    "Pelvis": (None, (0, 0, 0.9), (0, -0.1, 0.95)),
    "Neck": ("Pelvis", (0, -0.1, 0.95), (0, -0.3, 1.5)),
    "Head": ("Neck", (0, -0.3, 1.5), (0, -0.45, 1.55)),
    "Tail": ("Pelvis", (0, 0, 0.9), (0, 0.4, 0.85)),
}
for sfx, x in (("L", 0.15), ("R", -0.15)):
    BIRD_BONES |= {
        f"thigh_{sfx}": ("Pelvis", (x, 0, 0.9), (x, -0.1, 0.6)),
        f"shin_{sfx}": (f"thigh_{sfx}", (x, -0.1, 0.6), (x, 0.05, 0.15)),
        f"foot_{sfx}": (f"shin_{sfx}", (x, 0.05, 0.15), (x, 0.0, 0.02)),
        f"toe_{sfx}": (f"foot_{sfx}", (x, 0.0, 0.02), (x, -0.12, 0.0)),
    }


def same_point(p: Point) -> Point:
    return p


def unity_point(p: Point) -> Point:
    """A body point as the Unity-style rig rests it: at a hundredth of the size."""
    return (p[0] * UNITY_UNIT, p[1] * UNITY_UNIT, p[2] * UNITY_UNIT)


def centimetre_point(p: Point) -> Point:
    """A body point in centimetres, as a Unity export in centimetres rests it."""
    return (p[0] * UNITY_SCALE, p[1] * UNITY_SCALE, p[2] * UNITY_SCALE)


def make_armature(
    name: str, bones: dict, place: Callable[[Point], Point] = same_point, root: str | None = None
) -> bpy.types.Object:
    """Create an armature of bones (bone: (parent, head, tail)) in the current scene and make it active. place
    moves every bone point; root adds a bone at the origin, pointing up, as the parent of the top bones."""
    arm = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for bone, (_, head, tail) in bones.items():
        eb = arm.data.edit_bones.new(bone)
        eb.head, eb.tail = place(head), place(tail)
    top = arm.data.edit_bones.new(root) if root else None
    if top is not None:
        top.head, top.tail = (0, 0, 0), place((0, 0, 0.1))
    for bone, (parent, _, _) in bones.items():
        arm.data.edit_bones[bone].parent = arm.data.edit_bones[parent] if parent else top
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def build_rig(
    name: str = "Person", place: Callable[[Point], Point] = same_point, root: str | None = None
) -> bpy.types.Object:
    """The two-legged person (BONES), made active. place and root as for make_armature."""
    arm = make_armature(name, BONES, place, root)
    for bone in ("Hips", "LeftUpLeg", "RightUpLeg"):  # FBX imports are often Euler: Fix must keep the mode
        arm.pose.bones[bone].rotation_mode = "XYZ"
    return arm


def build_bird(name: str = "Bird") -> bpy.types.Object:
    """A two-legged animal with a tail (BIRD_BONES), made active."""
    return make_armature(name, BIRD_BONES)


def key_strides(arm: bpy.types.Object, name: str, together: bool, frames: int = 25) -> bpy.types.Action:
    """A loop of the thighs swinging 25 degrees each way: in turn (a walking bird) or together (a hop)."""
    act = new_clip(arm, name, frames)
    for f in range(1, frames + 1, 2):
        phase = 2 * math.pi * (f - 1) / (frames - 1)
        turn_x(arm.pose.bones["thigh_L"], 25 * math.sin(phase), f)
        turn_x(arm.pose.bones["thigh_R"], 25 * math.sin(phase if together else phase + math.pi), f)
    return act


def build_unity_rig(name: str = "UnityPerson") -> bpy.types.Object:
    """The body as Blender imports a Unity export: the object turned +90 degrees about X, and a Root bone that
    hold_root turns back -90 and scales 100 times in every clip."""
    arm = build_rig(name, unity_point, root="Root")
    arm.rotation_euler = (math.radians(90), 0, 0)
    arm.pose.bones["Root"].rotation_mode = "QUATERNION"
    return arm


def build_centimetre_bird(name: str = "CentimetreBird") -> bpy.types.Object:
    """The bird as a Unity export in centimetres reaches Blender: bones in centimetres, the object at 0.01 and
    turned +90 degrees about X, and a Root bone that hold_root turns back and scales 100 times. Every frame then
    stands the body up 100 times too big on screen (centimetres), which the checks read back in metres."""
    arm = make_armature(name, BIRD_BONES, centimetre_point, root="Root")
    arm.rotation_euler = (math.radians(90), 0, 0)
    arm.scale = (UNITY_UNIT,) * 3
    arm.pose.bones["Root"].rotation_mode = "QUATERNION"
    return arm


def hold_root(arm: bpy.types.Object, act: bpy.types.Action) -> None:
    """Key the Root bone's held pose on every frame of the clip (it must be the armature's current clip)."""
    root = arm.pose.bones["Root"]
    root.rotation_quaternion = Quaternion((1, 0, 0), math.radians(-90))
    root.scale = (UNITY_SCALE,) * 3
    first, last = (round(f) for f in act.frame_range)
    for f in range(first, last + 1):
        root.keyframe_insert("rotation_quaternion", frame=f)
        root.keyframe_insert("scale", frame=f)


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


def key_idle(arm: bpy.types.Object, frames: int = 48, unit: float = 1.0) -> bpy.types.Action:
    """Standing still; the chest rises 5 mm with each breath. unit: the rig's rest units per metre."""
    act = new_clip(arm, "Idle", frames)
    chest = arm.pose.bones["Spine1"]
    for f in range(1, frames + 1, 4):
        chest.location = (0, unit * 0.005 * math.sin(2 * math.pi * (f - 1) / (frames - 1)), 0)
        chest.keyframe_insert("location", frame=f)
    return act


def turn_x(pb: bpy.types.PoseBone, deg: float, frame: int) -> None:
    """Key the bone turned deg about its own X axis, in whatever rotation mode it uses."""
    q = Quaternion((1, 0, 0), math.radians(deg))
    if pb.rotation_mode == "QUATERNION":
        pb.rotation_quaternion = q
        pb.keyframe_insert("rotation_quaternion", frame=frame)
    else:
        pb.rotation_euler = q.to_euler(pb.rotation_mode)
        pb.keyframe_insert("rotation_euler", frame=frame)


def key_knees(arm: bpy.types.Object, act: bpy.types.Action, knee_deg: float) -> None:
    """Key both legs through the current clip with the knees bent forward knee_deg (0: straight), the thighs
    swung forward half that. Every clip on a rig keys this once any does: unkeyed bones keep the last clip's pose."""
    first, last = (round(f) for f in act.frame_range)
    for side in ("Left", "Right"):
        for f in (first, last):
            turn_x(arm.pose.bones[f"{side}UpLeg"], -knee_deg / 2, f)  # a leg bone's +X turn swings it back
            turn_x(arm.pose.bones[f"{side}Leg"], knee_deg, f)


def key_crouch(arm: bpy.types.Object, frames: int = 24, knee_deg: float = 60) -> bpy.types.Action:
    """Holding a crouch: knees bent forward knee_deg (a real knee's way)."""
    act = new_clip(arm, "Crouch_Idle", frames)
    key_knees(arm, act, knee_deg)
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
