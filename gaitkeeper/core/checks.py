# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: the measurements and plain-English verdicts. Deterministic; no AI model."""

from __future__ import annotations

import math

import bpy

from . import body, body_rules, cycle, motion_math, names, reactions
from .fix import MAX_FOOT_NUDGE_M
from .rig import (
    Sample,
    body_axes,
    clip_label,
    clip_range,
    contact_flags,
    in_metres,
    metres_per_unit,
    rest_space,
    set_action,
)

TRAVEL_M = 0.3  # hips (or root) this far apart on the first and last frames: the clip travels
ROOT_STILL_M = 0.05  # a root bone that moves less than this over the clip stays put
OFF_GROUND_M = 0.15  # feet that never come lower than this never reach the floor (swimming, hanging, flying)
STILL_SPEED_M_S = 0.15  # feet whose in-place ground speed is under this stand still
SINK_FAIL_M = 0.015  # a fix or edit may not bring the feet lower than the original by more than this
THROUGH_FLOOR_M = 0.02  # a joint this far below the floor goes through it
SLIDE_WARN_M_S = 0.2  # a planted foot sliding faster than this is skating
SLIDE_EDIT_MIN_M_S = 0.12  # an edit is allowed this much slide, or half as much again as the original had
POP_RATIO = 3.0  # a one-frame turn this many times its neighbours' is a pop...
POP_FLOOR_DEG = 20.0  # ...if it is also bigger than this
POPS_KEPT = 5  # frames listed per popping bone
HEIGHT_RANGE_M = (0.3, 5.0)  # a skeleton outside this height probably came in at the wrong scale


def scene_fps(scene: bpy.types.Scene) -> float:
    """The scene's frames per second."""
    return scene.render.fps / scene.render.fps_base


def basis_rotations(frame: dict[str, tuple]) -> cycle.Pose:
    """One sampled frame's local rotation per bone (a Sample basis frame holds (loc, quat, scale))."""
    return {bone: lqs[1] for bone, lqs in frame.items()}


def pose_rotations(arm: bpy.types.Object) -> cycle.Pose:
    """Every pose bone's local rotation as it stands now, as a quaternion whatever its rotation mode."""
    return {pb.name: tuple(pb.matrix_basis.to_quaternion()) for pb in arm.pose.bones}


def clip_loops(arm: bpy.types.Object, act: bpy.types.Action, scene: bpy.types.Scene, name: str) -> bool:
    """Whether the clip loops by the shared rule (cycle.loops): its name, or its first and last poses.
    Plays the clip's first and last frames on `scene` and leaves the clip current."""
    set_action(arm, act)
    first, last = clip_range(act)
    scene.frame_set(first)
    start = pose_rotations(arm)
    scene.frame_set(last)
    return cycle.loops(name, start, pose_rotations(arm), last - first + 1)


def hips_travel(s: Sample) -> bool:
    """The hips end the clip more than TRAVEL_M from where they began (in the sample's units)."""
    return "hips" in s.world[0] and motion_math.dist2d(s.world[0]["hips"], s.world[-1]["hips"]) > TRAVEL_M


def measure(s: Sample, fps: float, cyclic: bool, arm: bpy.types.Object, name: str = "") -> dict:
    """Every measurement of one sampled clip, in metres: feet, floor, loop seam, pops, root motion, body
    and balance. `verdicts` turns it into plain-English lines."""
    name = clip_label(arm, name)  # "root|Scene" says nothing: read the file's name too
    s = in_metres(s)  # every distance below is in metres
    n = len(s.world)
    out: dict = {"frames": n, "seconds": round((n - 1) / fps, 3), "feet": {}, "name": name, "fps": fps}
    # a clip that travels (root motion) can't wrap its planted feet across the loop seam
    travels = hips_travel(s)
    flags_by_side, lowest_sole = _measure_feet(s, fps, cyclic and not travels, out["feet"])
    out["lowest_point_m"] = round(lowest_sole, 4) if lowest_sole < math.inf else None
    if lowest_sole < math.inf and lowest_sole > OFF_GROUND_M:
        out["feet_off_ground"] = True
    if names.meant_off_ground(name):
        out["feet_off_ground"] = True
    if cyclic and n > 2:  # loop seam: biggest bone turn between first and last frame
        out["loop_seam_deg"] = round(cycle.seam_deg(basis_rotations(s.basis[0]), basis_rotations(s.basis[-1])), 2)
    out["travels"] = travels
    out.update(_lowest_joint(s))
    out["pops"] = _pops(s)
    out.update(_root_motion(s))
    lengths = {pb.name: max(0.01, pb.length) for pb in arm.pose.bones if pb.parent is not None}
    # balance is only meaningful when standing still: no ground speed
    still = all(v["ground_speed_m_s"] < STILL_SPEED_M_S for v in out["feet"].values()) if out["feet"] else False
    standing = not names.not_standing(name) and not out.get("feet_off_ground") and not travels
    out["body"] = body.measure_body(
        s,
        fps,
        getattr(s, "roles", {}),
        flags_by_side,
        lengths,
        name,
        travels,
        bool(out.get("feet_off_ground")),
        cyclic,
        still and standing,
    )
    if still and standing and len(flags_by_side) == 2:
        out["balance_worst_m"] = round(_balance_worst(s, list(flags_by_side.values()), lengths), 3)
    return out


