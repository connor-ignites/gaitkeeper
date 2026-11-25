# SPDX-License-Identifier: GPL-3.0-or-later
"""Odd rigs and clips (tests/blender/edge_cases.py): no crash, a clear message where GaitKeeper can't judge."""

from pathlib import Path

from blender_run import lines_starting, run_script


def test_edge_cases_never_crash(tmp_path: Path) -> None:
    run = run_script(tmp_path, "edge_cases.py", str(tmp_path))
    lines = lines_starting(run, "EDGE")
    assert run.returncode == 0 and lines[-1:] == ["EDGE PASSED"], "\n".join(lines) + run.stderr[-2000:]
