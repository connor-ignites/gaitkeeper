# SPDX-License-Identifier: GPL-3.0-or-later
"""Find the legs on any rig, in Blender: two legs, four legs or a hopper, named any way.

A leg ends at a bone near the floor in the rest pose (a foot, toe or paw) and climbs through its
parents until it reaches the trunk (bones on the body's centre line). The shoulder blade or
collarbone at the top of a front leg is left off, so a front leg starts at the shoulder joint.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import bpy

from . import adapt_math, body_rules, reactions
from . import legs as leg_checks
from .checks import clip_loops, scene_fps
from .names import hand_bone, has_word, is_enemy, is_upper_strike, shoulder_top
from .rig import body_axes, clip_label, clip_range, metres_world, rest_space, set_action

SKIP = (
    "tail",
    "ear",
    "tongue",
    "jaw",
    "eye",
    "finger",
    "thumb",
    "index",
    "middle",
    "ring",
    "pinky",
    "twist",
    "prop",
    "weapon",
    "ik",
    "pole",
    "target",
    "ctrl",
    "fix",
    "helper",
)
STRIKE_MIN_SPEED = 2.0  # m/s: a striking hand, head or foot peaks at least this fast
UPPER_MIN_REL_SPEED = 0.5  # m/s against the hips: below this no part above the legs is striking


class AnimalRig(NamedTuple):
    """What the animal checks need to know about a rig."""

    legs: dict[str, list[str]]
    pelvis: str
    hopper: bool
    rest_widths: dict[str, float]


def find_legs(arm: bpy.types.Object) -> dict[str, list[str]]:
    """leg name ("hind_l", "fore_r") -> bone names from the top joint down to the end. Tails, ears, props
    and controls are left out by whole words of their names (names.has_word), so RearLeg_L stays in."""
    mw = rest_space(arm, None)
    bones = [b for b in arm.data.bones if not has_word(b.name, SKIP)]
    zs = [(mw @ b.head_local).z for b in bones]  # joints of real bones only: helper tails can sit below the floor
    lo, hi = min(zs), max(zs)
    xs = [abs((mw @ b.head_local).x) for b in arm.data.bones]
    centre_tol = max(0.01, 0.15 * max(xs))
    low = [b for b in bones if (mw @ b.head_local).z < lo + 0.15 * (hi - lo)]
    ends = [b for b in low if not any(c in low for c in b.children)]  # the lowest of each chain
    chains = []
    for e in ends:
        chain = []
        b = e
        while b is not None and abs((mw @ b.head_local).x) > centre_tol:
            chain.append(b)
            b = b.parent
        chain.reverse()
        while chain and shoulder_top(chain[0].name) and len(chain) > 3:
            chain = chain[1:]
        if len(chain) >= 2:
            chains.append(chain)
    if not chains:
        return {}
    # sides by x, fore and hind by y (front = the end the head is on)
    head = next((b for b in arm.data.bones if has_word(b.name, ("head",))), None)
    tops_y = [(mw @ c[0].head_local).y for c in chains]
    mid_y = sum(tops_y) / len(tops_y)
    head_y = (mw @ head.head_local).y if head else mid_y - 1
    out: dict[str, list[str]] = {}
    for c in chains:
        side = "l" if (mw @ c[0].head_local).x > 0 else "r"  # Blender: +X is the character's left
        y = (mw @ c[0].head_local).y
        quad = max(tops_y) - min(tops_y) > 0.1 * (hi - lo)
        end = ("fore" if (y - mid_y) * (head_y - mid_y) > 0 else "hind") if quad else "hind"
        key = f"{end}_{side}"
        if key not in out or len(c) > len(out[key]):
            out[key] = [b.name for b in c]
    return out


STEPPING = ("walk", "run", "trot", "gallop", "jog", "sprint", "hop", "jump", "bound")


def feet_tracks(
    arm: bpy.types.Object, act: bpy.types.Action, legs: dict[str, list[str]], pelvis: str, scene: bpy.types.Scene
) -> tuple[list[list[float]], list[list[float]]]:
    """Per hind foot (left, right): its height and how far ahead of the pelvis it is, frame by frame."""
    set_action(arm, act)
    fwd = body_axes(arm, leg_roles(arm, legs, pelvis))[0]
    mw = metres_world(arm, pelvis)
    tracks: dict[str, list[list[float]]] = {s: [[], []] for s in "lr"}
    first, last = clip_range(act)
    for f in range(first, last + 1):
        scene.frame_set(f)
        hips = mw @ arm.pose.bones[pelvis].head
        for s, (height, ahead) in tracks.items():
            foot = mw @ arm.pose.bones[legs[f"hind_{s}"][-1]].head
            height.append(foot.z)
            ahead.append((foot - hips).dot(fwd))
    return tracks["l"], tracks["r"]


def feet_in_phase(left: list[list[float]], right: list[list[float]], fps: float, cyclic: bool) -> bool | None:
    """True when the feet move together (a hop), False when they take turns (a walk), None when neither shows."""
    period = adapt_math.step_period(left, fps, cyclic)
    if period and adapt_math.sides_alternate(left, right, period, cyclic):
        return False
    return True if adapt_math.sides_together(left, right, cyclic) else None


def hops(
    arm: bpy.types.Object, acts: list[bpy.types.Action], legs: dict[str, list[str]], pelvis: str, scene: bpy.types.Scene
) -> bool | None:
    """Whether a two-legged animal hops (a kangaroo) rather than walks (an emu), by its stepping clips (named
    walk, run, hop...): most of them move the feet together. None when no clip tells. Leaves the clip and
    frame it plays; the caller puts them back."""
    fps = scene_fps(scene)
    votes = []
    for act in acts:
        name = clip_label(arm, act.name)
        if has_word(name, STEPPING):
            cyclic = clip_loops(arm, act, scene, name)
            vote = feet_in_phase(*feet_tracks(arm, act, legs, pelvis, scene), fps, cyclic)
            if vote is not None:
                votes.append(vote)
    return 2 * sum(votes) > len(votes) if votes else None


class ClipTracks(NamedTuple):
    """An animal clip's positions frame by frame, in metres."""

    per_leg: dict[str, list]  # leg -> per frame, every joint of the leg (joints only, no tails)
    pelvis: list[tuple]  # the pelvis
    ends_rel: dict[str, list]  # end bone -> per frame, its joint relative to the pelvis
    ends_z: dict[str, list[float]]  # end bone -> per frame, its joint's height
    head_z: list[float]  # the head's height (empty when no head bone was found)


