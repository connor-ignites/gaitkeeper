# SPDX-License-Identifier: GPL-3.0-or-later
"""Odd rigs and clips, run inside Blender by tests/test_blender_edge_cases.py:

    blender -b --factory-startup --python tests/blender/edge_cases.py -- gaitkeeper-X.Y.Z.zip WORK_DIR

Each case builds a fresh scene, runs Check (and Fix where there is a clip) and prints one line:
"EDGE ok <case> <result>" when the add-on finished or refused with a message, "EDGE FAIL ..." when an operator
raised, reported an internal error, or left the scene changed. Exits 1 if any case failed.
"""

from __future__ import annotations

import math
import sys
import time
from collections.abc import Callable
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_rig

INTERNAL_ERROR = ("couldn't check", "couldn't fix", "Traceback")
failures: list[str] = []


def fresh_scene() -> None:
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)
    for text in list(bpy.data.texts):
        bpy.data.texts.remove(text)


def report_head() -> str:
    text = bpy.data.texts.get("GaitKeeper report")
    return " | ".join(text.as_string().splitlines()[:2]) if text else "(no report)"


def run_operator(name: str) -> str:
    """Run gaitkeeper.<name> on the active object; an exception or an internal error message is a failure."""
    op = getattr(bpy.ops.gaitkeeper, name)
    if not op.poll():
        return f"{name}: not offered"
    try:
        result = op()
    except RuntimeError as e:  # the operator reported an ERROR
        message = str(e).strip().splitlines()[-1]
        raise AssertionError(f"{name} error: {message}") from e
    return f"{name}: {sorted(result)[0]} ({report_head()[:110]})"


def case(name: str, build: Callable[[], bpy.types.Object], fix: bool = True) -> None:
    fresh_scene()
    started = time.perf_counter()
    try:
        arm = build()
        bpy.context.view_layer.objects.active = arm
        outcome = [run_operator("check")] + ([run_operator("fix")] if fix else [])
        line = f"EDGE ok   {name} [{time.perf_counter() - started:.1f}s] " + "; ".join(outcome)
        if any(word in line for word in INTERNAL_ERROR):
            raise AssertionError(line)
        print(line)
    except Exception as e:
        failures.append(name)
        print(f"EDGE FAIL {name}: {type(e).__name__}: {str(e)[:300]}")


# ---------- the cases ----------


def no_animation() -> bpy.types.Object:
    return demo_rig.build_rig()


def empty_action() -> bpy.types.Object:
    arm = demo_rig.build_rig()
    demo_rig.new_clip(arm, "Empty", 10)
    return arm


def one_frame_clip() -> bpy.types.Object:
    arm = demo_rig.build_rig()
    demo_rig.new_clip(arm, "Pose_Hold", 1)
    arm.pose.bones["Spine1"].keyframe_insert("location", frame=1)
    return arm


def two_frame_walk() -> bpy.types.Object:
    arm = demo_rig.build_rig()
    demo_rig.key_glide(arm, frames=2)
    return arm


def nla_only() -> bpy.types.Object:
    arm = demo_rig.build_rig()
    act = demo_rig.key_glide(arm)
    track = arm.animation_data.nla_tracks.new()
    track.strips.new(act.name, 1, act)
    arm.animation_data.action = None
    return arm


def shape_key_action_in_file() -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    cube.shape_key_add(name="Basis")
    smile = cube.shape_key_add(name="Smile")
    for f, v in ((1, 0.0), (10, 1.0)):
        smile.value = v
        smile.keyframe_insert("value", frame=f)
    arm = demo_rig.build_rig()
    demo_rig.key_glide(arm)
    return arm


def scaled_and_rotated() -> bpy.types.Object:
    arm = demo_rig.build_rig()
    demo_rig.key_glide(arm)
    arm.scale = (0.01, 0.01, 0.01)
    arm.rotation_euler = (math.radians(90), 0, math.radians(30))
    arm.location = (3, -2, 1)
    return arm


def non_english_bones() -> bpy.types.Object:
    arm = demo_rig.build_rig()
    names = {"Hips": "腰", "LeftUpLeg": "左足", "LeftLeg": "左ひざ", "RightUpLeg": "右足", "RightLeg": "右ひざ"}
    for old, new in names.items():
        arm.data.bones[old].name = new
    demo_rig.key_idle(arm)
    return arm


def huge_clip() -> bpy.types.Object:
    arm = demo_rig.build_rig()
    demo_rig.key_idle(arm, frames=1000)
    return arm


def no_bones() -> bpy.types.Object:
    arm = bpy.data.objects.new("Empty_Rig", bpy.data.armatures.new("Empty_Rig"))
    bpy.context.scene.collection.objects.link(arm)
    return arm


def library_override(work: Path) -> Callable[[], bpy.types.Object]:
    """The rig saved to a library file, linked into this one and overridden, as studios share characters."""

    def build() -> bpy.types.Object:
        arm = demo_rig.build_rig()
        demo_rig.key_glide(arm)
        coll = bpy.data.collections.new("Character")
        coll.objects.link(arm)
        library = work / "character_library.blend"
        bpy.data.libraries.write(str(library), {coll, arm, *bpy.data.actions}, fake_user=True)
        fresh_scene()
        bpy.data.collections.remove(coll)
        with bpy.data.libraries.load(str(library), link=True) as (_src, dst):
            dst.collections = ["Character"]
        linked = dst.collections[0]
        bpy.context.scene.collection.children.link(linked)
        override = linked.override_hierarchy_create(bpy.context.scene, bpy.context.view_layer)
        rig = next(o for o in override.all_objects if o.type == "ARMATURE")
        rig.animation_data_create().action = bpy.data.actions.get("Walk_Glide")
        return rig

    return build


if __name__ == "__main__":
    zip_path, work = sys.argv[sys.argv.index("--") + 1 :]
    bpy.ops.extensions.package_install_files(filepath=zip_path, repo="user_default", enable_on_install=True)
    case("no animation", no_animation, fix=False)
    case("empty action", empty_action)
    case("one-frame clip", one_frame_clip)
    case("two-frame clip", two_frame_walk)
    case("NLA strip only", nla_only, fix=False)
    case("shape-key action in file", shape_key_action_in_file)
    case("scaled and rotated rig", scaled_and_rotated)
    case("Japanese bone names", non_english_bones)
    case("1000-frame clip", huge_clip)
    case("armature with no bones", no_bones, fix=False)
    case("linked rig with library override", library_override(Path(work)))
    print("EDGE PASSED" if not failures else f"EDGE FAILED: {', '.join(failures)}")
    sys.exit(1 if failures else 0)
