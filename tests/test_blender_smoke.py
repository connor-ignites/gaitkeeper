# SPDX-License-Identifier: GPL-3.0-or-later
"""Install the extension into a throwaway Blender profile, check a code-made rig and fix a clip."""

from pathlib import Path

from blender_run import lines_starting, run_script


def test_install_check_and_fix(tmp_path: Path) -> None:
    run = run_script(tmp_path, "smoke.py")
    steps = lines_starting(run, "SMOKE")
    assert run.returncode == 0 and steps[-1:] == ["SMOKE PASSED"], "\n".join(steps) + run.stderr[-2000:]
