# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn per-clip verdict lines into a status and a plain-text report. No Blender here."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict

STATUSES = ("FAIL", "WARN", "PASS")


class CheckResult(TypedDict):
    """What one Check run found: the rig's kind, rig-level lines and each clip's verdict lines."""

    armature: str
    kind: str
    rig: list[str]
    clips: dict[str, list[str]]


def status(verdict: Iterable[str]) -> str:
    """FAIL if any line fails, else WARN if any line warns, else PASS."""
    lines = list(verdict)
    if any(v.startswith("FAIL") for v in lines):
        return "FAIL"
    if any(v.startswith("WARN") for v in lines):
        return "WARN"
    return "PASS"


def tidy(line: str) -> str:
    """Drop the FAIL/WARN prefix: the report shows the status once per clip."""
    return line.split(" ", 1)[1] if line.startswith(("FAIL ", "WARN ")) else line


def counts(clips: dict[str, list[str]]) -> dict[str, int]:
    """How many clips PASS, WARN and FAIL."""
    out = dict.fromkeys(STATUSES, 0)
    for verdict in clips.values():
        out[status(verdict)] += 1
    return out


def summary_line(clips: dict[str, list[str]]) -> str:
    """'12 clips: 9 pass, 2 warn, 1 fail'."""
    c = counts(clips)
    return f"{len(clips)} clips: {c['PASS']} pass, {c['WARN']} warn, {c['FAIL']} fail"


def report_text(result: CheckResult) -> str:
    """The full report written to Blender's Text Editor."""
    lines = [f"GaitKeeper: {result['armature']} (checked as: {result['kind']})", summary_line(result["clips"]), ""]
    if result["rig"]:
        lines += ["Skeleton and skin:", *(f"  {v}" for v in result["rig"]), ""]
    for name, verdict in result["clips"].items():
        lines.append(f"{status(verdict)}  {name}")
        lines += [f"      - {tidy(v)}" for v in verdict]
    return "\n".join(lines)


def panel_summary(result: CheckResult) -> dict:
    """The compact form the side panel draws from: {kind, rig, clips: {name: [status, [lines]]}}."""
    return {
        "kind": result["kind"],
        "rig": result["rig"],
        "clips": {name: [status(v), [tidy(x) for x in v]] for name, v in result["clips"].items()},
    }
