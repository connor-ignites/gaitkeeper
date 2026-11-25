# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: loading files, finding the humanoid bones, sampling clips. Runs inside Blender."""

from __future__ import annotations

import math
import re

import bpy
from mathutils import Vector

from . import motion_math as mm

ROLES: dict[str, list[str]] = {
    "hips": ["pelvis", "hips", "mixamorig:hips", "hip", "root.x"],
    "spine1": ["spine_01", "mixamorig:spine", "spine", "spine.001"],
    "spine2": ["spine_02", "mixamorig:spine1", "chest", "spine.002"],
    "spine3": ["spine_03", "mixamorig:spine2", "upperchest", "upper_chest", "spine.003"],
    "neck": ["neck_01", "neck", "mixamorig:neck", "spine.004"],
    "head": ["head", "mixamorig:head", "spine.006"],
}


for side, mix, sfx in (("l", "Left", ".l"), ("r", "Right", ".r")):
    ROLES.update(
        {
            f"thigh_{side}": [
                f"thigh_{side}",
                f"mixamorig:{mix.lower()}upleg",
                f"{mix.lower()}upleg",
                f"thigh{sfx}",
                f"upperleg{sfx}",
                f"upper_leg{sfx}",
            ],
            f"calf_{side}": [
                f"calf_{side}",
                f"mixamorig:{mix.lower()}leg",
                f"{mix.lower()}leg",
                f"shin{sfx}",
                f"lowerleg{sfx}",
                f"lower_leg{sfx}",
            ],
            f"foot_{side}": [f"foot_{side}", f"mixamorig:{mix.lower()}foot", f"{mix.lower()}foot", f"foot{sfx}"],
            f"toe_{side}": [
                f"ball_{side}",
                f"mixamorig:{mix.lower()}toebase",
                f"{mix.lower()}toebase",
                f"toe{sfx}",
                f"toes{sfx}",
            ],
            f"upperarm_{side}": [
                f"upperarm_{side}",
                f"mixamorig:{mix.lower()}arm",
                f"{mix.lower()}arm",
                f"upper_arm{sfx}",
                f"upperarm{sfx}",
            ],
            f"lowerarm_{side}": [
                f"lowerarm_{side}",
                f"mixamorig:{mix.lower()}forearm",
                f"{mix.lower()}forearm",
                f"forearm{sfx}",
                f"lowerarm{sfx}",
            ],
            f"hand_{side}": [f"hand_{side}", f"mixamorig:{mix.lower()}hand", f"{mix.lower()}hand", f"hand{sfx}"],
        }
    )


def clip_label(arm: bpy.types.Object, name: str) -> str:
    """The name the checks read: the clip's own, or the file's in front of it when the clip's says
    nothing ("root|Scene"). The file is the one load() read, else the open .blend, else the rig's name."""
    from .body import judged_name

    src = bpy.context.scene.get("gaitkeeper_source") or bpy.data.filepath or arm.name
    return judged_name(name, str(src))


# bone names from any pack, boiled down: prefix and side removed, lower case, letters only
CANON: dict[str, tuple[str, ...]] = {
    "hips": ("hips", "pelvis", "hip"),
    "neck": ("neck",),
    "head": ("head",),
    "thigh": ("thigh", "upleg", "upperleg", "legupper"),
    "calf": ("calf", "shin", "leg", "lowerleg", "leglower", "knee"),
    "foot": ("foot", "ankle"),
    "toe": ("toe", "toes", "toebase", "ball"),
    "upperarm": ("upperarm", "arm", "uparm", "armupper"),
    "lowerarm": ("lowerarm", "forearm", "elbow", "armlower"),
    "hand": ("hand", "wrist"),
}
PREFIXES = ("mixamorig", "def", "org", "bip", "ccbase", "rig", "armature", "character", "skeleton", "b")


def split_name(name: str) -> tuple[str, str]:
    """("l" | "r" | "", core) for a bone name in any common style: mixamorig:LeftUpLeg, B-thigh.L,
    thigh_l, LeftUpperLeg, Bip01 L Thigh, DEF-forearm.R, L_Hand."""
    n = name.split(":")[-1].split("|")[-1]
    side = ""
    m = re.search(r"[._\- ](l|r|left|right)$", n, re.I)
    if m:
        side, n = m.group(1)[0].lower(), n[: m.start()]
    elif m := re.match(r"(left|right)", n, re.I):
        side, n = m.group(1)[0].lower(), n[m.end() :]
    elif m := re.match(r"([LR])[._\- ]", n):
        side, n = m.group(1).lower(), n[m.end() :]
    elif m := re.search(r"[._\- ]([LR])[._\- ]", n):
        side, n = m.group(1).lower(), n[: m.start()] + " " + n[m.end() :]
    core = re.sub(r"[^a-z]", "", n.lower())
    known = {c for names in CANON.values() for c in names} | {"spine", "chest", "upperchest"}
    for p in PREFIXES:
        if core.startswith(p) and core[len(p) :] in known:
            return side, core[len(p) :]
    return side, core


