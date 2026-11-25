# SPDX-License-Identifier: GPL-3.0-or-later
"""Make the add-on's Blender-free maths importable as `core` (the package __init__ needs bpy)."""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gaitkeeper"))


def axis_q(axis: tuple[float, float, float], deg: float) -> tuple[float, float, float, float]:
    """Quaternion (w, x, y, z) turning `deg` degrees about a unit axis."""
    h = math.radians(deg) / 2
    return (math.cos(h), *(c * math.sin(h) for c in axis))
