# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless smoke test, run inside Blender by tests/test_blender_smoke.py:

    blender -b --factory-startup --python tests/blender/smoke.py -- path/to/gaitkeeper-X.Y.Z.zip

Installs the zip into the (temporary) user repository, builds the code-made rig, runs Check clips and reads
the report back. Prints one "SMOKE ..." line per step and exits 1 on the first failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_rig

MODULE = "bl_ext.user_default.gaitkeeper"


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"SMOKE {'ok  ' if ok else 'FAIL'} {name} {detail}".rstrip())
    if not ok:
        sys.exit(1)


def install(zip_path: str) -> None:
    bpy.ops.extensions.package_install_files(filepath=zip_path, repo="user_default", enable_on_install=True)
    step("install", hasattr(bpy.types.Scene, "gaitkeeper"), zip_path)
    step("operators", hasattr(bpy.ops.gaitkeeper, "check") and hasattr(bpy.ops.gaitkeeper, "fix"))


def check_clips() -> str:
    arm = demo_rig.build_rig()
    demo_rig.key_idle(arm)
    demo_rig.key_glide(arm)
    step("poll", bpy.ops.gaitkeeper.check.poll())
    result = bpy.ops.gaitkeeper.check()
    step("check", result == {"FINISHED"}, str(result))
    return bpy.data.texts["GaitKeeper report"].as_string()


def read_report(report: str) -> None:
    lines = report.splitlines()
    step("kind", "(checked as: person)" in lines[0], lines[0])
    step("both clips", any(line.endswith("  Idle") for line in lines) and "Walk_Glide" in report)
    glide = next(line for line in lines if line.endswith("  Walk_Glide"))
    step("glide flagged", not glide.startswith("PASS"), glide)
    step("skating named", "skating" in report)
    idle = next(line for line in lines if line.endswith("  Idle"))
    step("idle not failed", not idle.startswith("FAIL"), idle)


def fix_makes_copy() -> None:
    before = set(bpy.data.actions.keys())
    bpy.ops.gaitkeeper.fix()
    made = set(bpy.data.actions.keys()) - before
    step("fix keeps original", "Walk_Glide" in bpy.data.actions, f"new: {sorted(made)}")


def uninstall() -> None:
    bpy.ops.preferences.addon_disable(module=MODULE)
    step("disable", not hasattr(bpy.types.Scene, "gaitkeeper"))


if __name__ == "__main__":
    install(sys.argv[sys.argv.index("--") + 1])
    read_report(check_clips())
    fix_makes_copy()
    uninstall()
    print("SMOKE PASSED")
