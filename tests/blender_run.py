# SPDX-License-Identifier: GPL-3.0-or-later
"""Run a script from tests/blender/ in Blender against a freshly built extension zip.

Blender's user folders point at the test's temporary folder, so your own Blender profile is never touched.
Tests skip when Blender isn't found (set BLENDER to its executable).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from blender_exe import find_blender  # noqa: E402
from build import build  # noqa: E402


def blender_or_skip() -> str:
    try:
        return find_blender()
    except SystemExit:
        pytest.skip("Blender not found")


def run_script(tmp_path: Path, script: str, *args: str, background: bool = True) -> subprocess.CompletedProcess:
    """Build the zip, then run tests/blender/<script> with `-- <zip> <args...>`."""
    blender = blender_or_skip()
    zip_path = build(tmp_path / "dist")
    env = dict(os.environ, BLENDER_USER_RESOURCES=str(tmp_path / "res"), BLENDER_USER_EXTENSIONS=str(tmp_path / "ext"))
    flags = ["-b"] if background else []
    path = ROOT / "tests" / "blender" / script
    cmd = [blender, *flags, "--factory-startup", "--python-exit-code", "1", "--python", str(path)]
    return subprocess.run(
        [*cmd, "--", str(zip_path), *args], capture_output=True, text=True, env=env, check=False, timeout=900
    )


def lines_starting(run: subprocess.CompletedProcess, prefix: str) -> list[str]:
    return [line for line in run.stdout.splitlines() if line.startswith(prefix)]