def _measure_feet(s: Sample, fps: float, cyclic_feet: bool, feet: dict) -> tuple[dict[str, list[bool]], float]:
    """Fill `feet` with each foot's planted frames, ground speed, worst slide and lowest point. Returns the
    planted flags per side and the lowest the soles go."""
    lowest_sole = math.inf
    flags_by_side: dict[str, list[bool]] = {}
    for side in "lr":
        key = f"ball_{side}" if f"ball_{side}" in s.world[0] else f"ankle_{side}"
        if key not in s.world[0]:
            continue
        pos = [w[key] for w in s.world]
        sole = [min(w.get(f"toe_{side}", w[key])[2], w[key][2]) for w in s.world]
        lowest_sole = min(lowest_sole, min(sole))
        flags = contact_flags(s, side, fps, cyclic_feet)
        flags_by_side[side] = flags
        tm = motion_math.treadmill_velocity(pos, flags, fps)
        slides = motion_math.slide_per_contact(pos, flags, fps, cyclic_feet, tm)
        feet[side] = {
            "planted_frames": sum(flags),
            "ground_speed_m_s": round(math.hypot(tm[0], tm[1]), 3),
            "worst_slide_m_s": round(max(slides), 3) if slides else 0.0,
            "lowest_point_m": round(min(sole), 4),
        }
    return flags_by_side, lowest_sole


def _lowest_joint(s: Sample) -> dict:
    """The lowest point of the knees, hips, chest and head (only feet should touch the floor in most clips)."""
    joints = [k for k in s.world[0] if k.startswith("joint:")]
    if not joints:
        return {}
    low = min((w[k][2], k[6:]) for w in s.world for k in joints)
    return {"lowest_joint_m": round(low[0], 4), "lowest_joint": low[1]}


def _pops(s: Sample) -> dict[str, list[int]]:
    """Bones that snap to a new angle between two frames, with the first few frames where they do."""
    n = len(s.world_q)
    pop_bones = {}
    for bone in s.world_q[0]:
        if names.small_bone(bone):
            continue
        ang = [motion_math.q_angle_deg(s.world_q[i][bone], s.world_q[i + 1][bone]) for i in range(n - 1)]
        skip = [motion_math.q_angle_deg(s.world_q[i][bone], s.world_q[i + 2][bone]) for i in range(n - 2)]
        p = motion_math.pops(ang, ratio=POP_RATIO, floor_deg=POP_FLOOR_DEG, skip_angles=skip)
        if p:
            pop_bones[bone] = p[:POPS_KEPT]
    return pop_bones


def _root_motion(s: Sample) -> dict:
    """Does the body travel, and does the root bone carry it (and its sway)?"""
    if "hips" not in s.world[0]:
        return {}
    h0, h1 = s.world[0]["hips"], s.world[-1]["hips"]
    out = {"hips_travel_m": round(motion_math.dist2d(h0, h1), 3)}
    if "rootbone" in s.world[0] and s.world[0]["rootbone"] != s.world[0]["hips"]:
        r0, r1 = s.world[0]["rootbone"], s.world[-1]["rootbone"]
        out["root_travel_m"] = round(motion_math.dist2d(r0, r1), 3)
        if out["root_travel_m"] > TRAVEL_M:
            rp = [w["rootbone"] for w in s.world]
            out["root_sway_cm"] = round(reactions.side_sway_cm(rp, r0, r1), 1)
            out["hips_sway_cm"] = round(reactions.side_sway_cm([w["hips"] for w in s.world], r0, r1), 1)
    return out


def _balance_worst(s: Sample, planted: list[list[bool]], lengths: dict[str, float]) -> float:
    """How far (m) the centre of mass (by bone length) gets outside the planted feet while standing."""
    worst = 0.0
    for i, w in enumerate(s.world):
        if not (planted[0][i] or planted[1][i]):
            continue
        c = motion_math.com([(w["com:" + nm], lengths[nm]) for nm in lengths])
        pts = []
        for k, side in enumerate("lr"):
            if planted[k][i]:
                pts += [w[key] for key in (f"ankle_{side}", f"ball_{side}", f"toe_{side}") if key in w]
        if pts:
            worst = max(worst, motion_math.outside_support(c, pts))
    return worst


