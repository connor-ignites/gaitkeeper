# SPDX-License-Identifier: GPL-3.0-or-later
"""Glue between the panel and the checks: decides what kind of body a rig is, runs the checks or the fix,
and leaves the scene as it found it."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import NamedTuple

import bpy

from .core import body as body_checks
from .core import checks, creature, creature_fix, edit, rig, skin
from .core.checks import scene_fps
from .core.report import CheckResult
from .core.rig import action_fcurves

REPORT_NAME = "GaitKeeper report"
POSE_CLIP = re.compile(r"(^|[^a-z0-9])[ta][ _-]?pose([^a-z0-9]|$)")  # T-pose and A-pose clips, never checked
TAIL = re.compile(r"(^|[^a-z])tail")  # "Tail_01", "tail.L"; not "ponytail"
BONE_PATH = re.compile(r'pose\.bones\["([^"]+)"\]')
NO_BONES = "FAIL this armature has no bones, so there is nothing to check."
NOT_FULLY_CHECKED = (
    "WARN not fully checked: some of this rig's bones weren't found (see Skeleton and skin), "
    "so the checks that need them were skipped."
)
NOTHING_TO_MEND = "nothing to mend: this clip has no keys on this rig's bones"
BONES_NOT_FOUND = (
    "REFUSED some of this rig's bones weren't found, so a fix could move the wrong ones. Press Check to see which."
)

Progress = Callable[[int, int, str], None]  # (clips done, clips in all, the clip starting now)


class AnimalRig(NamedTuple):
    """What the animal checks need to know about a rig."""

    legs: dict[str, list[str]]
    pelvis: str
    hopper: bool
    rest_widths: dict[str, float]


def write_report(text: str) -> None:
    """Replace the report text block's contents."""
    block = bpy.data.texts.get(REPORT_NAME) or bpy.data.texts.new(REPORT_NAME)
    block.clear()
    block.write(text)


@contextmanager
def kept_frame(scene: bpy.types.Scene) -> Iterator[None]:
    """Put the playhead back where it was."""
    frame = scene.frame_current
    try:
        yield
    finally:
        scene.frame_set(frame)


TRANSFORMS = ("location", "rotation_quaternion", "rotation_euler", "rotation_axis_angle", "scale")


def _transform(item: bpy.types.Object | bpy.types.PoseBone) -> tuple:
    return tuple(tuple(getattr(item, name)) for name in TRANSFORMS)


def _set_transform(item: bpy.types.Object | bpy.types.PoseBone, values: tuple) -> None:
    for name, value in zip(TRANSFORMS, values):
        setattr(item, name, value)


def reported(actions: list[bpy.types.Action], progress: Progress | None) -> Iterator[bpy.types.Action]:
    """The clips one by one, telling `progress` (done, total, clip name) as each one starts."""
    for done, act in enumerate(actions):
        if progress is not None:
            progress(done, len(actions), act.name)
        yield act


@contextmanager
def kept_transforms(
    scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer, skip: bpy.types.Object | None = None
) -> Iterator[None]:
    """Put every object's and pose bone's transform back, keyed or not. Playing clips frame by frame
    re-evaluates animation, which would otherwise throw away a pose the user set but hasn't keyed."""
    saved = []
    for ob in scene.objects:
        if ob == skip:
            continue
        saved.append((ob, _transform(ob)))
        if ob.type == "ARMATURE" and ob.pose is not None:
            saved += [(pb, _transform(pb)) for pb in ob.pose.bones]
    try:
        yield
    finally:
        view_layer.update()  # let the restored clip evaluate first, so it can't overwrite the pose
        for item, values in saved:
            _set_transform(item, values)
        view_layer.update()


@contextmanager
def kept_action(arm: bpy.types.Object) -> Iterator[None]:
    """Put the armature's current clip (and its slot, Blender 4.4+) back."""
    ad = arm.animation_data
    action = ad.action if ad else None
    slot = getattr(ad, "action_slot", None) if ad else None
    try:
        yield
    finally:
        if ad is None:
            arm.animation_data_clear()
        else:
            ad.action = action
            if slot is not None:
                ad.action_slot = slot


