# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: the measurements and plain-English verdicts. Deterministic; no AI model."""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

from . import body as body_checks
from . import motion_math as mm
from . import reactions as R
from .rig import Sample, clip_label, contact_flags, in_metres, metres_per_unit, rest_space

SMALL_BONES = ("leaf", "index", "middle", "ring", "pinky", "thumb", "finger", "toe_end", "twist")
NOT_STANDING = (
    "sit",
    "driv",
    "swim",
    "lying",
    "lie_",
    "death",
    "die",
    "roll",
    "kneel",
    "fall",
    "ragdoll",
    "push",
    "pull",
    "lean",
    "climb",
    "hang",
)  # pushing or leaning: the object takes weight


def measure(s: Sample, fps: float, cyclic: bool, arm: bpy.types.Object, name: str = "") -> dict:
    name = clip_label(arm, name)  # "root|Scene" says nothing: read the file's name too
    s = in_metres(s)  # every distance below is in metres
    n = len(s.world)
    out: dict = {"frames": n, "seconds": round((n - 1) / fps, 3), "feet": {}, "name": name, "fps": fps}
    lowest_sole = math.inf
    planted_any = []
    flags_by_side: dict[str, list[bool]] = {}
    # a clip that travels (root motion) can't wrap its planted feet across the loop seam
    travels = "hips" in s.world[0] and mm.dist2d(s.world[0]["hips"], s.world[-1]["hips"]) > 0.3
    cyclic_feet = cyclic and not travels
    for side in "lr":
        key = f"ball_{side}" if f"ball_{side}" in s.world[0] else f"ankle_{side}"
        if key not in s.world[0]:
            continue
        pos = [w[key] for w in s.world]
        sole = [min(w.get(f"toe_{side}", w[key])[2], w[key][2]) for w in s.world]
        lowest_sole = min(lowest_sole, min(sole))
        flags = contact_flags(s, side, fps, cyclic_feet)
        planted_any.append(flags)
        flags_by_side[side] = flags
        tm = mm.treadmill_velocity(pos, flags, fps)
        slides = mm.slide_per_contact(pos, flags, fps, cyclic_feet, tm)
        out["feet"][side] = {
            "planted_frames": sum(flags),
            "ground_speed_m_s": round(math.hypot(tm[0], tm[1]), 3),
            "worst_slide_m_s": round(max(slides), 3) if slides else 0.0,
            "lowest_point_m": round(min(sole), 4),
        }
    out["lowest_point_m"] = round(lowest_sole, 4) if lowest_sole < math.inf else None
    if lowest_sole < math.inf and lowest_sole > 0.15:  # feet never reach the floor: swimming, hanging, flying
        out["feet_off_ground"] = True
    if any(k in name.lower() for k in ("swim", "roll", "death", "die", "fall", "ragdoll", "climb")):
        out["feet_off_ground"] = True  # feet aren't meant to stay planted in these
    # loop seam: biggest bone turn between first and last frame
    if cyclic and n > 2:
        a, b = s.basis[0], s.basis[-1]
        out["loop_seam_deg"] = round(max(mm.q_angle_deg(a[k][1], b[k][1]) for k in a), 2)
    out["travels"] = travels
    # knees, hips, chest, head: their lowest point (only feet should touch the floor in most clips)
    joints = [k for k in s.world[0] if k.startswith("joint:")]
    if joints:
        low = min((w[k][2], k[6:]) for w in s.world for k in joints)
        out["lowest_joint_m"] = round(low[0], 4)
        out["lowest_joint"] = low[1]
    # pops
    pop_bones = {}
    for bone in s.world_q[0]:
        if any(k in bone.lower() for k in SMALL_BONES):
            continue
        ang = [mm.q_angle_deg(s.world_q[i][bone], s.world_q[i + 1][bone]) for i in range(n - 1)]
        skip = [mm.q_angle_deg(s.world_q[i][bone], s.world_q[i + 2][bone]) for i in range(n - 2)]
        p = mm.pops(ang, ratio=3.0, floor_deg=20.0, skip_angles=skip)
        if p:
            pop_bones[bone] = p[:5]
    out["pops"] = pop_bones
    # root motion: does the body travel, and does the root bone carry it?
    if "hips" in s.world[0]:
        h0, h1 = s.world[0]["hips"], s.world[-1]["hips"]
        out["hips_travel_m"] = round(mm.dist2d(h0, h1), 3)
        if "rootbone" in s.world[0] and s.world[0]["rootbone"] != s.world[0]["hips"]:
            r0, r1 = s.world[0]["rootbone"], s.world[-1]["rootbone"]
            out["root_travel_m"] = round(mm.dist2d(r0, r1), 3)
            if out["root_travel_m"] > 0.3:
                rp = [w["rootbone"] for w in s.world]
                out["root_sway_cm"] = round(R.side_sway_cm(rp, r0, r1), 1)
                out["hips_sway_cm"] = round(R.side_sway_cm([w["hips"] for w in s.world], r0, r1), 1)
    # anatomy, balance on one foot, gait, physics, attacks (body.py; the rules are in BODY.md)
    lengths = {pb.name: max(0.01, pb.length) for pb in arm.pose.bones if pb.parent is not None}
    # balance (only meaningful when standing still: no ground speed)
    still = all(v["ground_speed_m_s"] < 0.15 for v in out["feet"].values()) if out["feet"] else False
    standing = not any(k in name.lower() for k in NOT_STANDING) and not out.get("feet_off_ground") and not travels
    out["body"] = body_checks.measure_body(
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
    if still and standing and len(planted_any) == 2:
        # mass by bone length; the root bone (floor to hips) carries no mass
        worst = 0.0
        for i, w in enumerate(s.world):
            if not (planted_any[0][i] or planted_any[1][i]):
                continue
            c = mm.com([(w["com:" + nm], lengths[nm]) for nm in lengths])
            pts = []
            for k, side in enumerate("lr"):
                if planted_any[k][i]:
                    pts += [w[key] for key in (f"ankle_{side}", f"ball_{side}", f"toe_{side}") if key in w]
            if pts:
                worst = max(worst, mm.outside_support(c, pts))
        out["balance_worst_m"] = round(worst, 3)
    return out


def verdicts(before: dict, after: dict | None, fixing: bool = False) -> list[str]:
    """Plain-English warnings, comparing the result with the original where it helps."""
    r = after or before
    msgs = []
    if after is not None and before.get("lowest_point_m") is not None and after.get("lowest_point_m") is not None:
        sink = before["lowest_point_m"] - after["lowest_point_m"]
        if sink > 0.015:
            msgs.append(f"FAIL feet go {sink * 100:.1f} cm lower than the original: they sink into the floor.")
    if r.get("lowest_joint_m") is not None and r["lowest_joint_m"] < -0.02:
        was = before.get("lowest_joint_m", 0.0) if after is not None else 0.0
        if after is None or r["lowest_joint_m"] < was - 0.02:
            msgs.append(
                f"FAIL the {r['lowest_joint'].split('_')[0]} goes {-r['lowest_joint_m'] * 100:.0f} cm "
                "through the floor."
            )
    for side, v in ({} if r.get("feet_off_ground") else r["feet"]).items():
        base = before["feet"].get(side, {}).get("worst_slide_m_s", 0.0) if after is not None else 0.0
        limit = 0.2 if after is None else (0.2 if fixing else max(0.12, base * 1.5 + 0.03))
        if v["worst_slide_m_s"] > limit:
            was = (
                f" (was {base:.2f}; the fixer only nudges feet up to 8 cm)"
                if fixing and base > v["worst_slide_m_s"]
                else ""
            )
            msgs.append(f"WARN {side} foot slides {v['worst_slide_m_s']:.2f} m/s while planted (skating){was}.")
    if r.get("loop_seam_deg", 0) > 5:
        msgs.append(
            f"WARN the loop doesn't join up: a bone jumps {r['loop_seam_deg']:.0f} degrees from the last frame "
            "back to the first, so it hitches every time it loops. Make the last pose match the first."
        )
    # A fix is judged on every pop left in its result (it used to skip the clip's own and say PASS,
    # 14 Nov 2026); an edit only on pops it added.
    new_pops = set(r["pops"]) - (set(before["pops"]) if after is not None and not fixing else set())
    if new_pops:
        where = ", ".join(f"{b} (frame {r['pops'][b][0]})" if r["pops"][b] else b for b in sorted(new_pops)[:6])
        msgs.append(
            f"WARN sudden jumps between two frames (pops) in: {where}. A bone snaps to a new angle instead "
            "of turning over a few frames; smooth the keys there."
        )
    one_foot = r.get("body", {}).get("one_foot_off_balance_m", 0)
    if r.get("balance_worst_m", 0) > 0.08 and not (one_foot > 0.08 and one_foot >= r["balance_worst_m"] - 0.001):
        msgs.append(
            f"WARN off balance: the body's weight sits {r['balance_worst_m'] * 100:.0f} cm outside the feet "
            "while it stands, so it would tip over. Move the hips back over the feet."
        )
    if r.get("hips_travel_m", 0) > 0.3 and r.get("root_travel_m", 0) < 0.05:
        msgs.append(
            f"WARN the body travels {r['hips_travel_m']:.2f} m but the root bone stays put: no root motion. "
            "In a game the character's collider stays behind while the body walks off. Fix it with Root "
            "motion set to 'Move onto root', or 'Walk on the spot' if the game moves the character itself."
        )
    if "root_sway_cm" in r:
        sway = R.root_sway_verdicts(r["root_sway_cm"], r.get("hips_sway_cm", 0.0))
        if after is None or not R.root_sway_verdicts(before.get("root_sway_cm", 0.0), before.get("hips_sway_cm", 0.0)):
            msgs += sway
    if "body" in r:
        msgs += body_checks.body_verdicts(
            before.get("body", {}),
            after.get("body") if after is not None else None,
            r.get("name", ""),
            bool(r.get("feet_off_ground")),
            r.get("fps", 30.0),
        )
    if not msgs:
        msgs.append("PASS no sinking, skating, seam jumps, pops, impossible joints or physics problems found.")
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
    """Checks on the skeleton itself: bone map, left/right, rest pose, size, root bone. The rest pose is read
    as the current clip shows it (a top bone the clip holds still is folded in: rig.rest_space)."""
    mw = rest_space(arm, roles.get("hips"))
    bones = arm.data.bones
    out: dict = {"missing": [r for r in REQUIRED if r not in roles]}
    # left/right: the left thigh must sit on the character's left (feet point forward)
    fwd = Vector((0, 0, 0))
    for side in "lr":
        f, t = roles.get(f"foot_{side}"), roles.get(f"toe_{side}")
        if f and t:
            fwd += mw.to_3x3() @ (bones[t].head_local - bones[f].head_local)
    fwd.z = 0
    if fwd.length > 1e-6 and roles.get("thigh_l") and roles.get("thigh_r"):
        right = fwd.normalized().cross(Vector((0, 0, 1)))
        dl = (mw @ bones[roles["thigh_l"]].head_local).dot(right)
        dr = (mw @ bones[roles["thigh_r"]].head_local).dot(right)
        out["sides_swapped"] = bool(dl > dr)
    # rest pose: how far the upper arms hang below horizontal
    angles = []
    for side in "lr":
        ub = roles.get(f"upperarm_{side}")
        if ub:
            v = mw.to_3x3() @ (bones[ub].tail_local - bones[ub].head_local)
            if v.length > 1e-6:
                angles.append(math.degrees(math.asin(max(-1.0, min(1.0, -v.normalized().z)))))
    if angles:
        a = sum(angles) / len(angles)
        out["arm_drop_deg"] = round(a, 1)
        out["rest_pose"] = "T" if a < 15 else "A" if a < 60 else "arms down"
    # size
    zs = [(mw @ b.head_local).z for b in bones] + [(mw @ b.tail_local).z for b in bones]
    out["height_m"] = round((max(zs) - min(zs)) * metres_per_unit(arm, roles.get("hips")), 3)
    top = [b.name for b in bones if b.parent is None]
    out["top_bones"] = top
    hips = roles.get("hips")
    out["root_bone"] = bool(hips and bones[hips].parent is not None)
    return out


def rig_verdicts(rig: dict, expect_pose: str | None = None) -> list[str]:
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
    if expect_pose and rig.get("rest_pose") and rig["rest_pose"] != expect_pose:
        msgs.append(
            f"FAIL rest pose is {rig['rest_pose']}-pose ({rig['arm_drop_deg']:.0f} degrees), "
            f"but this project uses {expect_pose}-pose: retargeted arms will be off by that much."
        )
    h = rig.get("height_m", 1.8)
    if h < 0.3 or h > 5:
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