def role_map(arm: bpy.types.Object) -> dict[str, str]:
    lower = {b.name.lower(): b.name for b in arm.pose.bones}
    out = {}
    for role, names in ROLES.items():
        for n in names:
            if n.lower() in lower:
                out[role] = lower[n.lower()]
                break
    # any other naming style: match on the boiled-down name
    by_core: dict[tuple[str, str], str] = {}
    for pb in arm.pose.bones:
        side, core = split_name(pb.name)
        by_core.setdefault((side, core), pb.name)
    for role, names in CANON.items():
        for side in ("l", "r") if role not in ("hips", "neck", "head") else ("",):
            key = f"{role}_{side}" if side else role
            if key in out:
                continue
            for c in names:
                if (side, c) in by_core:
                    out[key] = by_core[(side, c)]
                    break
    # spine: the bones between the hips and the neck, lowest first
    if "hips" in out and "neck" in out and not all(k in out for k in ("spine1", "spine2", "spine3")):
        chain = []
        pb = arm.pose.bones[out["neck"]].parent
        while pb is not None and pb.name != out["hips"]:
            chain.append(pb.name)
            pb = pb.parent
        if pb is not None and chain:
            chain.reverse()
            out["spine1"] = chain[0]
            out["spine2"] = chain[min(1, len(chain) - 1)]
            out["spine3"] = chain[-1]
    return out


def set_action(arm: bpy.types.Object, act: bpy.types.Action) -> None:
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    slots = getattr(act, "slots", None)
    if slots is not None and getattr(ad, "action_slot", None) is None and len(slots):
        ad.action_slot = slots[0]


def clip_range(act: bpy.types.Action) -> tuple[int, int]:
    a, b = act.frame_range
    return math.floor(a + 1e-4), math.ceil(b - 1e-4)


class Sample:
    """Local pose (basis) of every bone per frame, and world positions of the bones the checks use."""

    def __init__(self) -> None:
        self.basis: list[dict[str, tuple[tuple, tuple, tuple]]] = []  # bone -> (loc, quat, scale)
        self.world: list[dict[str, tuple[float, float, float]]] = []  # key -> world position
        self.world_q: list[dict[str, tuple]] = []  # bone -> world rotation quat (pops)
        self.rest_q: dict[str, tuple] = {}  # bone -> world rotation quat in the rest pose
        self.rest_axis: dict[str, tuple] = {}  # bone -> its long axis (head to tail) at rest, world
        self.roles: dict[str, str] = {}  # humanoid role -> bone name
        self.rest_fwd: tuple | None = None  # the way the feet point in the rest pose (world, flat)


def leg_sides(roles: dict[str, str]) -> list[str]:
    """The legs in a role map: "l" and "r" (a person, or an animal's hind legs), and "fl", "fr" for an
    animal's front legs."""
    return sorted({k.split("_", 1)[1] for k in roles if k.startswith("foot_")}, key=lambda s: (len(s), s))


def world_points(arm: bpy.types.Object, roles: dict[str, str]) -> dict[str, tuple[float, float, float]]:
    mw = arm.matrix_world
    pts = {}
    for side in leg_sides(roles):
        f, t = roles.get(f"foot_{side}"), roles.get(f"toe_{side}")
        if f:
            pts[f"ankle_{side}"] = tuple(mw @ arm.pose.bones[f].head)
        if t:
            pts[f"ball_{side}"] = tuple(mw @ arm.pose.bones[t].head)
            pts[f"toe_{side}"] = tuple(mw @ arm.pose.bones[t].tail)
    for pb in arm.pose.bones:  # centre of mass needs every bone, weighted by length
        pts["com:" + pb.name] = tuple(mw @ ((pb.head + pb.tail) / 2))
    for role in ("calf_l", "calf_r", "hips", "spine1", "head"):  # joints that must stay above the floor
        if role in roles:
            pts["joint:" + role] = tuple(mw @ arm.pose.bones[roles[role]].head)
    if "hips" in roles:
        pts["hips"] = tuple(mw @ arm.pose.bones[roles["hips"]].head)
    # body points for the anatomy checks: pt:<role> is the bone's head (its joint), tip:<role> its tail
    for role, bone in roles.items():
        pb = arm.pose.bones[bone]
        pts["pt:" + role] = tuple(mw @ pb.head)
        pts["tip:" + role] = tuple(mw @ pb.tail)
    top = next((pb for pb in arm.pose.bones if pb.parent is None), None)
    if top is not None:
        pts["rootbone"] = tuple(mw @ top.head)
    return pts


