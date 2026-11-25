# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the extension, install it into a throwaway Blender profile and check the code-made rig.

Skipped when Blender isn't found (set BLENDER to its executable). Your own Blender profile is never touched:
BLENDER_USER_RESOURCES and BLENDER_USER_EXTENSIONS point at a temporary folder.
"""

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


def test_install_check_and_fix(tmp_path: Path) -> None:
    blender = blender_or_skip()
    zip_path = build(tmp_path / "dist")
    env = dict(os.environ, BLENDER_USER_RESOURCES=str(tmp_path / "res"), BLENDER_USER_EXTENSIONS=str(tmp_path / "ext"))
    smoke = ROOT / "tests" / "blender" / "smoke.py"
    run = subprocess.run(
        [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", str(smoke), "--", str(zip_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=600,
    )
    steps = [line for line in run.stdout.splitlines() if line.startswith("SMOKE")]
    assert run.returncode == 0 and steps[-1:] == ["SMOKE PASSED"], "\n".join(steps) + run.stderr[-2000:]
