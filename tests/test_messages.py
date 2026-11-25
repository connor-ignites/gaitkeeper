# SPDX-License-Identifier: GPL-3.0-or-later
"""Every PASS / WARN / FAIL / TOOL? / REFUSED line is read by animators, not programmers: plain words only.

Scans the add-on's source for string literals (f-strings included, their {values} read as X) that start a
message, without importing anything, so it runs without Blender.
"""

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "gaitkeeper"
STARTS = ("PASS ", "WARN ", "FAIL ", "TOOL? ", "REFUSED ")
JARGON = [
    r"\bcorrelation\b",
    r"\bFroude\b",
    r"\bduty factor\b",
    r"\bjerk\b",
    r"\bp99\b",
    r"\bquaternion",
    r"\beuler\b",
    r"\bRMS\b",
    r"\bdelta\b",
    r"\bm/s2\b",
    r"\bflight phase\b",
    r"\bstd\b",
    r"--[a-z]",
    r"\bTODO\b",
]


def message_texts(path: Path) -> list[tuple[int, str]]:
    """(line, text) for each string in `path` that starts a message."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pieces = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
    found = []
    for node in ast.walk(tree):
        if id(node) in pieces:
            continue
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "X" for v in node.values)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        else:
            continue
        if text.startswith(STARTS) and text not in STARTS:
            found.append((node.lineno, text))
    return found


def all_messages() -> list[tuple[str, int, str]]:
    return [(f.name, line, text) for f in sorted(PACKAGE.rglob("*.py")) for line, text in message_texts(f)]


def test_the_scan_finds_the_messages() -> None:
    assert len(all_messages()) > 40


def test_no_jargon() -> None:
    bad = [
        f"{name}:{line}: {pattern} in {text[:80]!r}"
        for name, line, text in all_messages()
        for pattern in JARGON
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]
    assert bad == []


def test_each_warning_is_a_full_sentence() -> None:
    short = [
        f"{name}:{line}: {text!r}"
        for name, line, text in all_messages()
        if text.startswith(("WARN ", "FAIL ")) and len(text.split()) < 6 and "X" not in text
    ]
    assert short == []
