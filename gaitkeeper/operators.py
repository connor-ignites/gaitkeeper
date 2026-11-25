# SPDX-License-Identifier: GPL-3.0-or-later
"""Check clips, fix the current clip, and jump to a clip from the report."""

from __future__ import annotations

import json
import traceback
from collections.abc import Iterator
from contextlib import contextmanager

import bpy
from bpy.props import StringProperty

from . import runner
from .core import rig
from .core.report import panel_summary, report_text, status


def armature_with_clip(context: bpy.types.Context) -> bool:
    ob = context.object
    return (
        ob is not None
        and ob.type == "ARMATURE"
        and ob.animation_data is not None
        and ob.animation_data.action is not None
    )


@contextmanager
def shown_progress(context: bpy.types.Context, doing: str) -> Iterator[runner.Progress | None]:
    """A progress callback for the runner that moves the progress cursor and names the clip in the status
    bar, both cleared when the block ends. None without a window (Blender run in the background, or no window in
    the context), so nothing is shown."""
    if bpy.app.background or context.window is None:
        yield None
        return
    wm, workspace = context.window_manager, context.workspace

    def show(done: int, total: int, clip: str) -> None:
        wm.progress_update(done / max(1, total))
        workspace.status_text_set(f"GaitKeeper: {doing} {clip} ({done + 1} of {total})")

    wm.progress_begin(0.0, 1.0)
    try:
        yield show
    finally:
        wm.progress_end()
        workspace.status_text_set(None)


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
            with shown_progress(context, "checking") as progress:
                result = runner.run_check(context.object, context.scene, context.view_layer, progress)
        except Exception as e:  # reported in the UI; the traceback goes to the system console
            traceback.print_exc()
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
            with shown_progress(context, "fixing") as progress:
                new, rep = runner.fix_current_clip(context.object, context.scene, context.view_layer, progress)
        except Exception as e:  # reported in the UI; the traceback goes to the system console
            traceback.print_exc()
            self.report({"ERROR"}, f"GaitKeeper couldn't fix this clip: {type(e).__name__}: {e}")
            return {"CANCELLED"}
        runner.write_report(runner.fix_report_text(new, rep))
        changes = rep.get("changes", [])
        if new is None:
            refused = [v.removeprefix("REFUSED ") for v in rep["verdict"] if v.startswith("REFUSED ")]
            why = changes[0] if changes and "nothing to mend" in changes[0] else (refused or ["no fix made"])[0]
            self.report({"WARNING"}, f"GaitKeeper: {why.rstrip('.')}. See the report.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"GaitKeeper: made {new.name} ({'; '.join(changes)}). Press Check to see it.")
        return {"FINISHED"}


class GAITKEEPER_OT_show(bpy.types.Operator):
    """Make this clip the armature's current animation"""

    bl_idname = "gaitkeeper.show"
    bl_label = "Show clip"
    bl_options = {"INTERNAL", "UNDO"}

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
