# SPDX-License-Identifier: GPL-3.0-or-later
"""A Unity-style rig (a Root bone holding a -90 degree turn and a 100x scale), run inside Blender by
tests/test_blender_held_root.py:

    blender -b --factory-startup --python tests/blender/held_root.py -- gaitkeeper-X.Y.Z.zip

Check must read the body as it stands in the clips, not as its rest pose lies: no swapped legs, no knees bent
backwards in the crouch, no units warning, the gliding walk still flagged, and the scene left exactly as it was.
An animal exported in centimetres (100 times too big on screen) must measure exactly as the same animal in metres.
Prints one "HELD ..." line per step and exits 1 on the first failure.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_rig


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"HELD {'ok  ' if ok else 'FAIL'} {name} {detail}".rstrip())
    if not ok:
        sys.exit(1)


def rounded(matrix) -> tuple:
    return tuple(round(v, 6) for row in matrix for v in row)


def rig_print(arm: bpy.types.Object) -> dict:
    """The rest pose, every bone's pose and the object's place, as numbers."""
    bpy.context.view_layer.update()
    rest = {b.name: (rounded(b.matrix_local), tuple(b.head_local), tuple(b.tail_local)) for b in arm.data.bones}
    pose = {pb.name: (rounded(pb.matrix_basis), rounded(pb.matrix)) for pb in arm.pose.bones}
    return {"rest": rest, "pose": pose, "object": rounded(arm.matrix_world), "frame": bpy.context.scene.frame_current}


def build() -> bpy.types.Object:
    """The Unity-style rig with an idle, a crouch (bent knees) and a gliding walk, each holding the Root bone."""
    arm = demo_rig.build_unity_rig()
    for act in (
        demo_rig.key_idle(arm, unit=demo_rig.UNITY_UNIT),
        demo_rig.key_crouch(arm),
        demo_rig.key_glide(arm, distance=1.5 * demo_rig.UNITY_UNIT),
    ):
        arm.animation_data.action = act
        demo_rig.hold_root(arm, act)
        if act.name != "Crouch_Idle":
            demo_rig.key_knees(arm, act, 0)
    bpy.context.view_layer.objects.active = arm
    return arm


def bird_walk(build: Callable[[], bpy.types.Object]) -> tuple[dict, list[str]]:
    """A fresh bird walking with its feet in turn: the animal checks' (measures, report lines) for the walk."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)
    arm = build()
    walk = demo_rig.key_strides(arm, "Walk", together=False)
    if "Root" in arm.pose.bones:
        demo_rig.hold_root(arm, walk)
    step(f"check {arm.name}", bpy.ops.gaitkeeper.check() == {"FINISHED"})
    package = "bl_ext.user_default.gaitkeeper"
    runner = importlib.import_module(f"{package}.runner")
    creature = importlib.import_module(f"{package}.core.creature")
    scene, view_layer = bpy.context.scene, bpy.context.view_layer
    animal = runner.animal_rig(arm, scene, view_layer)
    return creature.measure_clip(arm, walk, animal.legs, animal.pelvis, animal.hopper, animal.rest_widths, scene)


if __name__ == "__main__":
    zip_path = sys.argv[sys.argv.index("--") + 1]
    bpy.ops.extensions.package_install_files(filepath=zip_path, repo="user_default", enable_on_install=True)
    arm = build()
    before = rig_print(arm)
    step("check", bpy.ops.gaitkeeper.check() == {"FINISHED"})
    report = bpy.data.texts["GaitKeeper report"].as_string()
    lines = report.splitlines()
    step("kind", "(checked as: person)" in lines[0], lines[0])
    step("no swapped legs", "swapped" not in report)
    step("no backward knees", "bends backwards" not in report)
    step("no units warning", "units problem" not in report)
    glide = next(line for line in lines if line.endswith("  Walk_Glide"))
    step("glide flagged", not glide.startswith("PASS") and "skating" in report, glide)
    idle = next(line for line in lines if line.endswith("  Idle"))
    step("idle not failed", not idle.startswith("FAIL"), idle)
    step("scene unchanged", rig_print(arm) == before)
    in_metres, in_centimetres = bird_walk(demo_rig.build_bird), bird_walk(demo_rig.build_centimetre_bird)
    step("animal read in metres", in_centimetres == in_metres, f"{in_metres[0]} vs {in_centimetres[0]}")
    print("HELD PASSED")
