# SPDX-License-Identifier: GPL-3.0-or-later
"""Glue between the panel and the checks: decides what kind of body a rig is, runs the checks or the fix,
and leaves the scene as it found it."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple

import bpy

from .core import body as body_checks
from .core import checks, creature, creature_fix, edit, rig, skin
from .core.report import CheckResult

REPORT_NAME = "GaitKeeper report"
POSE_CLIP = re.compile(r"(^|[^a-z0-9])[ta][ _-]?pose([^a-z0-9]|$)")  # T-pose and A-pose clips, never checked
TAIL = re.compile(r"(^|[^a-z])tail")  # "Tail_01", "tail.L"; not "ponytail"
BONE_PATH = re.compile(r'pose\.bones\["([^"]+)"\]')


class AnimalRig(NamedTuple):
    """What the animal checks need to know about a rig."""

    legs: dict[str, list[str]]
    pelvis: str
    hopper: bool
    rest_widths: dict[str, float]


def scene_fps(scene: bpy.types.Scene) -> float:
    return scene.render.fps / scene.render.fps_base


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


def body_kind(arm: bpy.types.Object, legs: dict, settings) -> tuple[bool, bool]:
    """(animal, hopper). Auto: four legs, or two legs and a tail, is an animal; two legs and a tail hop."""
    tail = any(TAIL.search(b.name.lower()) for b in arm.data.bones)
    fore = any(k.startswith("fore") for k in legs)
    animal, hopper = fore or tail, tail and not fore and len(legs) == 2
    if settings.body != "AUTO":
        animal = settings.body == "CREATURE"
    if settings.hopper != "AUTO":
        hopper = settings.hopper == "YES"
    return animal, hopper


def pelvis_bone(arm: bpy.types.Object, legs: dict) -> str:
    """The hips bone if the naming says so, else the parent of the first leg's top bone."""
    hips = rig.role_map(arm).get("hips")
    if hips is not None:
        return hips
    top = arm.pose.bones[next(iter(legs.values()))[0]]
    return top.parent.name if top.parent else top.name


def animal_rig(arm: bpy.types.Object, settings) -> AnimalRig | None:
    """The animal setup when the settings make this rig an animal with legs, else None."""
    legs = creature.find_legs(arm)
    animal, hopper = body_kind(arm, legs, settings)
    if not animal or not legs:
        return None
    return AnimalRig(legs, pelvis_bone(arm, legs), hopper, creature.rest_width(arm, legs))


def action_fcurves(act: bpy.types.Action) -> list[bpy.types.FCurve]:
    """Every F-curve in the action: the legacy list (before Blender 5.0) and the layered channelbags (4.4+)."""
    curves = list(getattr(act, "fcurves", None) or [])
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                curves += list(bag.fcurves)
    return curves


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


def check_person(arm: bpy.types.Object, actions: list, enemy: bool) -> tuple[list[str], dict[str, list[str]]]:
    """Skeleton, skin and per-clip lines for a two-legged, two-armed rig."""
    roles = rig.role_map(arm)
    fps = scene_fps(bpy.context.scene)
    saved_file = bpy.data.filepath.lower().endswith(".blend")
    rig_lines = checks.rig_verdicts(checks.rig_report(arm, roles), None)
    rig_lines += skin.skin_verdicts(skin.skin_report(arm, roles), saved_file)
    clips = {}
    for act in actions:
        label = judged_label(arm, act, enemy)
        measured = checks.measure(rig.sample(arm, act, roles), fps, "loop" in act.name.lower(), arm, label)
        clips[act.name] = checks.verdicts(measured, None)
    return body_checks.misread_verdicts(clips) + rig_lines, clips


def check_animal(
    arm: bpy.types.Object, actions: list, animal: AnimalRig, strike: bool, enemy: bool
) -> tuple[list[str], dict[str, list[str]]]:
    """Rest-stance and per-clip lines for a four-legged rig or a hopper."""
    rig_lines = [
        f"WARN in the rest pose the {end} feet stand {r:.1f} times as wide apart as the "
        f"{'hips' if end == 'hind' else 'shoulders'}: every clip starts from a straddle. "
        "Move the feet under the body in the rig."
        for end, r in animal.rest_widths.items()
        if r > 1.25
    ]
    clips = {}
    for act in actions:
        _, verdict = creature.measure_clip(
            arm, act, animal.legs, animal.pelvis, animal.hopper, animal.rest_widths, strike, enemy=enemy
        )
        clips[act.name] = verdict
    return rig_lines, clips


def run_check(arm: bpy.types.Object, settings) -> CheckResult:
    """Check the armature's clips. Changes nothing: the current clip and frame are put back."""
    legs = creature.find_legs(arm)
    animal, hopper = body_kind(arm, legs, settings)
    kind = ("hopper" if hopper else "animal") if animal else "person"
    actions = clips_to_check(arm, settings.current_only)
    enemy = settings.attacks_for == "ENEMY"
    with kept_frame(bpy.context.scene), kept_action(arm):
        if not animal:
            rig_lines, clips = check_person(arm, actions, enemy)
        elif not legs:
            rig_lines, clips = ["FAIL no legs found: no bone chains reach the floor in the rest pose."], {}
        else:
            found = AnimalRig(legs, pelvis_bone(arm, legs), hopper, creature.rest_width(arm, legs))
            rig_lines, clips = check_animal(arm, actions, found, settings.every_clip_strikes, enemy)
    return CheckResult(armature=arm.name, kind=kind, rig=rig_lines, clips=clips)


def fix_current_clip(arm: bpy.types.Object, settings) -> tuple[bpy.types.Action | None, dict]:
    """Fix the current clip into a copy and make the copy current. Returns (copy or None, fix report)."""
    act = arm.animation_data.action
    scene = bpy.context.scene
    animal = animal_rig(arm, settings)
    with kept_frame(scene):
        if animal is not None:
            new, rep = creature_fix.fix_creature(
                arm, act, animal.legs, animal.pelvis, animal.hopper, animal.rest_widths, settings.every_clip_strikes
            )
        else:
            root = None if settings.root_motion == "LEAVE" else settings.root_motion.lower()
            label = judged_label(arm, act, settings.attacks_for == "ENEMY")
            fps = scene_fps(scene)
            new, rep = edit.fix_clip(arm, act, rig.role_map(arm), fps, "loop" in act.name.lower(), root, label=label)
    if new is not None:
        rig.set_action(arm, new)
    return new, rep


def fix_report_text(new: bpy.types.Action | None, rep: dict) -> str:
    """The report written after Fix: what changed and how the copy now checks."""
    lines = [f"GaitKeeper fix: {new.name if new else 'refused'}", ""]
    lines += [f"  change: {c}" for c in rep.get("changes", [])]
    lines += [f"  {v}" for v in rep["verdict"]]
    return "\n".join(lines)