def measure_clip(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    animal: AnimalRig,
    scene: bpy.types.Scene,
    strike: bool = False,
    enemy: bool = False,
) -> tuple[dict, list[str]]:
    """Play the clip on `scene` and judge it; positions are read in metres (metres_world). strike: treat the
    clip as a strike with the legs even if its name doesn't say so. enemy: the clip is an enemy's (its strike
    must give the player time to react); its name can say so too."""
    name = clip_label(arm, act.name)  # an export's "Scene" says nothing: the file's name can say "Bite"
    cyclic = clip_loops(arm, act, scene, name)
    tracks = clip_tracks(arm, act, animal, scene)
    fps = scene_fps(scene)
    m = leg_checks.measure(tracks.per_leg, tracks.pelvis, fps, animal.rest_widths)
    v = leg_checks.verdicts(m, act.name, animal.hopper)
    m["linear_runs"] = runs = _linear_runs(tracks, fps)
    v = v + reactions.linear_verdicts(runs, fps)
    resting = has_word(name, ("sleep", "lying", "lie", "sit"))
    if cyclic and has_word(name, ("idle",)) and tracks.head_z and not resting:
        k = len(tracks.pelvis) - 1 if len(tracks.pelvis) > 2 else len(tracks.pelvis)  # the last frame repeats
        v = v + reactions.block_verdicts([q[2] for q in tracks.pelvis[:k]], {"head": tracks.head_z[:k]}, fps)
    enemy = enemy or is_enemy(name)
    if strike or has_word(name, LEG_STRIKE):
        sm, sv = measure_strike(arm, act, animal.legs, tracks.per_leg, fps, animal.hopper, scene, enemy)
        m["strike"] = sm
        v = v + sv
    elif is_upper_strike(name):
        um, uv = measure_upper_strike(arm, act, animal.legs, animal.pelvis, fps, scene, enemy)
        if um:
            m["upper_strike"] = um
        v = v + uv
    return m, v