def verdicts(before: dict, after: dict | None, fixing: bool = False) -> list[str]:
    """Plain-English warnings, comparing the result with the original where it helps."""
    r = after or before
    msgs = _floor_verdicts(before, after) + _slide_verdicts(before, after, fixing)
    if r.get("loop_seam_deg", 0) > cycle.SEAM_WARN_DEG:
        msgs.append(
            f"WARN the loop doesn't join up: a bone jumps {r['loop_seam_deg']:.0f} degrees from the last frame "
            "back to the first, so it hitches every time it loops. Make the last pose match the first."
        )
    msgs += _pop_verdicts(before, after, fixing)
    limit = body_rules.OFF_BALANCE_WARN_M
    balance = r.get("balance_worst_m", 0)
    one_foot = r.get("body", {}).get("one_foot_off_balance_m", 0)
    said_by_body = one_foot > limit and one_foot >= balance - 0.001  # the one-foot line already says it
    if balance > limit and not said_by_body:
        msgs.append(
            f"WARN off balance: the body's weight sits {balance * 100:.0f} cm outside the feet "
            "while it stands, so it would tip over. Move the hips back over the feet."
        )
    msgs += _root_verdicts(before, after)
    if "body" in r:
        msgs += body.body_verdicts(
            before.get("body", {}),
            after.get("body") if after is not None else None,
            r.get("name", ""),
            bool(r.get("feet_off_ground")),
            r.get("fps", 30.0),
        )
    if not msgs:
        msgs.append("PASS no sinking, skating, seam jumps, pops, impossible joints or physics problems found.")
    return msgs


def _floor_verdicts(before: dict, after: dict | None) -> list[str]:
    """Feet sinking below the original, and joints going through the floor."""
    r = after or before
    msgs = []
    if after is not None and before.get("lowest_point_m") is not None and after.get("lowest_point_m") is not None:
        sink = before["lowest_point_m"] - after["lowest_point_m"]
        if sink > SINK_FAIL_M:
            msgs.append(f"FAIL feet go {sink * 100:.1f} cm lower than the original: they sink into the floor.")
    if r.get("lowest_joint_m") is not None and r["lowest_joint_m"] < -THROUGH_FLOOR_M:
        was = before.get("lowest_joint_m", 0.0) if after is not None else 0.0
        if after is None or r["lowest_joint_m"] < was - THROUGH_FLOOR_M:
            msgs.append(
                f"FAIL the {r['lowest_joint'].split('_')[0]} goes {-r['lowest_joint_m'] * 100:.0f} cm "
                "through the floor."
            )
    return msgs


def _slide_verdicts(before: dict, after: dict | None, fixing: bool) -> list[str]:
    """Planted feet that skate. A fix is held to the plain limit; an edit to what the original already did."""
    r = after or before
    msgs = []
    for side, v in ({} if r.get("feet_off_ground") else r["feet"]).items():
        base = before["feet"].get(side, {}).get("worst_slide_m_s", 0.0) if after is not None else 0.0
        limit = SLIDE_WARN_M_S if after is None or fixing else max(SLIDE_EDIT_MIN_M_S, base * 1.5 + 0.03)
        if v["worst_slide_m_s"] > limit:
            was = (
                f" (was {base:.2f}; the fixer only nudges feet up to {MAX_FOOT_NUDGE_M * 100:.0f} cm)"
                if fixing and base > v["worst_slide_m_s"]
                else ""
            )
            msgs.append(f"WARN {side} foot slides {v['worst_slide_m_s']:.2f} m/s while planted (skating){was}.")
    return msgs


def _pop_verdicts(before: dict, after: dict | None, fixing: bool) -> list[str]:
    """A check or a fix is judged on every pop in the clip it judges, so a fix can't pass by leaving the
    clip's own pops in place; an edit only on the pops it added."""
    r = after or before
    new_pops = set(r["pops"]) - (set(before["pops"]) if after is not None and not fixing else set())
    if not new_pops:
        return []
    where = ", ".join(f"{b} (frame {r['pops'][b][0]})" if r["pops"][b] else b for b in sorted(new_pops)[:6])
    return [
        f"WARN sudden jumps between two frames (pops) in: {where}. A bone snaps to a new angle instead "
        "of turning over a few frames; smooth the keys there."
    ]


