# SPDX-License-Identifier: GPL-3.0-or-later
"""Pins Pose Adapt's output, run inside Blender by tests/test_blender_adapt.py:

    blender -b --factory-startup --python tests/blender/adapt_pin.py -- path/to/gaitkeeper-X.Y.Z.zip out.json

Installs the zip, keys a stepping walk loop on the code-made rig, then runs Adapt for each spread mode with
mirror on and off, with and without a kept pose on a second frame, feet planted on. Writes one fingerprint
per run to out.json: the report text, and for each bone a summary of every F-curve (see curve_summary).
"""

from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_rig

FRAMES = 32  # one stride; frame 33 repeats frame 1 so the loop joins
EDIT_FRAME, KEPT_FRAME = 9, 21


def key_rot_x(pb: bpy.types.PoseBone, deg: float, frame: int) -> None:
    """Rotate the bone about its own X axis and key it in the bone's rotation mode."""
    if pb.rotation_mode == "QUATERNION":
        pb.rotation_quaternion = (math.cos(math.radians(deg) / 2), math.sin(math.radians(deg) / 2), 0, 0)
        pb.keyframe_insert("rotation_quaternion", frame=frame)
    else:
        pb.rotation_euler = (math.radians(deg), 0, 0)
        pb.keyframe_insert("rotation_euler", frame=frame)


def key_walk(arm: bpy.types.Object) -> bpy.types.Action:
    """An in-place walk: the thighs swing in turn, the swinging knee bends (lifting that foot), the hips bob."""
    act = demo_rig.new_clip(arm, "Walk_Loop", FRAMES + 1)
    pb = arm.pose.bones
    for bone in pb:  # every bone keyed, so a hand-posed bone differs from the clip's own pose
        for f in (1, FRAMES + 1):
            key_rot_x(bone, 0, f)
    for f in range(1, FRAMES + 2):
        p = 2 * math.pi * (f - 1) / FRAMES
        for side, sign in (("Left", 1), ("Right", -1)):
            s = sign * math.sin(p)
            key_rot_x(pb[f"{side}UpLeg"], 25 * s, f)
            key_rot_x(pb[f"{side}Leg"], 45 * max(0.0, sign * math.cos(p)), f)
            key_rot_x(pb[f"{side}Foot"], -10 * s, f)
        pb["Hips"].location = (0, 0.02 * math.cos(2 * p), 0)
        pb["Hips"].keyframe_insert("location", frame=f)
    return act


def curve_summary(fc: bpy.types.FCurve) -> list:
    """[path, index, key count, first, last, min, max, mean] of one curve's key values. Small enough to keep in
    the golden file, and compared with a tolerance, since IK results differ in the last digits across platforms."""
    values = [k.co[1] for k in fc.keyframe_points] or [0.0]
    stats = (values[0], values[-1], min(values), max(values), sum(values) / len(values))
    return [fc.data_path, fc.array_index, len(fc.keyframe_points), *(round(v, 5) for v in stats)]


def fingerprint(act: bpy.types.Action) -> dict[str, list]:
    """Per bone (the data path before its property): the summaries of its curves."""
    action_fcurves = importlib.import_module("bl_ext.user_default.gaitkeeper.core.rig").action_fcurves
    curves: dict[str, list] = {}
    for fc in action_fcurves(act):
        curves.setdefault(fc.data_path.rsplit(".", 1)[0], []).append(curve_summary(fc))
    return {owner: sorted(c) for owner, c in sorted(curves.items())}


def report_text() -> str:
    block = bpy.data.texts.get("GaitKeeper report")
    return block.as_string() if block else ""


def reset(arm: bpy.types.Object, walk: bpy.types.Action, frame: int) -> None:
    """Clear any hand posing, put the walk back on and go to `frame`."""
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    arm.animation_data.action = walk
    bpy.context.scene.frame_set(frame)


def pose(arm: bpy.types.Object, bone: str, deg: float) -> None:
    """Turn a bone about its own X axis on top of the clip's pose, without keying it."""
    pb = arm.pose.bones[bone]
    pb.matrix_basis = pb.matrix_basis @ Matrix.Rotation(math.radians(deg), 4, "X")


def run(arm: bpy.types.Object, walk: bpy.types.Action, mode: str, mirror: bool, kept: bool, edit: tuple) -> dict:
    settings = bpy.context.scene.gaitkeeper
    settings.adapt_mode, settings.adapt_mirror, settings.adapt_feet, settings.adapt_fade = mode, mirror, True, 6
    settings.adapt_kept = ""
    if kept:
        reset(arm, walk, KEPT_FRAME)
        pose(arm, "LeftArm", 30)
        assert bpy.ops.gaitkeeper.adapt_keep() == {"FINISHED"}
    reset(arm, walk, EDIT_FRAME)
    for bone, deg in edit:
        pose(arm, bone, deg)
    if "GaitKeeper report" in bpy.data.texts:  # a refused run must not show the last run's report
        bpy.data.texts["GaitKeeper report"].clear()
    result = bpy.ops.gaitkeeper.adapt()
    new = arm.animation_data.action
    rec = {"result": sorted(result), "action": new.name, "report": report_text()}
    if new is not walk:
        rec["fcurves"] = fingerprint(new)
        bpy.data.actions.remove(new)
    return rec


EDITS = {"spine": (("Spine1", 10),), "leg": (("LeftUpLeg", 15), ("Spine1", 5)), "foot": (("LeftFoot", 20),)}


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :]
    bpy.ops.extensions.package_install_files(filepath=argv[0], repo="user_default", enable_on_install=True)
    arm = demo_rig.build_rig()
    walk = key_walk(arm)
    bpy.context.view_layer.objects.active = arm
    runs = {}
    for mode in ("WHOLE", "STEPS", "HERE"):
        for mirror in (True, False):
            for kept in (False, True):
                for edit_name, edit in EDITS.items():
                    key = f"{mode}-mirror{int(mirror)}-kept{int(kept)}-{edit_name}"
                    runs[key] = run(arm, walk, mode, mirror, kept, edit)
    Path(argv[1]).write_text(json.dumps(runs, indent=1, sort_keys=True), encoding="utf-8")
    made = sum("fcurves" in r for r in runs.values())
    print(f"PIN {len(runs)} runs, {made} made a copy, wrote {argv[1]}")


if __name__ == "__main__":
    main()
