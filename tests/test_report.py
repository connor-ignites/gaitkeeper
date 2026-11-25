# SPDX-License-Identifier: GPL-3.0-or-later
"""The report text and the panel summary (core.report)."""

from core.report import CheckResult, counts, panel_summary, report_text, status, tidy

RESULT = CheckResult(
    armature="Hero",
    kind="person",
    rig=["WARN no skinned mesh found on this skeleton: only the bones were checked."],
    clips={
        "Idle": ["PASS no sinking, skating, seam jumps, pops, impossible joints or physics problems found."],
        "Walk": ["WARN left foot slides 0.25 m/s while planted (skating)."],
        "Punch": ["WARN arm snaps in one frame.", "FAIL knee bends backwards 40 degrees."],
    },
)


def test_status_takes_the_worst_line() -> None:
    assert status([]) == "PASS"
    assert status(["PASS fine"]) == "PASS"
    assert status(["PASS fine", "WARN odd"]) == "WARN"
    assert status(["WARN odd", "FAIL broken"]) == "FAIL"


def test_tidy_drops_only_the_status_word() -> None:
    assert tidy("WARN left foot slides") == "left foot slides"
    assert tidy("FAIL knee bends") == "knee bends"
    assert tidy("PASS nothing found") == "PASS nothing found"


def test_counts() -> None:
    assert counts(RESULT["clips"]) == {"FAIL": 1, "WARN": 1, "PASS": 1}


def test_report_lists_every_clip_under_its_status() -> None:
    lines = report_text(RESULT).splitlines()
    assert lines[0] == "GaitKeeper: Hero (checked as: person)"
    assert lines[1] == "3 clips: 1 pass, 1 warn, 1 fail"
    assert "Skeleton and skin:" in lines
    assert "FAIL  Punch" in lines
    assert "      - knee bends backwards 40 degrees." in lines


def test_panel_summary_keeps_status_and_tidied_lines() -> None:
    summary = panel_summary(RESULT)
    assert summary["kind"] == "person"
    assert summary["clips"]["Walk"] == ["WARN", ["left foot slides 0.25 m/s while planted (skating)."]]