def clip_tracks(arm: bpy.types.Object, act: bpy.types.Action, animal: AnimalRig, scene: bpy.types.Scene) -> ClipTracks:
    """Play the current clip `act` on `scene` and record the legs, pelvis, bone ends and head."""
    mw = metres_world(arm, animal.pelvis)
    pb = arm.pose.bones
    ends = [b.name for b in pb if not b.children and not has_word(b.name, HELPERS)]
    head = next((b.name for b in pb if b.name.lower().startswith("head")), None)
    tracks = ClipTracks({k: [] for k in animal.legs}, [], {e: [] for e in ends}, {e: [] for e in ends}, [])
    a, b = clip_range(act)
    for f in range(a, b + 1):
        scene.frame_set(f)
        for k, names in animal.legs.items():
            tracks.per_leg[k].append([tuple(mw @ pb[n].head) for n in names])
        p = mw @ pb[animal.pelvis].head
        tracks.pelvis.append(tuple(p))
        for e in ends:
            w = mw @ pb[e].head
            tracks.ends_rel[e].append(tuple(w - p))
            tracks.ends_z[e].append(w.z)
        if head:
            tracks.head_z.append((mw @ pb[head].head).z)
    return tracks


def _linear_runs(tracks: ClipTracks, fps: float) -> dict[str, tuple[int, int]]:
    """Every bone end's longest stretch at one steady velocity, for those that have one. Frames where the
    end is planted on the floor never count."""
    floor = min((min(z) for z in tracks.ends_z.values() if z), default=0.0)
    runs = {}
    for e, pts in tracks.ends_rel.items():
        grounded = [h < floor + reactions.GROUND_TOL for h in tracks.ends_z[e]]
        r = reactions.linear_run(pts, fps, grounded)
        if r[0]:
            runs[e] = r
    return runs


def find_upper(arm: bpy.types.Object, legs: dict[str, list[str]]) -> dict[str, list[str]]:
    """The parts an animal strikes with above the legs: each arm (chest, shoulder, elbow, hand) and the
    head (two bones behind it, then the head). Arms are chains ending in a hand, paw or claw that isn't
    a leg (a kangaroo's arms; a dog's front legs are legs)."""
    in_legs = {n for c in legs.values() for n in c}
    out: dict[str, list[str]] = {}
    for b in arm.data.bones:
        if b.name in in_legs or has_word(b.name, SKIP) or not hand_bone(b.name):
            continue
        if any(hand_bone(c.name, first=True) for c in b.children):
            continue  # a wrist with a hand below it: the hand is the end
        chain, p = [b.name], b.parent
        while p is not None and len(chain) < 5:
            chain.append(p.name)
            p = p.parent
        if len(chain) >= 4:
            out[f"arm:{b.name}"] = list(reversed(chain))
    head = next((b for b in arm.data.bones if b.name.lower() == "head"), None) or next(
        (b for b in arm.data.bones if b.name.lower().startswith("head")), None
    )
    if head is not None:
        chain, p = [head.name], head.parent
        while p is not None and len(chain) < 4:
            chain.append(p.name)
            p = p.parent
        out["head"] = list(reversed(chain))
    return out


def find_jaw(arm: bpy.types.Object, head: str | None) -> str | None:
    """The lower jaw: a child of the head named jaw or mouth (not a lip corner like Mouth.L)."""
    if head is None:
        return None
    kids = arm.data.bones[head].children
    for want in ("jaw", "mouth", "jaw_01", "lowerjaw", "jaw_lower", "lower_jaw"):
        hit = next((c.name for c in kids if c.name.lower() == want), None)
        if hit:
            return hit
    return next((c.name for c in kids if c.name.lower().startswith("jaw")), None)


