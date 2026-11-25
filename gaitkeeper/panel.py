# SPDX-License-Identifier: GPL-3.0-or-later
"""The GaitKeeper tab in the 3D View's sidebar (N)."""

from __future__ import annotations

import json
import textwrap

import bpy

from .adapt_ops import kept_poses
from .core.report import STATUSES, tidy
from .runner import REPORT_NAME

ICONS = {"PASS": "CHECKMARK", "WARN": "ERROR", "FAIL": "CANCEL"}
LIST_LIMIT = 40  # clips listed in the panel; the rest are in the report
WRAP = 90  # characters per panel line


def current_clip(context: bpy.types.Context) -> bpy.types.Action | None:
    ob = context.object
    if ob is None or ob.type != "ARMATURE" or ob.animation_data is None:
        return None
    return ob.animation_data.action


class GAITKEEPER_PT_panel(bpy.types.Panel):
    bl_label = "GaitKeeper"
    bl_idname = "GAITKEEPER_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GaitKeeper"

    def draw(self, context: bpy.types.Context) -> None:
        settings = context.scene.gaitkeeper
        col = self.layout.column()
        for name in ("body", "hopper", "every_clip_strikes", "attacks_for", "current_only"):
            col.prop(settings, name)
        col.operator("gaitkeeper.check", icon="CHECKMARK")
        fix = col.box()
        fix.prop(settings, "root_motion")
        fix.operator("gaitkeeper.fix", icon="MODIFIER")
        self.draw_adapt(col.box(), settings, current_clip(context))
        try:
            result = json.loads(settings.result) if settings.result else None
        except ValueError:
            result = None
        if result is None:
            col.label(text="Select an armature and press Check.")
            return
        self.draw_result(col, result, current_clip(context))

    @staticmethod
    def draw_adapt(box: bpy.types.UILayout, settings, act: bpy.types.Action | None) -> None:
        box.label(text="Pose Adapt: pose bones on a frame (no key), then:", icon="POSE_HLT")
        box.prop(settings, "adapt_mode")
        if settings.adapt_mode != "WHOLE":
            box.prop(settings, "adapt_fade")
        if settings.adapt_mode != "HERE":
            box.prop(settings, "adapt_mirror")
        box.prop(settings, "adapt_feet")
        row = box.row()
        row.operator("gaitkeeper.adapt_keep", icon="PINNED")
        kept = kept_poses(settings, act) if act else []
        if kept:
            row.operator("gaitkeeper.adapt_clear", text="", icon="X")
            box.label(text="Kept poses on frames " + ", ".join(str(f) for f, _ in sorted(kept)))
        box.operator("gaitkeeper.adapt", icon="MOD_ARMATURE")

    @staticmethod
    def draw_result(col: bpy.types.UILayout, result: dict, act: bpy.types.Action | None) -> None:
        clips = result["clips"]
        counts = {k: sum(1 for v in clips.values() if v[0] == k) for k in STATUSES}
        box = col.box()
        tally = f"{counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail"
        box.label(text=f"{result['kind'].capitalize()}: {tally}")
        for line in result["rig"][:3]:
            box.label(text=tidy(line)[:WRAP], icon="ARMATURE_DATA")
        if act is not None and act.name in clips:
            current = col.box()
            current.label(text=f"Current clip: {act.name} ({clips[act.name][0]})", icon="ACTION")
            for message in clips[act.name][1][:8]:
                for i, part in enumerate(textwrap.wrap(message, WRAP)[:3]):
                    current.label(text=("- " if i == 0 else "  ") + part)
        ordered = sorted(clips.items(), key=lambda kv: STATUSES.index(kv[1][0]))
        for name, (state, messages) in ordered[:LIST_LIMIT]:
            box.row().operator("gaitkeeper.show", text=name, icon=ICONS[state], emboss=False).clip = name
            if messages:
                box.label(text="    " + messages[0][:WRAP])
        if len(ordered) > LIST_LIMIT:
            box.label(text=f"... and {len(ordered) - LIST_LIMIT} more in the report")
        box.label(text=f"Full report: Text Editor > {REPORT_NAME}", icon="TEXT")


CLASSES = (GAITKEEPER_PT_panel,)
