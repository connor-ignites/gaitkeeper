# SPDX-License-Identifier: GPL-3.0-or-later
"""Progress for long checks (tests/blender/progress.py): one call per clip with the right totals, and the
operators still run headless."""

from pathlib import Path

from blender_run import lines_starting, run_script


def test_progress_once_per_clip(tmp_path: Path) -> None:
    run = run_script(tmp_path, "progress.py")
    lines = lines_starting(run, "PROGRESS")
    assert run.returncode == 0 and lines[-1:] == ["PROGRESS PASSED"], "\n".join(lines) + run.stderr[-2000:]