NEXT_JOINT = {
    f"{a}_{s}": f"{b}_{s}"
    for s in "lr"
    for a, b in (("thigh", "calf"), ("calf", "foot"), ("foot", "toe"), ("upperarm", "lowerarm"), ("lowerarm", "hand"))
}


def sample(arm: bpy.types.Object, act: bpy.types.Action, roles: dict[str, str]) -> Sample:
    set_action(arm, act)
    s = Sample()
    a, b = clip_range(act)
    scn = bpy.context.scene
    mw = arm.matrix_world
    s.roles = dict(roles)
    s.rest_fwd = tuple(body_axes(arm, roles)[0])
    for bone in arm.data.bones:
        s.rest_q[bone.name] = tuple((mw @ bone.matrix_local).to_quaternion())
        s.rest_axis[bone.name] = tuple((mw.to_3x3() @ (bone.tail_local - bone.head_local)).normalized())
    # A limb's rest direction is its joint to the next joint, not its tail: FBX files have no tails, and the
    # importer guesses them, sometimes backwards on one side (Unity's Starter Assets rig: the right thigh's
    # tail points up, so a normal knee read as bent backwards and the thigh as swung 180 degrees).
    for role, nxt in NEXT_JOINT.items():
        here, there = roles.get(role), roles.get(nxt)
        if here and there and here in arm.data.bones and there in arm.data.bones:
            d = mw.to_3x3() @ (arm.data.bones[there].head_local - arm.data.bones[here].head_local)
            if d.length > 1e-6:
                s.rest_axis[here] = tuple(d.normalized())
    for f in range(a, b + 1):
        scn.frame_set(f)
        fr = {}
        wq = {}
        for pb in arm.pose.bones:
            loc, rot, sca = pb.matrix_basis.decompose()
            fr[pb.name] = (tuple(loc), tuple(rot), tuple(sca))
            wq[pb.name] = tuple((arm.matrix_world @ pb.matrix).to_quaternion())
        s.basis.append(fr)
        s.world.append(world_points(arm, roles))
        s.world_q.append(wq)
    return s


def interp_basis(frames: list[dict], t: float) -> dict:
    i = math.floor(t)
    i = max(0, min(i, len(frames) - 1))
    j = min(i + 1, len(frames) - 1)
    u = t - i
    if u < 1e-6 or i == j:
        return frames[i]
    out = {}
    for name, (la, qa, sa) in frames[i].items():
        lb, qb, sb = frames[j][name]
        out[name] = (
            tuple(x + (y - x) * u for x, y in zip(la, lb)),
            mm.q_slerp(qa, qb, u),
            tuple(x + (y - x) * u for x, y in zip(sa, sb)),
        )
    return out


def interp_list(vals: list[float], t: float) -> float:
    i = max(0, min(math.floor(t), len(vals) - 1))
    j = min(i + 1, len(vals) - 1)
    return vals[i] + (vals[j] - vals[i]) * (t - i)


def body_axes(arm: bpy.types.Object, roles: dict[str, str]) -> tuple[Vector, Vector, Vector]:
    """(forward, right, up) in world space, from the rest pose: feet point forward."""
    mw = arm.matrix_world.to_3x3()
    fwd = Vector((0, 0, 0))
    for side in "lr":
        f, t = roles.get(f"foot_{side}"), roles.get(f"toe_{side}")
        if f and t:
            fb, tb = arm.data.bones[f], arm.data.bones[t]
            fwd += mw @ (tb.head_local - fb.head_local)
    fwd.z = 0
    if fwd.length < 1e-6:
        fwd = Vector((0, -1, 0))
    fwd.normalize()
    up = Vector((0, 0, 1))
    right = fwd.cross(up).normalized()
    return fwd, right, up


def contact_flags(s: Sample, side: str, fps: float, cyclic: bool) -> list[bool]:
    key = f"ball_{side}" if f"ball_{side}" in s.world[0] else f"ankle_{side}"
    pos = [w[key] for w in s.world]
    h = [p[2] for p in pos]
    n = len(pos)
    sp = []
    for i in range(n):
        j = (i + 1) % n if cyclic else min(i + 1, n - 1)
        k = i if j != i else max(0, i - 1)
        a, b = pos[k], pos[j if j != i else i]
        sp.append(abs(b[2] - a[2]) * fps)
    return mm.drop_sweeps(pos, mm.contacts(h, sp, min(h)), fps, cyclic)
