# SPDX-License-Identifier: GPL-3.0-or-later
"""Whole-word names, rear legs, the bend test's clean-up, all-or-nothing Fix and the shared loop rule
(tests/blender/review_fixes.py)."""

from pathlib import Path

from blender_run import lines_starting, run_script


def test_review_fixes(tmp_path: Path) -> None:
    run = run_script(tmp_path, "review_fixes.py")
    lines = lines_starting(run, "REVIEW")
    assert run.returncode == 0 and lines[-1:] == ["REVIEW PASSED"], "\n".join(lines) + run.stderr[-2000:]
