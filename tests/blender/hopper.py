# SPDX-License-Identifier: GPL-3.0-or-later
"""Hopper or walker, run inside Blender by tests/test_blender_hopper.py:

    blender -b --factory-startup --python tests/blender/hopper.py -- gaitkeeper-X.Y.Z.zip

Two legs and a tail: on Auto, a bird whose feet take turns is an animal, one whose feet move together is a
hopper, and the manual Hopper setting still wins. Prints one "HOP ..." line per step and exits 1 on the first
failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_rig


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"HOP {'ok  ' if ok else 'FAIL'} {name} {detail}".rstrip())
    if not ok:
        sys.exit(1)


def fresh_bird(clip: str, together: bool) -> None:
    """An empty scene holding one bird with one stepping clip."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)
    demo_rig.key_strides(demo_rig.build_bird(), clip, together)


def checked_as() -> str:
    """Run Check and return the kind the report names."""
    step("check", bpy.ops.gaitkeeper.check() == {"FINISHED"})
    first = bpy.data.texts["GaitKeeper report"].as_string().splitlines()[0]
    return first.split("(checked as: ")[-1].rstrip(")")


if __name__ == "__main__":
    zip_path = sys.argv[sys.argv.index("--") + 1]
    bpy.ops.extensions.package_install_files(filepath=zip_path, repo="user_default", enable_on_install=True)
    settings = bpy.context.scene.gaitkeeper
    fresh_bird("Walk", together=False)
    kind = checked_as()
    step("feet in turn: animal", kind == "animal", kind)
    settings.hopper = "YES"
    kind = checked_as()
    step("Hopper: Yes wins", kind == "hopper", kind)
    settings.hopper = "AUTO"
    fresh_bird("Hop", together=True)
    kind = checked_as()
    step("feet together: hopper", kind == "hopper", kind)
    print("HOP PASSED")
