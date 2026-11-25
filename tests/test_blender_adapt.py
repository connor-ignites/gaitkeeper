# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose Adapt must give exactly the pinned result: run tests/blender/adapt_pin.py in Blender and compare every
run's report and per-bone F-curve hashes with tests/blender/adapt_golden.json.

Skipped when Blender isn't found (set BLENDER to its executable). Your own Blender profile is never touched.
To re-pin after a change meant to alter the output, run adapt_pin.py by hand and write the golden file.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from blender_exe import find_blender  # noqa: E402
from build import build  # noqa: E402

GOLDEN = ROOT / "tests" / "blender" / "adapt_golden.json"


def blender_or_skip() -> str:
    try:
        return find_blender()
    except SystemExit:
        pytest.skip("Blender not found")


def run_pin(blender: str, tmp_path: Path) -> dict:
    zip_path = build(tmp_path / "dist")
    env = dict(os.environ, BLENDER_USER_RESOURCES=str(tmp_path / "res"), BLENDER_USER_EXTENSIONS=str(tmp_path / "ext"))
    out = tmp_path / "adapt.json"
    pin = ROOT / "tests" / "blender" / "adapt_pin.py"
    args = ["-b", "--factory-startup", "--python-exit-code", "1", "--python", str(pin), "--", str(zip_path), str(out)]
    run = subprocess.run(
        [blender, *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=900,
    )
    assert run.returncode == 0 and out.exists(), run.stdout[-1500:] + run.stderr[-1500:]
    return json.loads(out.read_text(encoding="utf-8"))


def test_adapt_matches_golden(tmp_path: Path) -> None:
    blender = blender_or_skip()
    got, want = run_pin(blender, tmp_path), json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sorted(got) == sorted(want)
    differ = []
    for key in sorted(want):
        for part in ("result", "action", "report"):
            if got[key][part] != want[key][part]:
                differ.append(f"{key}: {part}")
        bones = set(got[key]["fcurves"]) | set(want[key]["fcurves"])
        bad = sorted(b for b in bones if got[key]["fcurves"].get(b) != want[key]["fcurves"].get(b))
        if bad:
            differ.append(f"{key}: curves of {', '.join(bad)}")
    assert not differ, "\n".join(differ)
