# SPDX-License-Identifier: GPL-3.0-or-later
"""Check clips, fix the current clip, and jump to a clip from the report."""

from __future__ import annotations

import json

import bpy
from bpy.props import StringProperty

from . import runner
from .core import rig
from .core.report import panel_summary, report_text, status


def armature_with_clip(context: bpy.types.Context) -> bool:
    ob = context.object
    return ob is not None and ob.type == "ARMATURE" and ob.animation_data is not None and ob.animation_data.action


class GAITKEEPER_OT_check(bpy.types.Operator):
    """Check every clip on the selected armature (or only the current one)"""

    bl_idname = "gaitkeeper.check"
    bl_label = "Check clips"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return context.object is not None and context.object.type == "ARMATURE"

    def execute(self, context: bpy.types.Context) -> set[str]:
        settings = context.scene.gaitkeeper
        try:
            result = runner.run_check(context.object, settings)
        except Exception as e:  # shown in the UI rather than as a traceback
            self.report({"ERROR"}, f"GaitKeeper couldn't check this rig: {type(e).__name__}: {e}")
            return {"CANCELLED"}
        runner.write_report(report_text(result))
        settings.result = json.dumps(panel_summary(result))
        need_look = sum(1 for v in result["clips"].values() if status(v) != "PASS")
        self.report(
            {"INFO"},
            f"GaitKeeper: {len(result['clips'])} clips checked, {need_look} need a look. "
            "Full report in the Text Editor.",
        )
        return {"FINISHED"}


class GAITKEEPER_OT_fix(bpy.types.Operator):
    """Re-plant sliding feet, close the loop seam and smooth pops on a copy of the current clip; \
the original is not changed"""

    bl_idname = "gaitkeeper.fix"
    bl_label = "Fix current clip (makes a copy)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return armature_with_clip(context)

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            new, rep = runner.fix_current_clip(context.object, context.scene.gaitkeeper)
        except Exception as e:  # shown in the UI rather than as a traceback
            self.report({"ERROR"}, f"GaitKeeper couldn't fix this clip: {type(e).__name__}: {e}")
            return {"CANCELLED"}
        runner.write_report(runner.fix_report_text(new, rep))
        changes = rep.get("changes", [])
        if new is None:
            nothing = bool(changes) and "nothing to mend" in changes[0]
            why = "nothing to mend in this clip" if nothing else "the fix made the clip worse, so it was thrown away"
            self.report({"WARNING"}, f"GaitKeeper: {why}. See the report.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"GaitKeeper: made {new.name} ({'; '.join(changes)}). Press Check to see it.")
        return {"FINISHED"}


class GAITKEEPER_OT_show(bpy.types.Operator):
    """Make this clip the armature's current animation"""

    bl_idname = "gaitkeeper.show"
    bl_label = "Show clip"
    bl_options = {"INTERNAL"}

    clip: StringProperty()  # type: ignore[valid-type]

    def execute(self, context: bpy.types.Context) -> set[str]:
        act = bpy.data.actions.get(self.clip)
        ob = context.object
        if act is None or ob is None or ob.type != "ARMATURE":
            return {"CANCELLED"}
        rig.set_action(ob, act)
        first, last = rig.clip_range(act)
        context.scene.frame_start, context.scene.frame_end = first, last
        context.scene.frame_set(first)
        return {"FINISHED"}


CLASSES = (GAITKEEPER_OT_check, GAITKEEPER_OT_fix, GAITKEEPER_OT_show)
