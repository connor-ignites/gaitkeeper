# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose Adapt must give exactly the pinned result: run tests/blender/adapt_pin.py in Blender and compare every
run's report and per-bone F-curve hashes with tests/blender/adapt_golden.json.

To re-pin after a change meant to alter the output, run adapt_pin.py by hand and write the golden file.
"""

import json
from pathlib import Path

from blender_run import ROOT, run_script

GOLDEN = ROOT / "tests" / "blender" / "adapt_golden.json"


def run_pin(tmp_path: Path) -> dict:
    out = tmp_path / "adapt.json"
    run = run_script(tmp_path, "adapt_pin.py", str(out))
    assert run.returncode == 0 and out.exists(), run.stdout[-1500:] + run.stderr[-1500:]
    return json.loads(out.read_text(encoding="utf-8"))


def differences(got: dict, want: dict) -> list[str]:
    """Which runs differ, and in which part (result, action name, report, or which bones' curves)."""
    out = []
    for key in sorted(want):
        out += [f"{key}: {part}" for part in ("result", "action", "report") if got[key][part] != want[key][part]]
        bones = set(got[key]["fcurves"]) | set(want[key]["fcurves"])
        bad = sorted(b for b in bones if got[key]["fcurves"].get(b) != want[key]["fcurves"].get(b))
        if bad:
            out.append(f"{key}: curves of {', '.join(bad)}")
    return out


def test_adapt_matches_golden(tmp_path: Path) -> None:
    got, want = run_pin(tmp_path), json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sorted(got) == sorted(want)
    differ = differences(got, want)
    assert not differ, "\n".join(differ)
