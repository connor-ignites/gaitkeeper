# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: Fix is all or nothing. If it fails midway, the file is left as it was before Fix started."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import bpy


@contextmanager
def all_or_nothing(arm: bpy.types.Object) -> Iterator[None]:
    """On any error inside: every action made inside is removed, the armature's clip (and its slot, Blender
    4.4+) is put back, and the error is raised again. A half-written "_fixed" copy never stays behind."""
    ad = arm.animation_data
    action = ad.action if ad else None
    slot = getattr(ad, "action_slot", None) if ad else None
    before = {a.as_pointer() for a in bpy.data.actions}
    try:
        yield
    except BaseException:
        _put_back(arm, action, slot)
        for act in [a for a in bpy.data.actions if a.as_pointer() not in before]:
            bpy.data.actions.remove(act)
        raise


def _put_back(arm: bpy.types.Object, action: bpy.types.Action | None, slot: object | None) -> None:
    """Make `action` (and `slot`) the armature's current clip again."""
    ad = arm.animation_data
    if ad is None:
        if action is None:
            return
        ad = arm.animation_data_create()
    ad.action = action
    if slot is not None:
        ad.action_slot = slot
