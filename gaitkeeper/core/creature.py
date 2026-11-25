# SPDX-License-Identifier: GPL-3.0-or-later
"""Find the legs on any rig, in Blender: two legs, four legs or a hopper, named any way.

A leg ends at a bone near the floor in the rest pose (a foot, toe or paw) and climbs through its
parents until it reaches the trunk (bones on the body's centre line). The shoulder blade or
collarbone at the top of a front leg is left off, so a front leg starts at the shoulder joint.
"""

from __future__ import annotations

import math

import bpy

from . import adapt_math as am
from . import body_rules as br
from . import legs as L
from . import reactions as R
from .checks import clip_loops, scene_fps
from .names import has_word
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
TOPS_OFF = ("clavicle", "shoulder", "scapula", "collar")


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
        while chain and any(k in chain[0].name.lower() for k in TOPS_OFF) and len(chain) > 3:
            chain = chain[1:]
        if len(chain) >= 2:
            chains.append(chain)
    if not chains:
        return {}
    # sides by x, fore and hind by y (front = the end the head is on)
    head = next((b for b in arm.data.bones if "head" in b.name.lower()), None)
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
    period = am.step_period(left, fps, cyclic)
    if period and am.sides_alternate(left, right, period, cyclic):
        return False
    return True if am.sides_together(left, right, cyclic) else None


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


def measure_clip(
    arm: bpy.types.Object,
    act: bpy.types.Action,
    legs: dict[str, list[str]],
    pelvis: str,
    hopper: bool,
    rest_width: dict[str, float],
    scene: bpy.types.Scene,
    strike: bool = False,
    enemy: bool = False,
) -> tuple[dict, list[str]]:
    """Play the clip on `scene` and judge it; positions are read in metres (metres_world). strike: treat the
    clip as a strike with the legs even if its name doesn't say so. enemy: the clip is an enemy's (its strike
    must give the player time to react); its name can say so too."""

    name = clip_label(arm, act.name)  # an export's "Scene" says nothing: the file's name can say "Bite"
    cyclic = clip_loops(arm, act, scene, name)
    mw = metres_world(arm, pelvis)
    a, b = clip_range(act)
    per_leg: dict[str, list] = {k: [] for k in legs}
    pel = []
    ends = [pb.name for pb in arm.pose.bones if not pb.children and not has_word(pb.name, HELPERS)]
    head = next((pb.name for pb in arm.pose.bones if pb.name.lower().startswith("head")), None)
    rel: dict[str, list] = {e: [] for e in ends}
    ez: dict[str, list] = {e: [] for e in ends}
    head_z = []
    for f in range(a, b + 1):
        scene.frame_set(f)
        for k, names in legs.items():
            per_leg[k].append([tuple(mw @ arm.pose.bones[n].head) for n in names])  # joints only, no tails
        p = mw @ arm.pose.bones[pelvis].head
        pel.append(tuple(p))
        for e in ends:
            w = mw @ arm.pose.bones[e].head
            rel[e].append(tuple(w - p))
            ez[e].append(w.z)
        if head:
            head_z.append((mw @ arm.pose.bones[head].head).z)
    fps = scene_fps(scene)
    m = L.measure(per_leg, pel, fps, cyclic, rest_width)
    v = L.verdicts(m, act.name, hopper)
    floor = min((min(z) for z in ez.values() if z), default=0.0)
    runs = {
        e: r
        for e, r in ((e, R.linear_run(pts, fps, [h < floor + R.GROUND_TOL for h in ez[e]])) for e, pts in rel.items())
        if r[0]
    }
    m["linear_runs"] = runs
    v = v + R.linear_verdicts(runs, fps)
    resting = has_word(name, ("sleep", "lying", "lie", "sit"))
    if cyclic and has_word(name, ("idle",)) and head_z and not resting:
        k = len(pel) - 1 if len(pel) > 2 else len(pel)  # a loop's last frame repeats the first
        v = v + R.block_verdicts([q[2] for q in pel[:k]], {"head": head_z[:k]}, fps)
    if strike or has_word(name, LEG_STRIKE):
        sm, sv = measure_strike(arm, act, legs, per_leg, fps, hopper, scene, enemy or R.is_enemy(name))
        m["strike"] = sm
        v = v + sv
    elif R.is_upper_strike(name):
        um, uv = measure_upper_strike(arm, act, legs, pelvis, fps, scene, enemy or R.is_enemy(name))
        if um:
            m["upper_strike"] = um
        v = v + uv
    return m, v