def _root_verdicts(before: dict, after: dict | None) -> list[str]:
    """Travel the root bone doesn't carry, and a root that sways with the hips."""
    r = after or before
    msgs = []
    if r.get("hips_travel_m", 0) > TRAVEL_M and r.get("root_travel_m", 0) < ROOT_STILL_M:
        msgs.append(
            f"WARN the body travels {r['hips_travel_m']:.2f} m but the root bone stays put: no root motion. "
            "In a game the character's collider stays behind while the body walks off. Fix it with Root "
            "motion set to 'Move onto root', or 'Walk on the spot' if the game moves the character itself."
        )
    if "root_sway_cm" in r:
        sway = reactions.root_sway_verdicts(r["root_sway_cm"], r.get("hips_sway_cm", 0.0))
        was_swaying = reactions.root_sway_verdicts(before.get("root_sway_cm", 0.0), before.get("hips_sway_cm", 0.0))
        if after is None or not was_swaying:
            msgs += sway
    return msgs


ROLE_WORDS = {
    "hips": "hips",
    "spine1": "spine",
    "spine2": "chest",
    "spine3": "upper chest",
    "neck": "neck",
    "head": "head",
    "thigh": "thigh",
    "calf": "shin",
    "foot": "foot",
    "toe": "toes",
    "upperarm": "upper arm",
    "lowerarm": "forearm",
    "hand": "hand",
}


def role_words(role: str) -> str:
    """A bone role in words: thigh_l -> left thigh."""
    base, _, side = role.partition("_")
    word = ROLE_WORDS.get(base, base)
    return f"{'left' if side == 'l' else 'right'} {word}" if side in ("l", "r") else word


REQUIRED = [
    "hips",
    "spine1",
    "head",
    "thigh_l",
    "calf_l",
    "foot_l",
    "thigh_r",
    "calf_r",
    "foot_r",
    "upperarm_l",
    "lowerarm_l",
    "upperarm_r",
    "lowerarm_r",
]


def rig_report(arm: bpy.types.Object, roles: dict[str, str]) -> dict:
    """Checks on the skeleton itself: bone map, left/right, size, root bone. The rest pose is read as the
    current clip shows it (a top bone the clip holds still is folded in: rig.rest_space)."""
    mw = rest_space(arm, roles.get("hips"))
    bones = arm.data.bones
    out: dict = {"missing": [r for r in REQUIRED if r not in roles]}
    # left/right: the left thigh must sit on the character's left (feet point forward)
    feet = any(roles.get(f"foot_{side}") and roles.get(f"toe_{side}") for side in "lr")
    if feet and roles.get("thigh_l") and roles.get("thigh_r"):
        right = body_axes(arm, roles)[1]
        dl = (mw @ bones[roles["thigh_l"]].head_local).dot(right)
        dr = (mw @ bones[roles["thigh_r"]].head_local).dot(right)
        out["sides_swapped"] = bool(dl > dr)
    zs = [(mw @ b.head_local).z for b in bones] + [(mw @ b.tail_local).z for b in bones]
    out["height_m"] = round((max(zs) - min(zs)) * metres_per_unit(arm, roles.get("hips")), 3)
    out["top_bones"] = [b.name for b in bones if b.parent is None]
    hips = roles.get("hips")
    out["root_bone"] = bool(hips and bones[hips].parent is not None)
    return out


def rig_verdicts(rig: dict) -> list[str]:
    """Plain-English lines about the skeleton (rig_report): missing or swapped bones, scale, top and root bones."""
    msgs = []
    if rig["missing"]:
        msgs.append(
            "FAIL GaitKeeper can't tell which bones are the "
            + ", ".join(role_words(r) for r in rig["missing"])
            + ". Give them common names (for example pelvis, thigh_l, calf_l, foot_l, or Mixamo's names) "
            "or choose Body: Animal if this isn't a person."
        )
    if rig.get("sides_swapped"):
        msgs.append("FAIL left and right legs are swapped in the bone names.")
    h = rig.get("height_m", 1.8)
    if not HEIGHT_RANGE_M[0] <= h <= HEIGHT_RANGE_M[1]:
        msgs.append(
            f"WARN the skeleton is {h:.2f} m tall: probably a units problem (it came in 100 times too big "
            "or too small). Check the scale on export and import."
        )
    if len(rig.get("top_bones", [])) > 1:
        msgs.append(
            "WARN more than one top bone (" + ", ".join(rig["top_bones"][:4]) + "): game engines want one "
            "bone at the top that everything hangs from. Parent the others under it."
        )
    if not rig.get("root_bone"):
        msgs.append(
            "WARN no root bone above the hips: there is nowhere to store the walk's travel (root motion) "
            "for a game engine. Add a root bone at the feet, between them, as the hips' parent."
        )
    return msgs
