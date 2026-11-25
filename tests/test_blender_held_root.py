# SPDX-License-Identifier: GPL-3.0-or-later
"""A rig whose Root bone holds a turn and a 100x scale (Unity exports): read as it stands, scene untouched."""

from pathlib import Path

from blender_run import lines_starting, run_script


def test_held_root_rig_reads_standing(tmp_path: Path) -> None:
    run = run_script(tmp_path, "held_root.py")
    lines = lines_starting(run, "HELD")
    assert run.returncode == 0 and lines[-1:] == ["HELD PASSED"], "\n".join(lines) + run.stderr[-2000:]
