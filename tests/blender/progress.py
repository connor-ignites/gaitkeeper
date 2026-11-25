# SPDX-License-Identifier: GPL-3.0-or-later
"""Progress for long checks, run inside Blender by tests/test_blender_progress.py:

    blender -b --factory-startup --python tests/blender/progress.py -- gaitkeeper-X.Y.Z.zip

Check tells its progress callback once per clip, in order, with the right totals (a person and an animal),
Fix tells it once for its one clip, and the operators still run headless (no window, so no progress shown).
Prints one "PROGRESS ..." line per step and exits 1 on the first failure.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_rig


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"PROGRESS {'ok  ' if ok else 'FAIL'} {name} {detail}".rstrip())
    if not ok:
        sys.exit(1)


def fresh_scene() -> None:
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)


def expected(clips: list[str]) -> list[tuple[int, int, str]]:
    """One call per clip as it starts: (clips done, clips in all, its name)."""
    return [(done, len(clips), name) for done, name in enumerate(clips)]


def check_calls(runner, arm: bpy.types.Object) -> tuple[list[tuple[int, int, str]], list[str]]:
    """(the calls Check made, the clips it checked)."""
    calls: list[tuple[int, int, str]] = []
    result = runner.run_check(arm, bpy.context.scene, bpy.context.view_layer, lambda *call: calls.append(call))
    return calls, list(result["clips"])


def person(runner) -> None:
    fresh_scene()
    arm = demo_rig.build_rig()
    demo_rig.key_idle(arm)
    demo_rig.key_crouch(arm)
    demo_rig.key_glide(arm)
    calls, clips = check_calls(runner, arm)
    step("person: once per clip", len(clips) == 3 and calls == expected(clips), str(calls))
    fix_calls: list[tuple[int, int, str]] = []
    current = arm.animation_data.action.name
    runner.fix_current_clip(arm, bpy.context.scene, bpy.context.view_layer, lambda *call: fix_calls.append(call))
    step("fix: once", fix_calls == [(0, 1, current)], str(fix_calls))


def animal(runner) -> None:
    fresh_scene()
    arm = demo_rig.build_bird()
    demo_rig.key_strides(arm, "Walk", together=False)
    demo_rig.key_strides(arm, "Run", together=False, frames=17)
    calls, clips = check_calls(runner, arm)
    step("animal: once per clip", len(clips) == 2 and calls == expected(clips), str(calls))


def headless_operators(operators) -> None:
    fresh_scene()
    demo_rig.key_glide(demo_rig.build_rig())
    with operators.shown_progress(bpy.context, "checking") as progress:
        step("headless: nothing shown", bpy.app.background and progress is None)
    step("check headless", bpy.ops.gaitkeeper.check() == {"FINISHED"})
    step("fix headless", bpy.ops.gaitkeeper.fix() == {"FINISHED"})


if __name__ == "__main__":
    zip_path = sys.argv[sys.argv.index("--") + 1]
    bpy.ops.extensions.package_install_files(filepath=zip_path, repo="user_default", enable_on_install=True)
    runner = importlib.import_module("bl_ext.user_default.gaitkeeper.runner")
    person(runner)
    animal(runner)
    headless_operators(importlib.import_module("bl_ext.user_default.gaitkeeper.operators"))
    print("PROGRESS PASSED")