def body_kind(
    arm: bpy.types.Object, legs: dict, scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer
) -> tuple[bool, bool]:
    """(animal, hopper). Auto: four legs, or two legs and a tail, is an animal. Two legs and a tail hop unless
    the stepping clips show the feet taking turns (an emu walks; a kangaroo hops)."""
    settings = scene.gaitkeeper
    tail = any(TAIL.search(b.name.lower()) for b in arm.data.bones)
    fore = any(k.startswith("fore") for k in legs)
    animal, hopper = fore or tail, tail and not fore and len(legs) == 2
    if settings.body != "AUTO":
        animal = settings.body == "CREATURE"
    if settings.hopper != "AUTO":
        hopper = settings.hopper == "YES"
    elif hopper:
        hopper = hops_by_motion(arm, legs, scene, view_layer) is not False
    return animal, hopper


def hops_by_motion(
    arm: bpy.types.Object, legs: dict, scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer
) -> bool | None:
    """Whether a two-legged animal's stepping clips move its feet together (None: no clip tells).
    Plays the clips, then puts the scene back as it was."""
    with kept_transforms(scene, view_layer), kept_frame(scene), kept_action(arm):
        return creature.hops(arm, clips_to_check(arm, False), legs, pelvis_bone(arm, legs), scene)


def pelvis_bone(arm: bpy.types.Object, legs: dict) -> str:
    """The hips bone if the naming says so, else the parent of the first leg's top bone."""
    hips = rig.role_map(arm).get("hips")
    if hips is not None:
        return hips
    top = arm.pose.bones[next(iter(legs.values()))[0]]
    return top.parent.name if top.parent else top.name


def body_setup(
    arm: bpy.types.Object, scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer
) -> tuple[str, AnimalRig | None]:
    """What the scene's settings make this rig ("person", "animal" or "hopper") and, for an animal whose
    legs were found, its animal setup (None for a person, or an animal with no legs found)."""
    legs = creature.find_legs(arm)
    animal, hopper = body_kind(arm, legs, scene, view_layer)
    if not animal:
        return "person", None
    found = AnimalRig(legs, pelvis_bone(arm, legs), hopper, creature.rest_width(arm, legs)) if legs else None
    return ("hopper" if hopper else "animal"), found


def animal_rig(arm: bpy.types.Object, scene: bpy.types.Scene, view_layer: bpy.types.ViewLayer) -> AnimalRig | None:
    """The animal setup when the scene's settings make this rig an animal with legs, else None."""
    return body_setup(arm, scene, view_layer)[1]


def animates(act: bpy.types.Action, arm: bpy.types.Object) -> bool:
    """True when the action keys at least one of this armature's bones."""
    bones = set(arm.pose.bones.keys())
    matches = (BONE_PATH.match(fc.data_path) for fc in action_fcurves(act))
    return any(m is not None and m[1] in bones for m in matches)


def clips_to_check(arm: bpy.types.Object, current_only: bool) -> list[bpy.types.Action]:
    """The current clip, or every clip in the file that animates this rig (rest-pose clips left out)."""
    if current_only:
        ad = arm.animation_data
        return [ad.action] if ad and ad.action else []
    return [a for a in bpy.data.actions if animates(a, arm) and not POSE_CLIP.search(a.name.lower())]


def judged_label(arm: bpy.types.Object, act: bpy.types.Action, enemy: bool) -> str:
    """The name the checks read for this clip; Check and Fix must judge the same way."""
    return rig.clip_label(arm, act.name) + (" (enemy)" if enemy else "")