def measure_upper_strike(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    legs: dict[str, list[str]],
    pelvis: str,
    fps: float,
    scene: bpy.types.Scene,
    enemy: bool = False,
) -> tuple[dict, list[str]]:
    """A strike with the arms, claws or jaws. The striking point is the one moving fastest against the
    hips, so a lunge or a charge across the ground isn't mistaken for a punch; it is then judged where
    the player sees it, in the world (in metres)."""
    parts = find_upper(arm, legs)
    if not parts:
        return {}, []
    set_action(arm, act)
    head = parts.get("head", [None])[-1]
    jaw = find_jaw(arm, head)
    joints, pel, gape = _upper_tracks(arm, act, parts, pelvis, head, jaw, scene)
    best = _fastest_part(joints, pel, fps)
    if not best:
        return {}, []
    tip = [pts[-1] for pts in joints[best]]
    st = body_rules.strike(tip, fps)
    if not st or st["peak_speed_m_s"] < STRIKE_MIN_SPEED:
        return {}, []
    st, split, off = _strike_after_windup(st, tip, pel, fps)
    m, out = _upper_strike_verdicts(best, joints[best], pel, st, split, off, fps, enemy)
    m = {"part": best, "chain": parts[best], **m}
    if best == "head" and gape:
        m["jaw"] = jaw
        m["jaw_open_deg"] = [round(g, 1) for g in gape]
        out += reactions.jaw_verdicts(gape, st["hit_start"], fps, _strike_name(best))
    return m, out


def _upper_tracks(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    parts: dict[str, list[str]],
    pelvis: str,
    head: str | None,
    jaw: str | None,
    scene: bpy.types.Scene,
) -> tuple[dict[str, list], list[tuple], list[float]]:
    """Per frame, in metres: each part's joints (an arm's knuckles or claws last), the pelvis, and how far
    the jaw is open against its rest angle (degrees; empty without a jaw)."""
    mw = metres_world(arm, pelvis)
    pb = arm.pose.bones
    rest_gape = None
    if jaw:
        bones = arm.data.bones
        rest_gape = (bones[jaw].tail_local - bones[jaw].head_local).angle(
            bones[head].tail_local - bones[head].head_local, 0.0
        )
    joints: dict[str, list] = {k: [] for k in parts}
    pel, gape = [], []
    a, b = clip_range(act)
    for f in range(a, b + 1):
        scene.frame_set(f)
        pel.append(tuple(mw @ pb[pelvis].head))
        for k, chain in parts.items():
            pts = [tuple(mw @ pb[n].head) for n in chain]
            if k.startswith("arm:"):
                pts.append(tuple(mw @ pb[chain[-1]].tail))  # the knuckles or claws
            joints[k].append(pts)
        if jaw:
            ang = (pb[jaw].tail - pb[jaw].head).angle(pb[head].tail - pb[head].head, 0.0)
            gape.append(math.degrees(abs(ang - rest_gape)))
    return joints, pel, gape


def _fastest_part(joints: dict[str, list], pel: list[tuple], fps: float) -> str:
    """The part moving hardest against the hips ("" if none moves fast enough to strike). A charge moves
    everything at once, so it is picked against the hips, but judged in the world: a bite is a lunge, the
    body bringing the head, so the head moves little against the hips."""
    best, best_rel = "", 0.0
    for k, js in joints.items():
        rel = [tuple(p - q for p, q in zip(pts[-1], c)) for pts, c in zip(js, pel)]
        top = max(body_rules.speeds(rel, fps), default=0.0)
        if top > best_rel:
            best, best_rel = k, top
    return best if best_rel >= UPPER_MIN_REL_SPEED else ""


def _strike_after_windup(st: dict, tip: list[tuple], pel: list[tuple], fps: float) -> tuple[dict, dict | None, int]:
    """(strike, wind-up split, first frame of the strike). When the fastest move was the draw-back (a claw
    lifted high), the strike judged is the one that follows it. A draw-back is found on the path relative
    to the hips, so a head rising with a jump (the whole body going up) isn't taken for a wind-up."""
    split = reactions.split_windup([tuple(p - q for p, q in zip(t, c)) for t, c in zip(tip, pel)], fps)
    if not split:
        return st, split, 0
    later = body_rules.strike(tip[split["windup"][1] + 1 :], fps)
    if not later:
        return st, split, 0
    off = split["windup"][1] + 1
    st = {
        **later,
        "hit_start": later["hit_start"] + off,
        "anticipation_s": round((later["hit_start"] + off) / fps, 3),
        "windup_m": max(later["windup_m"], split["windup_m"]),
        "windup_split": split,
    }
    return st, split, off


def _strike_name(part: str) -> str:
    return "the head's bite" if part == "head" else f"the {part[4:].replace('_', ' ')}'s strike"


