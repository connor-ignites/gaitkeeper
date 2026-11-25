# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression checks, run inside Blender by tests/test_blender_regressions.py:

    blender -b --factory-startup --python tests/blender/regressions.py -- gaitkeeper-X.Y.Z.zip

- clip names are read by whole words: a skating "Soldier_Walk" or "Troll_Run" is still judged as a walk or run;
- bone names too: hind legs named RearLeg_L ("ear" inside) are found;
- the bend test puts rotation modes, pose and clip back even when it fails midway;
- Fix is all or nothing: failing midway leaves no new action and the original clip current;
- one loop rule for people and animals: a clip ending in its first pose loops, one ending elsewhere doesn't.
Prints one "REGRESSION ..." line per step and exits 1 on the first failure.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_rig

PACKAGE = "bl_ext.user_default.gaitkeeper"


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"REGRESSION {'ok  ' if ok else 'FAIL'} {name} {detail}".rstrip())
    if not ok:
        sys.exit(1)


def module(name: str):
    return importlib.import_module(f"{PACKAGE}.{name}")


def fresh_scene() -> None:
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)


def scene_and_layer() -> tuple[bpy.types.Scene, bpy.types.ViewLayer]:
    return bpy.context.scene, bpy.context.view_layer


def glide(arm: bpy.types.Object, name: str) -> bpy.types.Action:
    """The demo rig's skating glide, renamed."""
    act = demo_rig.key_glide(arm)
    act.name = name
    return act


def clip_words_are_whole_words() -> None:
    fresh_scene()
    arm = demo_rig.build_rig()
    names = ("Soldier_Walk", "Troll_Run")
    for name in names:
        glide(arm, name)
    bpy.context.scene.gaitkeeper.current_only = False
    result = module("runner").run_check(arm, *scene_and_layer())
    for name in names:
        lines = result["clips"].get(name, [])
        step(f"{name} judged for skating", any("skating" in line for line in lines), " | ".join(lines)[:200])


def rear_legs_are_found() -> None:
    fresh_scene()
    legs = module("core.creature").find_legs(demo_rig.build_quadruped())
    step("four legs", sorted(legs) == ["fore_l", "fore_r", "hind_l", "hind_r"], str(sorted(legs)))
    step("hind leg is the rear leg", legs.get("hind_l", [""])[-1] == "RearFoot_L", str(legs.get("hind_l")))


def failing(owner: object, attr: str, on_call: int = 1) -> Callable[[], None]:
    """Make owner.attr raise on its on_call-th call (earlier calls run as normal); returns the undo."""
    original = getattr(owner, attr)
    calls = []

    def boom(*args, **kwargs):
        calls.append(1)
        if len(calls) >= on_call:
            raise RuntimeError("forced failure")
        return original(*args, **kwargs)

    setattr(owner, attr, boom)
    return lambda: setattr(owner, attr, original)


def raises(call: Callable[[], object]) -> bool:
    try:
        call()
    except RuntimeError:
        return True
    return False


def bend_test_puts_everything_back() -> None:
    fresh_scene()
    arm = demo_rig.build_rig()
    act = glide(arm, "Walk_Glide")
    spine = arm.pose.bones["Spine"]
    spine.location = (0, 0.01, 0)
    skin = module("core.skin")
    roles = module("core.rig").role_map(arm)
    undo = failing(skin, "_evaluated_positions")
    try:
        failed = raises(lambda: skin.bend_test(arm, roles, [], bpy.context.view_layer))
    finally:
        undo()
    modes = {pb.name: pb.rotation_mode for pb in arm.pose.bones if pb.rotation_mode != "QUATERNION"}
    step("bend test failed", failed)
    step("rotation modes kept", sorted(modes) == ["Hips", "LeftUpLeg", "RightUpLeg"], str(modes))
    step("pose kept", tuple(round(v, 6) for v in spine.location) == (0, 0.01, 0), str(tuple(spine.location)))
    step("clip kept", arm.animation_data.action == act)


def fix_leaves_no_trace(name: str, arm: bpy.types.Object, act: bpy.types.Action, undo: Callable[[], None]) -> None:
    """Run Fix with a forced failure inside (undo takes it away): nothing may be left behind."""
    before = set(bpy.data.actions)
    try:
        failed = raises(lambda: module("runner").fix_current_clip(arm, *scene_and_layer()))
    finally:
        undo()
    step(f"{name}: fix failed", failed)
    step(f"{name}: no new action", set(bpy.data.actions) == before, str([a.name for a in bpy.data.actions]))
    step(f"{name}: original current", arm.animation_data.action == act, str(arm.animation_data.action))


def person_fix_is_all_or_nothing() -> None:
    fresh_scene()
    arm = demo_rig.build_rig()
    act = glide(arm, "Walk_Glide")
    fix_leaves_no_trace("person", arm, act, failing(module("core.edit"), "replant_feet"))


def animal_fix_is_all_or_nothing() -> None:
    fresh_scene()
    arm = demo_rig.build_bird()
    act = demo_rig.key_strides(arm, "Walk", together=False)
    creature_fix = module("core.creature_fix")
    bow_warn = dict(creature_fix.leg_checks.BOW_WARN)
    creature_fix.leg_checks.BOW_WARN.update(hind=-1.0, fore=-1.0)  # every leg counts as bowed, so the copy is made
    undo_measure = failing(creature_fix.creature, "measure_clip", on_call=2)  # then judging the copy fails

    def undo() -> None:
        undo_measure()
        creature_fix.leg_checks.BOW_WARN.clear()
        creature_fix.leg_checks.BOW_WARN.update(bow_warn)

    fix_leaves_no_trace("animal", arm, act, undo)


def one_loop_rule() -> None:
    fresh_scene()
    checks = module("core.checks")
    scene = bpy.context.scene
    bird = demo_rig.build_bird()
    walk = demo_rig.key_strides(bird, "Walk", together=False)
    start = demo_rig.new_clip(bird, "Walk_Start", 20)
    for frame, deg in ((1, 0), (20, 30)):
        demo_rig.turn_x(bird.pose.bones["thigh_L"], deg, frame)
    step("animal walk loops", checks.clip_loops(bird, walk, scene, walk.name))
    step("animal walk start doesn't", not checks.clip_loops(bird, start, scene, start.name))
    person = demo_rig.build_rig()
    idle = demo_rig.key_idle(person)
    rise = demo_rig.new_clip(person, "Crouch_Rise", 24)
    for frame, deg in ((1, 60), (24, 0)):
        demo_rig.turn_x(person.pose.bones["LeftLeg"], deg, frame)
    step("person idle loops", checks.clip_loops(person, idle, scene, idle.name))
    step("person rise doesn't", not checks.clip_loops(person, rise, scene, rise.name))


if __name__ == "__main__":
    zip_path = sys.argv[sys.argv.index("--") + 1]
    bpy.ops.extensions.package_install_files(filepath=zip_path, repo="user_default", enable_on_install=True)
    clip_words_are_whole_words()
    rear_legs_are_found()
    bend_test_puts_everything_back()
    person_fix_is_all_or_nothing()
    animal_fix_is_all_or_nothing()
    one_loop_rule()
    print("REGRESSION PASSED")
