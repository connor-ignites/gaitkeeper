# SPDX-License-Identifier: GPL-3.0-or-later
"""Find the Blender executable: $BLENDER, then PATH, then the usual install folders."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def find_blender() -> str:
    """Path to a Blender executable, or SystemExit with a hint."""
    candidates = [os.environ.get("BLENDER"), shutil.which("blender")]
    for root in (Path("C:/Program Files/Blender Foundation"), Path("/Applications")):
        if root.is_dir():
            candidates += [str(p) for p in sorted(root.glob("Blender*/blender*"), reverse=True)]
    found = next((c for c in candidates if c and Path(c).is_file()), None)
    if found is None:
        raise SystemExit("Blender not found: set BLENDER to the blender executable.")
    return found
