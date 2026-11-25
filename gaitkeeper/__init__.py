# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: checks every animation clip on a skeleton for motion faults before it goes into a game.

Select an armature, open the sidebar (N) in the 3D View, GaitKeeper tab, press Check clips. Each clip gets
PASS, WARN or FAIL with the reasons; the full report goes to the Text Editor as "GaitKeeper report".
Checking changes nothing in the scene. Fix and Pose Adapt always work on a copy of the clip.
"""

from __future__ import annotations

import bpy

from . import adapt_ops, operators, panel, props

CLASSES = (*operators.CLASSES, *adapt_ops.CLASSES, *panel.CLASSES)


def register() -> None:
    props.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    props.unregister()
