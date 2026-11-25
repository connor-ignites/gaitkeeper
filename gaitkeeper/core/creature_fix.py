# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: fixing animal clips (Blender).

The animal checks judge legs by their line, timing and weight, not by sliding paws (paws roll and
pivot, and a sliding-paw measure flagged 46 of 113 good clips in a commercial dog pack), so the fix mends what the
checks flag: legs that bow out sideways are brought back into line ("legs in line"), joint by joint,
without moving the planted foot or the move itself.
"""

from __future__ import annotations

import math
import re

import bpy
from mathutils import Matrix, Vector

from . import creature
from . import legs as leg_checks
from .fix_guard import REFUSED_WORSE, all_or_nothing
from .rig import body_axes, clip_range, key_rotation, set_action


def best_turn(axis: Vector, pivot: Vector, joint: Vector, side: Vector, fwd: Vector, keep: float = 0.0) -> float:
    """The turn (radians) about `axis` (through `pivot`) that brings `joint` closest to the plane
    whose normal is `side` (or to `keep` of its old distance from it: a little natural give),
    keeping it on the same side of the axis, front to back."""
    off = (joint - pivot) - axis * (joint - pivot).dot(axis)
    if off.length < 1e-6:
        return 0.0
    sign0 = off.dot(fwd)
    goal = keep * off.dot(side)
    best, best_cost = 0.0, (off.dot(side) - goal) ** 2
    for k in range(-180, 181):
        th = math.radians(k * 0.5)
        t = Matrix.Rotation(th, 3, axis) @ off
        if sign0 * t.dot(fwd) < -1e-6:
            continue
        cost = (t.dot(side) - goal) ** 2
        if cost < best_cost - 1e-12:
            best, best_cost = th, cost
    return best


def legs_in_line(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    legs: dict[str, list[str]],
    fwd: Vector,
    which: tuple[str, ...],
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    keep: float = 0.0,
) -> bpy.types.Action:
    """Joint by joint, top down: turn the bone above each middle joint about the line from its top
    to the joint below, so that joint swings into the leg's side plane and the joint below stays
    put; the bone below then gets its world pose back, so nothing further down moves."""
    new = act.copy()
    new.name = act.name.split("|")[-1] + "_inline"
    set_action(arm, new)
    mw = arm.matrix_world
    inv = mw.inverted()
    a, b = clip_range(new)
    for f in range(a, b + 1):
        scene.frame_set(f)
        for key, names in legs.items():
            if not key.startswith(which):
                continue
            pbs = [arm.pose.bones[n] for n in names]
            top, end = mw @ pbs[0].head, mw @ pbs[-1].head
            line = end - top
            side = line.cross(fwd)
            if side.length < 1e-6:
                continue
            side.normalize()
            touched = set()
            for k in range(1, len(pbs) - 1):
                pivot, joint, below = (mw @ pbs[k - 1].head, mw @ pbs[k].head, mw @ pbs[k + 1].head)
                axis = below - pivot
                if axis.length < 1e-6:
                    continue
                axis.normalize()
                th = best_turn(axis, pivot, joint, side, fwd, keep)
                if abs(th) < 1e-4:
                    continue
                hold = mw @ pbs[k + 1].matrix
                turn = Matrix.Translation(pivot) @ Matrix.Rotation(th, 4, axis) @ Matrix.Translation(-pivot)
                pbs[k - 1].matrix = inv @ (turn @ (mw @ pbs[k - 1].matrix))
                view_layer.update()
                pbs[k + 1].matrix = inv @ hold
                view_layer.update()
                touched |= {k - 1, k, k + 1}
            for k in sorted(touched):
                key_rotation(pbs[k], f)
    return new


def _words(line: str) -> str:
    return re.sub(r"[-+]?\d+(\.\d+)?", "#", line)


def fix_creature(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    animal: creature.AnimalRig,
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    strike: bool = False,
) -> tuple[bpy.types.Action | None, dict]:
    """The animal fix on a COPY: bowed legs brought into line. Returns (copy or None, report). None when
    nothing needs it, or when the fix made anything worse (the copy is then deleted). If anything fails
    midway, the copy is removed and the original clip made current again before the error is raised."""
    legs = animal.legs
    with all_or_nothing(arm):
        m0, v0 = creature.measure_clip(arm, act, animal, scene, strike)
        bowed = [
            k
            for k, v in m0["legs"].items()
            if v["bow_share"] > leg_checks.BOW_WARN.get(k.split("_")[0], leg_checks.BOW_WARN_DEFAULT)
        ]
        report: dict = {"before": v0, "changes": []}
        if not bowed:
            report["verdict"] = v0
            report["changes"] = [
                "nothing to mend: no leg bows out of line (the animal checks' other notes are "
                "about timing and weight, which need an animator)"
            ]
            set_action(arm, act)
            return None, report
        fwd = body_axes(arm, creature.leg_roles(arm, legs, animal.pelvis))[0]
        new = legs_in_line(arm, act, legs, fwd, tuple(bowed), scene, view_layer)
        new.name = f"{act.name.split('|')[-1]}_fixed"
        m1, v1 = creature.measure_clip(arm, new, animal, scene, strike)
        for k in bowed:
            side = "left" if k.endswith("_l") else "right"
            report["changes"].append(
                f"{side} {k.split('_')[0]} leg brought into line (bow {m0['legs'][k]['bow_cm']:.0f} cm "
                f"-> {m1['legs'][k]['bow_cm']:.1f} cm)"
            )
        report["verdict"] = v1
        was = {_words(x) for x in v0}
        report["worse"] = [x for x in v1 if x.startswith(("FAIL", "WARN")) and _words(x) not in was]
        if any(x.startswith("FAIL") for x in report["worse"]):
            report["verdict"] = [*v1, REFUSED_WORSE]
            bpy.data.actions.remove(new)
            set_action(arm, act)
            return None, report
        new.use_fake_user = True
        set_action(arm, new)
        return new, report