def _upper_strike_verdicts(
    part: str, js: list, pel: list[tuple], st: dict, split: dict | None, off: int, fps: float, enemy: bool
) -> tuple[dict, list[str]]:
    """Measurements and lines for the striking part's chain `js` (body end first, striking point last)."""
    tip = [pts[-1] for pts in js]
    sp = body_rules.speeds(tip, fps)
    sp_hit = [0.0] * off + sp[off:]  # the strike alone, the draw-back left out, for timing the hit
    nice = _strike_name(part)
    body_i = 0  # the chest behind an arm, or the spine two bones behind the head
    # Who leads is decided on the way in to the strike, up to just after the hit: a jump attack's landing,
    # later, moves the body harder but has nothing to do with the strike.
    upto = min(len(js), st["hit_start"] + st["hit_frames"] + reactions.CHAIN_LEAD_FRAMES + 2)
    peaks = [
        off + body_rules.peak_frame(body_rules.speeds([pts[i] for pts in js[off:upto]], fps))
        for i in range(body_i, len(js[0]))
    ]
    out = (
        reactions.strike_verdicts(sp[off:], nice)
        + reactions.windup_verdicts(st, nice)
        + reactions.chain_verdicts(peaks, nice)
        + reactions.windup_outruns_verdicts(split if off else None, nice)
    )
    follow = reactions.follow_through_s(sp[off:], fps)
    body_follow = reactions.follow_through_s(
        body_rules.speeds([pts[body_i] for pts in js], fps), fps, reactions.hit_end(sp_hit)
    )
    if part == "head":
        # A bite grips: the head stops on the target by design (good dog bites hold low on it for half a
        # second; wolves in footage grip, then tug). Only punches and swipes drive through.
        out = [v for v in out if "stops dead" not in v]
    else:
        out += reactions.follow_verdicts(follow, body_follow, nice)
    tell = reactions.tell_s(sp_hit, fps, [[*list(pts[:-1]), p] for pts, p in zip(js, pel)])
    if enemy:
        out += reactions.reaction_verdicts(tell, nice)
    m = {
        **st,
        "chain_peaks": peaks,
        "follow_through_s": follow,
        "body_follow_s": body_follow,
        "tell_s": None if tell is None else round(tell, 3),
    }
    return m, out


HELPERS = ("ik", "pole", "target", "ctrl", "prop", "weapon", "twist", "fix", "helper", "root", "end")
LEG_STRIKE = ("kick", "stomp", "grapple", "pounce", "trample", "buck")  # strikes made with the legs


def leg_dirs(arm: bpy.types.Object, names: list[str], posed: bool = True) -> tuple:
    """The last three bones of a leg (shin, foot, toe): their directions (knee to hock, hock to toe
    joint, toe joint to claw tip) in the shin bone's own frame, posed or at rest."""
    shin, foot, toe = names[-3:]
    if posed:
        pb = arm.pose.bones
        rot = pb[shin].matrix.to_quaternion().inverted()
        pts = (pb[shin].head, pb[foot].head, pb[toe].head, pb[toe].tail)
    else:
        bones = arm.data.bones
        rot = bones[shin].matrix_local.to_quaternion().inverted()
        pts = (bones[shin].head_local, bones[foot].head_local, bones[toe].head_local, bones[toe].tail_local)
    return tuple(tuple(rot @ (pts[i + 1] - pts[i])) for i in range(3))


