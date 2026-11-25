# SPDX-License-Identifier: GPL-3.0-or-later
"""Whole-word names, rear legs, the bend test's clean-up, all-or-nothing Fix and Pose Adapt, the clip put back,
named Pose Adapt numbers and the shared loop rule
(tests/blender/regressions.py)."""

from pathlib import Path

from blender_run import lines_starting, run_script


def test_regressions(tmp_path: Path) -> None:
    run = run_script(tmp_path, "regressions.py")
    lines = lines_starting(run, "REGRESSION")
    assert run.returncode == 0 and lines[-1:] == ["REGRESSION PASSED"], "\n".join(lines) + run.stderr[-2000:]
