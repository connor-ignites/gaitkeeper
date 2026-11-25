# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose Adapt: pose bones on a frame (without keying) and bake the change through a copy of the clip.

"Keep this pose" remembers poses on several frames; "Adapt" blends them all in, keeping untouched feet planted.
"""

from __future__ import annotations

import json
import traceback

import bpy
from mathutils import Matrix, Quaternion

from . import runner
from .core import adapt, creature, rig
from .operators import armature_with_clip


def load_kept(settings, clip_name: str) -> dict:
    """The kept poses as stored, or a fresh record when they belong to another clip or can't be read."""
    try:
        kept = json.loads(settings.adapt_kept or "{}")
    except ValueError:
        kept = {}
    return kept if kept.get("clip") == clip_name else {"clip": clip_name, "poses": {}}


def kept_poses(settings, act: bpy.types.Action) -> list[tuple[int, dict]]:
    """Poses kept for this clip: [(frame, {bone: (loc, rot, scale)})]."""
    poses = load_kept(settings, act.name)["poses"]
    return [(int(f), {b: tuple(tuple(x) for x in v) for b, v in bones.items()}) for f, bones in poses.items()]


def changed_bones(arm: bpy.types.Object, scene: bpy.types.Scene) -> dict:
    """Bones posed by hand on this frame (compared with the clip's own pose), left on screen as posed."""
    edited = adapt.capture_pose(arm)
    scene.frame_set(scene.frame_current)  # re-reads the clip's own pose on this frame
    clip = adapt.capture_pose(arm)
    changed = {b: v for b, v in edited.items() if adapt.pose_delta({b: v}, clip)}
    for b, (loc, rot, sca) in changed.items():
        arm.pose.bones[b].matrix_basis = Matrix.LocRotScale(loc, Quaternion(rot), sca)
    return changed


class GAITKEEPER_OT_adapt_keep(bpy.types.Operator):
    """Remember the pose on this frame (without keying it), then pose another frame; \
Adapt blends all the kept poses into the clip"""

    bl_idname = "gaitkeeper.adapt_keep"
    bl_label = "Keep this pose"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return armature_with_clip(context)

    def execute(self, context: bpy.types.Context) -> set[str]:
        arm, scene, settings = context.object, context.scene, context.scene.gaitkeeper
        changed = changed_bones(arm, scene)
        if not changed:
            self.report({"WARNING"}, "Pose Adapt: nothing changed on this frame yet: pose a bone first (no key).")
            return {"CANCELLED"}
        kept = load_kept(settings, arm.animation_data.action.name)
        kept["poses"][str(scene.frame_current)] = {b: [list(x) for x in v] for b, v in changed.items()}
        settings.adapt_kept = json.dumps(kept)
        frames = ", ".join(sorted(kept["poses"], key=int))
        where = f"frame {scene.frame_current} ({len(changed)} bones)"
        self.report({"INFO"}, f"Pose Adapt: kept the pose on {where}. Kept: {frames}.")
        return {"FINISHED"}


class GAITKEEPER_OT_adapt_clear(bpy.types.Operator):
    """Forget the poses kept with Keep this pose"""

    bl_idname = "gaitkeeper.adapt_clear"
    bl_label = "Clear kept poses"
    bl_options = {"REGISTER"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        context.scene.gaitkeeper.adapt_kept = ""
        return {"FINISHED"}


def adapt_current(arm: bpy.types.Object, scene: bpy.types.Scene) -> tuple[bpy.types.Action, dict]:
    """Run Pose Adapt on the current clip; animals are judged by the animal checks."""
    settings = scene.gaitkeeper
    act = arm.animation_data.action
    edited = adapt.capture_pose(arm)
    animal = runner.animal_rig(arm, settings)
    judge, cyclic, roles = None, None, rig.role_map(arm)
    if animal is not None:
        roles = creature.leg_roles(arm, animal.legs, animal.pelvis)
        cyclic = creature.loops(act.name)

        def judge(a: bpy.types.Action) -> list[str]:
            return creature.measure_clip(
                arm, a, animal.legs, animal.pelvis, animal.hopper, animal.rest_widths, settings.every_clip_strikes
            )[1]

    return adapt.adapt_clip(
        arm,
        act,
        roles,
        runner.scene_fps(scene),
        scene.frame_current,
        edited,
        settings.adapt_mode.lower(),
        settings.adapt_fade,
        settings.adapt_mirror,
        settings.adapt_feet,
        more=kept_poses(settings, act),
        judge=judge,
        cyclic=cyclic,
    )


class GAITKEEPER_OT_adapt(bpy.types.Operator):
    """Spread the pose you made on this frame through the clip, keeping the feet planted; \
the original clip is not changed"""

    bl_idname = "gaitkeeper.adapt"
    bl_label = "Adapt clip to this pose (makes a copy)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return armature_with_clip(context)

    def execute(self, context: bpy.types.Context) -> set[str]:
        arm, scene = context.object, context.scene
        act, frame = arm.animation_data.action, scene.frame_current
        try:
            new, rep = adapt_current(arm, scene)
        except Exception as e:  # reported in the UI; the traceback goes to the system console
            traceback.print_exc()
            rig.set_action(arm, act)
            scene.frame_set(frame)
            self.report(*self.failure_message(e, scene))
            return {"CANCELLED"}
        scene.frame_start, scene.frame_end = rig.clip_range(new)
        scene.gaitkeeper.adapt_kept = ""  # the kept poses belonged to the old clip
        runner.write_report("\n".join(adapt.report_lines(new.name, rep)))
        worse = f" Check the report: {len(rep['worse'])} thing(s) got worse." if rep["worse"] else ""
        self.report({"INFO"}, f"Pose Adapt: made {new.name}, spread over {rep['how']}.{worse}")
        return {"FINISHED"}

    @staticmethod
    def failure_message(e: Exception, scene: bpy.types.Scene) -> tuple[set[str], str]:
        """ValueError is a refusal with a reason; anything else is an error."""
        if not isinstance(e, ValueError):
            return {"ERROR"}, f"Pose Adapt couldn't change this clip: {type(e).__name__}: {e}"
        auto_key = scene.tool_settings.use_keyframe_insert_auto and "nothing changed" in str(e)
        tip = " Auto-keying is on: switch it off so the pose isn't keyed into the clip." if auto_key else ""
        return {"WARNING"}, f"Pose Adapt: {e}.{tip}"


CLASSES = (GAITKEEPER_OT_adapt_keep, GAITKEEPER_OT_adapt_clear, GAITKEEPER_OT_adapt)