def check_person(
    arm: bpy.types.Object,
    actions: list,
    enemy: bool,
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    progress: Progress | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """Skeleton, skin and per-clip lines for a two-legged, two-armed rig."""
    roles = rig.role_map(arm)
    fps = scene_fps(scene)
    saved_file = bpy.data.filepath.lower().endswith(".blend")
    report = checks.rig_report(arm, roles)
    rig_lines = checks.rig_verdicts(report, None)
    rig_lines += skin.skin_verdicts(skin.skin_report(arm, roles, view_layer), saved_file)
    # a clip on a rig whose bones weren't all found can't honestly PASS
    partly = [NOT_FULLY_CHECKED] if report["missing"] else []
    clips = {}
    for act in reported(actions, progress):
        label = judged_label(arm, act, enemy)
        cyclic = checks.clip_loops(arm, act, scene, label)
        measured = checks.measure(rig.sample(arm, act, roles, scene), fps, cyclic, arm, label)
        clips[act.name] = partly + checks.verdicts(measured, None)
    return body_checks.misread_verdicts(clips) + rig_lines, clips


def check_animal(
    arm: bpy.types.Object,
    actions: list,
    animal: AnimalRig,
    enemy: bool,
    scene: bpy.types.Scene,
    progress: Progress | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """Rest-stance and per-clip lines for a four-legged rig or a hopper."""
    rig_lines = [
        f"WARN in the rest pose the {end} feet stand {r:.1f} times as wide apart as the "
        f"{'hips' if end == 'hind' else 'shoulders'}: every clip starts from a straddle. "
        "Move the feet under the body in the rig."
        for end, r in animal.rest_widths.items()
        if r > 1.25
    ]
    strike = scene.gaitkeeper.every_clip_strikes
    clips = {}
    for act in reported(actions, progress):
        _, verdict = creature.measure_clip(
            arm, act, animal.legs, animal.pelvis, animal.hopper, animal.rest_widths, scene, strike, enemy=enemy
        )
        clips[act.name] = verdict
    return rig_lines, clips


def run_check(
    arm: bpy.types.Object,
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    progress: Progress | None = None,
) -> CheckResult:
    """Check the armature's clips, telling `progress` as each clip starts. Changes nothing: the current clip
    and frame are put back."""
    if not arm.data.bones:
        return CheckResult(armature=arm.name, kind="person", rig=[NO_BONES], clips={})
    settings = scene.gaitkeeper
    kind, animal = body_setup(arm, scene, view_layer)
    actions = clips_to_check(arm, settings.current_only)
    enemy = settings.attacks_for == "ENEMY"
    with kept_transforms(scene, view_layer), kept_frame(scene), kept_action(arm):
        if kind == "person":
            rig_lines, clips = check_person(arm, actions, enemy, scene, view_layer, progress)
        elif animal is None:
            rig_lines, clips = ["FAIL no legs found: no bone chains reach the floor in the rest pose."], {}
        else:
            rig_lines, clips = check_animal(arm, actions, animal, enemy, scene, progress)
    return CheckResult(armature=arm.name, kind=kind, rig=rig_lines, clips=clips)


def fix_current_clip(
    arm: bpy.types.Object,
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    progress: Progress | None = None,
) -> tuple[bpy.types.Action | None, dict]:
    """Fix the current clip into a copy and make the copy current, telling `progress` as it starts.
    Returns (copy or None, fix report)."""
    act = arm.animation_data.action
    if not animates(act, arm):
        return None, {"changes": [NOTHING_TO_MEND], "verdict": []}
    animal = animal_rig(arm, scene, view_layer)
    if animal is None and checks.rig_report(arm, rig.role_map(arm))["missing"]:
        return None, {"changes": [], "verdict": [BONES_NOT_FOUND]}
    if progress is not None:
        progress(0, 1, act.name)
    with kept_transforms(scene, view_layer, skip=arm), kept_frame(scene):
        new, rep = fixed_copy(arm, act, animal, scene, view_layer)
    if new is not None:
        rig.set_action(arm, new)
    return new, rep


def fixed_copy(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    animal: AnimalRig | None,
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
) -> tuple[bpy.types.Action | None, dict]:
    """The animal fix or the person fix of `act`, as the scene's settings ask."""
    settings = scene.gaitkeeper
    if animal is not None:
        return creature_fix.fix_creature(
            arm,
            act,
            animal.legs,
            animal.pelvis,
            animal.hopper,
            animal.rest_widths,
            scene,
            view_layer,
            settings.every_clip_strikes,
        )
    root = None if settings.root_motion == "LEAVE" else settings.root_motion.lower()
    label = judged_label(arm, act, settings.attacks_for == "ENEMY")
    cyclic = checks.clip_loops(arm, act, scene, label)
    return edit.fix_clip(arm, act, rig.role_map(arm), scene_fps(scene), cyclic, scene, view_layer, root, label=label)


def fix_report_text(new: bpy.types.Action | None, rep: dict) -> str:
    """The report written after Fix: what changed and how the copy now checks."""
    lines = [f"GaitKeeper fix: {new.name if new else 'refused'}", ""]
    lines += [f"  change: {c}" for c in rep.get("changes", [])]
    lines += [f"  {v}" for v in rep["verdict"]]
    return "\n".join(lines)
