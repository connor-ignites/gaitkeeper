# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: Fix and Pose Adapt are all or nothing. If one fails midway, the file is left as it was
before it started."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import bpy

from .rig import restore_clip, save_clip

REFUSED_WORSE = "REFUSED the fix made this clip worse, so it was thrown away."


@contextmanager
def all_or_nothing(arm: bpy.types.Object) -> Iterator[None]:
    """On any error inside: every action made inside is removed, the armature's clip (and its slot, Blender
    4.4+) is put back, and the error is raised again. A half-written "_fixed" or "_adapted" copy never
    stays behind."""
    clip = save_clip(arm)
    before = {a.as_pointer() for a in bpy.data.actions}
    try:
        yield
    except BaseException:
        restore_clip(arm, clip)
        for act in [a for a in bpy.data.actions if a.as_pointer() not in before]:
            bpy.data.actions.remove(act)
        raise