def measure_strike(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    legs: dict[str, list[str]],
    per_leg: dict[str, list],
    fps: float,
    hopper: bool,
    scene: bpy.types.Scene,
    enemy: bool = False,
) -> tuple[dict, list[str]]:
    """A creature's strike with a leg: the fastest leg end. Dead stop and stutter, corners in its path
    and, for a hopper's kick (as kangaroos kick in reference footage), the foot's angle and toe curl at
    the hit."""
    best, best_key = {}, ""
    for k, joints in per_leg.items():
        st = body_rules.strike([j[-1] for j in joints], fps)
        if st and st["peak_speed_m_s"] > best.get("peak_speed_m_s", 0):
            best, best_key = st, k
    if not best or best["peak_speed_m_s"] < STRIKE_MIN_SPEED:
        return {}, []
    end = [j[-1] for j in per_leg[best_key]]
    sp = body_rules.speeds(end, fps)
    name = f"the {best_key.replace('_l', ' left').replace('_r', ' right').replace('_', ' ')} leg's strike"
    out = reactions.strike_verdicts(sp, name)
    corners = reactions.path_corners(end, fps)
    out += reactions.arc_verdicts(corners, name)
    follow = reactions.follow_through_s(sp, fps)
    body_follow = reactions.follow_through_s(
        body_rules.speeds([j[0] for j in per_leg[best_key]], fps), fps, reactions.hit_end(sp)
    )
    out += reactions.follow_verdicts(follow, body_follow, name)  # the body: the top of the kicking leg (the hip)
    body = [
        [pts[0] for pts in (per_leg[k][i] for k in per_leg)] + [per_leg[k][i][-1] for k in per_leg]
        for i in range(len(end))
    ]  # every leg's top (the body) and end
    tell = reactions.tell_s(sp, fps, body)
    if enemy:
        out += reactions.reaction_verdicts(tell, name)
    m = {
        "leg": best_key,
        **best,
        "path_corners": corners,
        "follow_through_s": follow,
        "body_follow_s": body_follow,
        "tell_s": None if tell is None else round(tell, 3),
    }
    names = legs[best_key]
    if hopper and len(names) >= 4:
        out += _kicking_foot(arm, act, names, sp, len(end), scene, best_key, m)
    return m, out


def _kicking_foot(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    names: list[str],
    sp: list[float],
    n: int,
    scene: bpy.types.Scene,
    leg: str,
    m: dict,
) -> list[str]:
    """A hopper's kicking foot at the hit: its angle against the shin and its toe curl, added to `m`."""
    contact = max(range(len(sp)), key=lambda i: sp[i]) + 1
    hit = [k for k in range(contact, contact + 4) if k < n]
    set_action(arm, act)
    a = clip_range(act)[0]
    dirs = []
    for f in range(a, a + n):
        scene.frame_set(f)
        dirs.append(leg_dirs(arm, names))
    ankle, curl = reactions.foot_angles(
        [d[0] for d in dirs], [d[1] for d in dirs], [d[2] for d in dirs], leg_dirs(arm, names, posed=False)
    )
    m["ankle_at_hit_deg"] = [round(ankle[k]) for k in hit]
    m["toe_curl_at_hit_deg"] = [round(curl[k]) for k in hit]
    return reactions.strike_foot_verdicts(ankle, curl, hit, f"the kicking foot ({leg})")


def rest_width(arm: bpy.types.Object, legs: dict[str, list[str]]) -> dict[str, float]:
    """Feet width over hip width in the rest pose, per leg pair."""
    mw = rest_space(arm, None)
    out = {}
    for end in ("hind", "fore"):
        if f"{end}_l" in legs and f"{end}_r" in legs:
            tl, tr = (mw @ arm.data.bones[legs[f"{end}_{s}"][0]].head_local for s in "lr")
            fl, fr = (mw @ arm.data.bones[legs[f"{end}_{s}"][-1]].head_local for s in "lr")
            out[end] = abs(fr.x - fl.x) / max(1e-6, abs(tr.x - tl.x))
    return out


def leg_roles(arm: bpy.types.Object, legs: dict[str, list[str]], pelvis: str) -> dict[str, str]:
    """An animal's legs in the same terms as a person's: each leg's two longest bones in a row are the
    thigh and calf (the knee bends between them), the next bone is the "foot" (held rigid with
    everything below it, so a paw keeps its shape) and the last bone's joint is where it meets the
    ground. Hind legs (and a hopper's legs) are sides "l" and "r"; front legs "fl" and "fr"."""
    out = {"hips": pelvis}
    for key, chain in legs.items():
        end, side = key.split("_")
        s = side if end == "hind" else "f" + side
        if len(chain) < 3:
            continue
        bones = arm.data.bones
        seg = [(bones[chain[i + 1]].head_local - bones[chain[i]].head_local).length for i in range(len(chain) - 1)]
        k = max(range(len(chain) - 2), key=lambda i: seg[i] + seg[i + 1])
        out[f"thigh_{s}"], out[f"calf_{s}"], out[f"foot_{s}"] = chain[k], chain[k + 1], chain[k + 2]
        if len(chain) > k + 3:
            out[f"toe_{s}"] = chain[-1]
    return out
