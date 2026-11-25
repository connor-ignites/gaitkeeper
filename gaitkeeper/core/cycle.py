# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: whether a clip loops. One rule for people and animals. No Blender needed.

A clip loops when its name says so ("Walk_Loop"), or when its last pose turns every bone back to within
SEAM_WARN_DEG of its first pose. The second half catches loops whose names don't say so (a "Walk" or
"Idle" exported from a pack) without taking every clip named walk or run for a loop: a "Walk_Start"
ends in a different pose, so it isn't one. The threshold is the one the seam check warns at, so a clip
judged a loop by its poses never gets the "loop doesn't join up" warning. Only rotations are compared:
a walk with root motion ends somewhere else but in the same pose. A clip of fewer than three frames
loops only by its name.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import motion_math as mm
from .names import says_loop

SEAM_WARN_DEG = 5.0  # a bone turning more than this from the last frame back to the first hitches the loop
MIN_LOOP_FRAMES = 3

Pose = dict[str, Sequence[float]]  # bone -> local rotation quaternion (w, x, y, z)


def seam_deg(first: Pose, last: Pose) -> float:
    """The biggest bone turn between two poses, in degrees (0 when they share no bones)."""
    return max((mm.q_angle_deg(first[k], last[k]) for k in first if k in last), default=0.0)


def loops(name: str, first: Pose, last: Pose, frames: int) -> bool:
    """The shared loop rule (see the module's docstring). first, last: the clip's first and last poses."""
    if says_loop(name):
        return True
    return frames >= MIN_LOOP_FRAMES and seam_deg(first, last) <= SEAM_WARN_DEG