HAND_WORDS = ("hand", "paw", "claw", "wrist")


def find_upper(arm: bpy.types.Object, legs: dict[str, list[str]]) -> dict[str, list[str]]:
    """The parts an animal strikes with above the legs: each arm (chest, shoulder, elbow, hand) and the
    head (two bones behind it, then the head). Arms are chains ending in a hand, paw or claw that isn't
    a leg (a kangaroo's arms; a dog's front legs are legs)."""
    in_legs = {n for c in legs.values() for n in c}
    out: dict[str, list[str]] = {}
    for b in arm.data.bones:
        low = b.name.lower()
        if b.name in in_legs or has_word(b.name, SKIP) or not any(k in low for k in HAND_WORDS):
            continue
        if any(c.name.lower().startswith(HAND_WORDS) for c in b.children):
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
    """A strike with the arms, claws or jaws (0.8). The striking point is the one moving fastest against
    the hips, so a lunge or a charge across the ground isn't mistaken for a punch; it is then judged where
    the player sees it, in the world (in metres)."""

    parts = find_upper(arm, legs)
    if not parts:
        return {}, []
    set_action(arm, act)
    mw = metres_world(arm, pelvis)
    pb = arm.pose.bones
    a, b = clip_range(act)
    head = parts.get("head", [None])[-1]
    jaw = find_jaw(arm, head)
    rest_gape = None
    if jaw:
        bones = arm.data.bones
        rest_gape = (bones[jaw].tail_local - bones[jaw].head_local).angle(
            bones[head].tail_local - bones[head].head_local, 0.0
        )
    joints: dict[str, list] = {k: [] for k in parts}
    pel, gape = [], []
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
    # Pick the part moving hardest against the hips (a charge moves everything at once), but judge it in
    # the world: a bite is a lunge, the body bringing the head, so the head moves little against the hips.
    best, best_rel = "", 0.0
    for k, js in joints.items():
        rel = [tuple(p - q for p, q in zip(pts[-1], c)) for pts, c in zip(js, pel)]
        top = max(br.speeds(rel, fps), default=0.0)
        if top > best_rel:
            best, best_rel = k, top
    if not best or best_rel < 0.5:
        return {}, []
    js = joints[best]
    tip = [pts[-1] for pts in js]
    st = br.strike(tip, fps)
    if not st or st["peak_speed_m_s"] < 2.0:
        return {}, []
    off = 0
    # A draw-back is against the body: found on the path relative to the hips, so a head rising with a
    # jump (the whole body going up) isn't taken for a wind-up.
    split = R.split_windup([tuple(p - q for p, q in zip(t, c)) for t, c in zip(tip, pel)], fps)
    if split:  # the fastest move was the draw-back (a claw lifted high): judge the strike that follows it
        later = br.strike(tip[split["windup"][1] + 1 :], fps)
        if later:
            off = split["windup"][1] + 1
            st = {
                **later,
                "hit_start": later["hit_start"] + off,
                "anticipation_s": round((later["hit_start"] + off) / fps, 3),
                "windup_m": max(later["windup_m"], split["windup_m"]),
                "windup_split": split,
            }
    sp = br.speeds(tip, fps)
    sp_hit = [0.0] * off + sp[off:]  # the strike alone, the draw-back left out, for timing the hit
    nice = "the head's bite" if best == "head" else f"the {best[4:].replace('_', ' ')}'s strike"
    body_i = 0  # the chest behind an arm, or the spine two bones behind the head
    # Who leads is decided on the way in to the strike, up to just after the hit: a jump attack's landing,
    # later, moves the body harder but has nothing to do with the strike.
    upto = min(len(js), st["hit_start"] + st["hit_frames"] + R.CHAIN_LEAD_FRAMES + 2)
    peaks = [off + br.peak_frame(br.speeds([pts[i] for pts in js[off:upto]], fps)) for i in range(body_i, len(js[0]))]
    bite = best == "head"
    out = (
        R.strike_verdicts(sp[off:], nice)
        + R.windup_verdicts(st, nice)
        + R.chain_verdicts(peaks, nice)
        + R.windup_outruns_verdicts(split if off else None, nice)
    )
    follow = R.follow_through_s(sp[off:], fps)
    body_follow = R.follow_through_s(br.speeds([pts[body_i] for pts in js], fps), fps, R.hit_end(sp_hit))
    if bite:
        # A bite grips: the head stops on the target by design (the Border Collie's bites hold low on it
        # for half a second; the wolf footage grips, then tugs). Only punches and swipes drive through.
        out = [v for v in out if "stops dead" not in v]
    else:
        out += R.follow_verdicts(follow, body_follow, nice)
    tell = R.tell_s(sp_hit, fps, [[*list(pts[:-1]), p] for pts, p in zip(js, pel)])
    if enemy:
        out += R.reaction_verdicts(tell, nice)
    m = {
        "part": best,
        "chain": parts[best],
        **st,
        "chain_peaks": peaks,
        "follow_through_s": follow,
        "body_follow_s": body_follow,
        "tell_s": None if tell is None else round(tell, 3),
    }
    if best == "head" and gape:
        m["jaw"] = jaw
        m["jaw_open_deg"] = [round(g, 1) for g in gape]
        out += R.jaw_verdicts(gape, st["hit_start"], fps, nice)
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
    and, for a hopper's kick (the kangaroo footage), the foot's angle and toe curl at the hit."""

    best, best_key = {}, ""
    for k, joints in per_leg.items():
        st = br.strike([j[-1] for j in joints], fps)
        if st and st["peak_speed_m_s"] > best.get("peak_speed_m_s", 0):
            best, best_key = st, k
    if not best or best["peak_speed_m_s"] < 2.0:
        return {}, []
    end = [j[-1] for j in per_leg[best_key]]
    sp = br.speeds(end, fps)
    name = f"the {best_key.replace('_l', ' left').replace('_r', ' right').replace('_', ' ')} leg's strike"
    out = R.strike_verdicts(sp, name)
    corners = R.path_corners(end, fps)
    out += R.arc_verdicts(corners, name)
    follow = R.follow_through_s(sp, fps)
    body_follow = R.follow_through_s(br.speeds([j[0] for j in per_leg[best_key]], fps), fps, R.hit_end(sp))
    out += R.follow_verdicts(follow, body_follow, name)  # the body: the top of the kicking leg (the hip)
    body = [
        [pts[0] for pts in (per_leg[k][i] for k in per_leg)] + [per_leg[k][i][-1] for k in per_leg]
        for i in range(len(end))
    ]  # every leg's top (the body) and end
    tell = R.tell_s(sp, fps, body)
    if enemy:
        out += R.reaction_verdicts(tell, name)
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
        contact = max(range(len(sp)), key=lambda i: sp[i]) + 1
        hit = [k for k in range(contact, contact + 4) if k < len(end)]
        set_action(arm, act)
        a = clip_range(act)[0]
        dirs = []
        for f in range(a, a + len(end)):
            scene.frame_set(f)
            dirs.append(leg_dirs(arm, names))
        ankle, curl = R.foot_angles(
            [d[0] for d in dirs], [d[1] for d in dirs], [d[2] for d in dirs], leg_dirs(arm, names, posed=False)
        )
        m["ankle_at_hit_deg"] = [round(ankle[k]) for k in hit]
        m["toe_curl_at_hit_deg"] = [round(curl[k]) for k in hit]
        out += R.strike_foot_verdicts(ankle, curl, hit, f"the kicking foot ({best_key})")
    return m, out


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
