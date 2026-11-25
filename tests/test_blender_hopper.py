# SPDX-License-Identifier: GPL-3.0-or-later
"""Two legs and a tail: Auto calls it a hopper only when its feet move together (a kangaroo, not an emu)."""

from pathlib import Path

from blender_run import lines_starting, run_script


def test_hopper_decided_by_motion(tmp_path: Path) -> None:
    run = run_script(tmp_path, "hopper.py")
    lines = lines_starting(run, "HOP")
    assert run.returncode == 0 and lines[-1:] == ["HOP PASSED"], "\n".join(lines) + run.stderr[-2000:]
