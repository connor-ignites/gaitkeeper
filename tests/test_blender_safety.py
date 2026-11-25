# SPDX-License-Identifier: GPL-3.0-or-later
"""The safety promise (tests/blender/safety.py): Check changes nothing, Fix only adds a copy, a saved file
reopens with its clips unchanged, and Undo takes the copy away.

Undo needs a Blender window, so that part runs only with GAITKEEPER_WINDOW_TESTS=1 (a window opens briefly).
"""

import os
from pathlib import Path

import pytest
from blender_run import lines_starting, run_script


def assert_passed(run) -> None:
    steps = lines_starting(run, "SAFETY")
    assert run.returncode == 0 and steps[-1:] == ["SAFETY PASSED"], "\n".join(steps) + run.stderr[-2000:]


def test_check_and_fix_are_safe(tmp_path: Path) -> None:
    assert_passed(run_script(tmp_path, "safety.py", str(tmp_path)))


@pytest.mark.skipif(not os.environ.get("GAITKEEPER_WINDOW_TESTS"), reason="opens a Blender window")
def test_undo_after_fix(tmp_path: Path) -> None:
    run = run_script(tmp_path, "safety.py", str(tmp_path), background=False)
    assert_passed(run)
    assert any("undo removes the copy" in line for line in lines_starting(run, "SAFETY ok"))
