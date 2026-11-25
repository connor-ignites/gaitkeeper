# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper body checks: anatomy, balance, gait and physics, in plain English.

No Blender import, so it runs on any object shaped like rig.Sample (unit-tested with a fake).
Each limit and where it comes from is noted beside it in body_rules.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from . import body_rules, motion_math, reactions
from .names import has_word, is_enemy, words_of

RUNNING = ("run", "sprint", "jog", "dash")
GAIT = ("walk", "run", "jog", "sprint")
TURN_WORDS = ("l", "r", "bl", "br", "fl", "fr", "left", "right", "turn", "pivot", "strafe")
AIR_OK = (
    *RUNNING,
    "jump",
    "hop",
    "leap",
    "fall",
    "swim",
    "fly",
    "climb",
    "roll",
    "death",
    "die",
    "vault",
    "flip",
    "hang",
    "dodge",
    "ragdoll",
    "knock",
    "launch",
    "air",
)
SUPPORTED = (
    "push",
    "pull",
    "lean",
    "grab",
    "climb",
    "hang",
    "ledge",
    "sit",
    "kneel",
    "lying",
    "drive",
    "carry",
    "lift",
    "interact",
)  # something else takes some of the weight
ATTACK = (
    "attack",
    "punch",
    "slash",
    "swing",
    "kick",
    "strike",
    "throw",
    "stab",
    "chop",
    "smash",
    "jab",
    "combo",
    "melee",
)


# Words an exporter puts in a clip's name that say nothing about the move ("root|Scene", "Take 001",
# "Armature|mixamo.com|Layer0"): with only these, the checks read the file's name instead.
PLACEHOLDER = (
    "scene",
    "take",
    "armature",
    "root",
    "action",
    "layer",
    "mixamo",
    "com",
    "anim",
    "animation",
    "default",
    "clip",
    "base",
    "track",
    "stack",
)


def says_nothing(name: str) -> bool:
    """Every word of the name is an exporter's placeholder (or it has no words at all)."""
    return all(w in PLACEHOLDER for w in words_of(name))


def judged_name(clip: str, source: str = "") -> str:
    """The name the checks read for a clip: its own, or, when that says nothing (Blender exports name
    every clip "root|Scene"), the file's name in front of it, so Hero_Punch.fbx still gets the attack checks.
    Before a "|" is the rig's name ("SK_Mannequin|Scene"), so only what follows it is the clip's own."""
    if not source or not says_nothing(clip.split("|", 1)[-1]):
        return clip
    stem = source.replace("\\", "/").split("/")[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    return clip if says_nothing(stem) else f"{stem} {clip}"


def _pts(s: Any, key: str) -> list[tuple] | None:
    return [w[key] for w in s.world] if key in s.world[0] else None


def _first(s: Any, *keys: str) -> list[tuple] | None:
    for k in keys:
        p = _pts(s, k)
        if p is not None:
            return p
    return None


Issue = tuple[str, float, str]  # (key, size, message): bigger size = worse
SIDE_WORD = {"l": "left", "r": "right"}


@dataclass(frozen=True)
class _Clip:
    """One clip as the body measurements read it."""

    s: Any
    fps: float
    roles: dict[str, str]
    flags: dict[str, list[bool]]
    name: str
    travels: bool
    feet_off_ground: bool
    cyclic: bool
    standing_still: bool

    @property
    def n(self) -> int:
        return len(self.s.world)


def measure_body(
    s: Any,
    fps: float,
    roles: dict[str, str],
    flags: dict[str, list[bool]],
    lengths: dict[str, float],
    name: str,
    travels: bool,
    feet_off_ground: bool,
    cyclic: bool,
    standing_still: bool = False,
) -> dict:
    """Every body measurement of one clip: joints, balance, gait, spacing and attacks."""
    c = _Clip(s, fps, roles, flags, name, travels, feet_off_ground, cyclic, standing_still)
    chest = next((roles[r] for r in ("spine3", "spine2", "spine1") if r in roles), None)
    out: dict = _hinge_joints(s, roles)
    out.update(_joint_turns(s, roles, chest))
    hip_ext = _hip_extension(c)
    if hip_ext is not None:
        out["hip_extension_deg"] = hip_ext
    com = [motion_math.com([(w["com:" + nm], ln) for nm, ln in lengths.items() if "com:" + nm in w]) for w in s.world]
    out.update(_feet_on_ground(c, com))
    hl, hr = _pts(s, "pt:thigh_l"), _pts(s, "pt:thigh_r")
    if has_word(name, GAIT) and hl and hr:
        out.update(_gait(s, hl, hr))
    hp = _pts(s, "pt:hips") or _pts(s, "hips")
    if hp:
        out.update(_spacing(c, hp, hl, hr))
    if has_word(name, ATTACK):
        strike = _strike(c, chest)
        if strike:
            out["strike"] = strike
    return out


# ---------- joints ----------


def _knee(s: Any, roles: dict[str, str], side: str) -> dict | None:
    """The knee as a hinge, its axis from the rest pose: the shin folds back, away from where the feet point."""
    hip, knee, ankle = (_pts(s, f"pt:{r}_{side}") for r in ("thigh", "calf", "foot"))
    thigh = roles.get(f"thigh_{side}")
    if not (hip and knee and ankle and thigh):
        return None
    ref = None
    fwd = getattr(s, "rest_fwd", None)
    if fwd and thigh in s.rest_q:
        axis = body_rules.cross(s.rest_axis[thigh], body_rules.scale(fwd, -1.0))
        ref = body_rules.q_rotate(body_rules.q_inv(s.rest_q[thigh]), body_rules.unit(axis))
    return body_rules.hinge(hip, knee, ankle, [q[thigh] for q in s.world_q], ref_local=ref)


def _elbow(s: Any, roles: dict[str, str], side: str) -> dict | None:
    """The elbow as a hinge, about the axis the clip mostly bends it."""
    sh, el = _pts(s, f"pt:upperarm_{side}"), _pts(s, f"pt:lowerarm_{side}")
    wr = _first(s, f"pt:hand_{side}", f"tip:lowerarm_{side}")
    ua = roles.get(f"upperarm_{side}")
    if not (sh and el and wr and ua):
        return None
    return body_rules.hinge(
        sh,
        el,
        wr,
        [q[ua] for q in s.world_q],
        backward_limit=body_rules.ELBOW_BACKWARD_FAIL,
        sideways_limit=body_rules.ELBOW_SIDEWAYS_WARN,
    )


def _hinge_joints(s: Any, roles: dict[str, str]) -> dict:
    """Knees and elbows, side by side."""
    out: dict = {}
    for side in "lr":
        knee = _knee(s, roles, side)
        if knee is not None:
            out[f"knee_{side}"] = knee
        elbow = _elbow(s, roles, side)
        if elbow is not None:
            out[f"elbow_{side}"] = elbow
    return out


def _relative_turn(s: Any, parent: str | None, child: str | None) -> dict | None:
    """The most a bone bends and twists against its parent over the clip, compared with the rest pose."""
    if not parent or not child or child not in s.rest_q:
        return None
    bend = twist = 0.0
    for q in s.world_q:
        b, t = body_rules.relative_turn(s.rest_q[parent], s.rest_q[child], q[parent], q[child], s.rest_axis[child])
        bend, twist = max(bend, b), max(twist, t)
    return {"bend_deg": round(bend, 1), "twist_deg": round(twist, 1)}


def _joint_turns(s: Any, roles: dict[str, str], chest: str | None) -> dict:
    """Neck, spine and wrists: turns against the parent, compared with the rest pose."""
    out: dict = {}
    for key, parent, child in (
        ("neck", chest, roles.get("head")),
        ("spine", roles.get("hips"), chest),
        ("wrist_l", roles.get("lowerarm_l"), roles.get("hand_l")),
        ("wrist_r", roles.get("lowerarm_r"), roles.get("hand_r")),
    ):
        t = _relative_turn(s, parent, child)
        if t:
            out[key] = t
    return out


def _hip_extension(c: _Clip) -> float | None:
    """The furthest a thigh swings behind the pelvis, in degrees (None without a pelvis and rest pose)."""
    s, roles = c.s, c.roles
    pelvis_b = roles.get("hips")
    fwd = getattr(s, "rest_fwd", None)
    if not (pelvis_b and fwd and pelvis_b in s.rest_q):
        return None
    worst = 0.0
    inv_rest = body_rules.q_inv(s.rest_q[pelvis_b])
    f0 = body_rules.q_rotate(inv_rest, fwd)
    for side in "lr":
        thigh, hip, knee = roles.get(f"thigh_{side}"), _pts(s, f"pt:thigh_{side}"), _pts(s, f"pt:calf_{side}")
        if not thigh or not hip or not knee or thigh not in s.rest_axis:
            continue
        # neutral is straight down at rest, not the rest thigh: some files rest mid-stride (Starter Assets:
        # one thigh 21 degrees back, the other 29 forward), which read as a 180-degree swing
        d0 = body_rules.q_rotate(inv_rest, (0.0, 0.0, -1.0))
        for i in range(c.n):
            d = body_rules.q_rotate(body_rules.q_inv(s.world_q[i][pelvis_b]), body_rules.sub(knee[i], hip[i]))
            worst = max(worst, body_rules.hip_extension_deg(d0, f0, d))
    return round(worst, 1)


# ---------- feet on the ground ----------


def _sole_heights(s: Any) -> dict[str, list[float]]:
    """Per side, the lowest of the ball (or ankle) and toe on each frame."""
    sole = {}
    for side in "lr":
        k = f"ball_{side}" if f"ball_{side}" in s.world[0] else f"ankle_{side}"
        if k in s.world[0]:
            sole[side] = [min(w.get(f"toe_{side}", w[k])[2], w[k][2]) for w in s.world]
    return sole


def _feet_on_ground(c: _Clip, com: list[tuple]) -> dict:
    """Flight, steps a minute, sudden changes of speed, and balance on one foot."""
    sole = _sole_heights(c.s)
    flags, n = c.flags, c.n
    if len(sole) != 2 or len(flags) != 2:
        return {}
    ground = min(min(v) for v in sole.values())
    air = [
        not flags["l"][i] and not flags["r"][i] and sole["l"][i] > ground + 0.05 and sole["r"][i] > ground + 0.05
        for i in range(n)
    ]
    out: dict = {"airborne_frames": sum(air)}
    runs = body_rules.true_runs(air)
    out["longest_airborne"] = max((ln for _, ln in runs), default=0)
    out["air_gravity_m_s2"], out["hang_share"] = _flight_arcs(c, runs, com)
    steps = sum(len(motion_math.runs(flags[sd], c.cyclic)) for sd in "lr")
    secs = (n - 1) / c.fps if n > 1 else 1.0
    out["steps_per_min"] = round(steps / secs * 60, 1) if secs > 0 else 0.0
    # COM sudden changes of speed while a foot is down
    acc = body_rules.accel_series(com, c.fps, span=3)
    grounded = [a for i, a in enumerate(acc, start=3) if flags["l"][i] or flags["r"][i]]
    out["com_accel_max_m_s2"] = round(max(grounded), 1) if grounded else 0.0
    if c.standing_still and not has_word(c.name, AIR_OK + GAIT + ATTACK + SUPPORTED):
        # static balance only: a moving body falls into its next step on purpose
        worst, worst_side = _one_foot_balance(c, com)
        out["one_foot_off_balance_m"] = round(worst, 3)
        out["one_foot_side"] = worst_side
    return out


def _flight_arcs(c: _Clip, runs: list[tuple[int, int]], com: list[tuple]) -> tuple[list[float], list[float]]:
    """Gravity (m/s2) and hang share of each whole flight that makes a real arc."""
    falls: list[float] = []
    hangs: list[float] = []
    for st, ln in runs:
        # only whole flights: one cut off by the clip's start or end isn't a full arc
        if ln >= 6 and not c.feet_off_ground and st > 0 and st + ln < c.n:
            zs = [com[i][2] for i in range(st, st + ln)]
            top = zs.index(max(zs))
            # a real arc: rises then falls, with the top well inside the flight
            if 2 <= top <= ln - 3 and max(zs) - zs[0] > 0.02 and max(zs) - zs[-1] > 0.02:
                falls.append(round(-body_rules.fall_acceleration(zs, c.fps), 2))
                h = reactions.hang_share(zs)
                if h is not None:
                    hangs.append(h)
    return falls, hangs


def _one_foot_balance(c: _Clip, com: list[tuple]) -> tuple[float, str]:
    """Standing on one foot: the furthest the weight sits outside it (m), and which foot."""
    s, flags, n = c.s, c.flags, c.n
    worst, worst_side = 0.0, ""
    for i in range(n):
        down = [sd for sd in "lr" if flags[sd][i]]
        if len(down) != 1:
            continue
        j = min(i + 1, n - 1)
        if i == j or body_rules.length(body_rules.sub(com[j], com[i])) * c.fps > 0.25:
            continue
        sd = down[0]
        pts = [s.world[i][k] for k in (f"ankle_{sd}", f"ball_{sd}", f"toe_{sd}") if k in s.world[i]]
        if pts:
            d = motion_math.outside_support(com[i], pts)
            if d > worst:
                worst, worst_side = d, sd
    return worst, worst_side


# ---------- gait: arms against legs, chest against hips ----------


def _gait(s: Any, hl: list[tuple], hr: list[tuple]) -> dict:
    """Arm swing against leg swing, and chest turn against hip turn."""
    n = len(s.world)
    out: dict = {}
    al, ar = _pts(s, "ankle_l"), _pts(s, "ankle_r")
    wl = _first(s, "pt:hand_l", "tip:lowerarm_l")
    wr = _first(s, "pt:hand_r", "tip:lowerarm_r")
    fwd = [
        body_rules.unit(body_rules.cross(body_rules.UP, body_rules.flat(body_rules.sub(hr[i], hl[i]))))
        for i in range(n)
    ]
    if al and ar and wl and wr:
        leg = [body_rules.dot(body_rules.sub(al[i], ar[i]), fwd[i]) for i in range(n)]
        arm = [body_rules.dot(body_rules.sub(wl[i], wr[i]), fwd[i]) for i in range(n)]
        out["arm_leg_corr"] = round(body_rules.correlation(arm, leg), 2)
        out["arm_swing_m"] = round(body_rules.spread(arm), 3)
        out["leg_swing_m"] = round(body_rules.spread(leg), 3)
    sl, sr = _pts(s, "pt:upperarm_l"), _pts(s, "pt:upperarm_r")
    if sl and sr:
        py, cy = _yaw_series(hl, hr), _yaw_series(sl, sr)
        out["chest_hip_corr"] = round(body_rules.correlation(cy, py), 2)
        out["hip_turn_deg"] = round(body_rules.spread(py), 1)
        out["chest_turn_deg"] = round(body_rules.spread(cy), 1)
    return out


def _yaw_series(a: list[tuple], b: list[tuple]) -> list[float]:
    """Heading of the line a->b on each frame, in degrees against the first frame."""
    ys = [math.degrees(math.atan2(b[i][1] - a[i][1], b[i][0] - a[i][0])) for i in range(len(a))]
    return [(y - ys[0] + 180) % 360 - 180 for y in ys]


# ---------- spacing, sideways lean, overlap ----------


def _spacing(c: _Clip, hp: list[tuple], hl: list[tuple] | None, hr: list[tuple] | None) -> dict:
    """Parts gliding at one steady velocity, sideways lean in a walk or run, and an idle's overlap."""
    out: dict = {"linear_runs": _linear_runs(c, hp)}
    top = _first(c.s, "pt:neck", "pt:head")
    if has_word(c.name, GAIT) and top and hl and hr:
        lean = _side_lean(c, hp, top, hl, hr)
        if lean is not None:
            out["lean"] = lean
    if c.cyclic and has_word(c.name, ("idle",)) and not has_word(c.name, ("sit", "driv", "lying", "sleep")):
        out["block_bob"] = _block_bob(c, hp)
    return out


def _linear_runs(c: _Clip, hp: list[tuple]) -> dict[str, tuple[int, int]]:
    """A part gliding at one steady velocity (linear in-betweens), against the hips."""
    s, n = c.s, c.n
    runs: dict[str, tuple[int, int]] = {}
    floor_z = min(
        (q[2] for k in ("toe_l", "toe_r", "ankle_l", "ankle_r") for q in (_pts(s, k) or [])),
        default=min(q[2] for q in hp) - 1.0,
    )
    for key, label in (
        ("tip:hand_l", "left hand"),
        ("tip:hand_r", "right hand"),
        ("tip:head", "head"),
        ("toe_l", "left foot"),
        ("toe_r", "right foot"),
    ):
        p = _pts(s, key)
        if p:
            rel = [body_rules.sub(p[i], hp[i]) for i in range(n)]
            r = reactions.linear_run(rel, c.fps, [q[2] < floor_z + reactions.GROUND_TOL for q in p])
            if r[0]:
                runs[label] = r
    # the hips against the root bone: a travelling clip moves the whole body at the game speed
    rb = _pts(s, "rootbone")
    r = reactions.linear_run([body_rules.sub(hp[i], rb[i]) for i in range(n)] if rb and rb[0] != hp[0] else hp, c.fps)
    if r[0]:
        runs["hips"] = r
    return runs


def _side_lean(c: _Clip, hp: list[tuple], top: list[tuple], hl: list[tuple], hr: list[tuple]) -> dict | None:
    """Leaning sideways in a walk or run, beyond what the turn needs (clamped, or it looks drunk)."""
    turning = any(w in TURN_WORDS for w in words_of(c.name))
    rb = _pts(c.s, "rootbone")
    path = rb if rb and rb[0] != hp[0] and c.travels else (hp if c.travels else None)
    if path is None and turning:
        return None
    need = reactions.turn_lean_deg(path, c.fps) if path is not None else None
    lean = reactions.lean_measure(reactions.side_lean_deg(hp, top, hl, hr), need)
    lean["turning"] = turning
    return lean


def _block_bob(c: _Clip, hp: list[tuple]) -> list[str]:
    """Overlap: in an idle, the head and hands trail the hips' bob."""
    n = c.n
    m = n - 1 if n > 2 else n  # a loop's last frame repeats the first
    parts = {
        lab: [p[i][2] for i in range(m)]
        for lab, key in (("head", "pt:head"), ("hands", "pt:hand_l"))
        if (p := _pts(c.s, key))
    }
    return reactions.block_verdicts([hp[i][2] for i in range(m)], parts, c.fps)


# ---------- attacks: anticipation, hit, recovery, wind-up, kinetic chain ----------


def _fastest_strike(c: _Clip) -> tuple[dict, str]:
    """The strike of the hand, forearm or foot that moves fastest, and that effector's key."""
    best: dict = {}
    best_key = ""
    for key in ("tip:hand_l", "tip:hand_r", "tip:lowerarm_l", "tip:lowerarm_r", "toe_l", "toe_r"):
        p = _pts(c.s, key)
        if p is None:
            continue
        st = body_rules.strike(p, c.fps)
        if st and st["peak_speed_m_s"] > best.get("peak_speed_m_s", 0):
            best, best_key = st, key
    return best, best_key


def _strike(c: _Clip, chest: str | None) -> dict:
    """The fastest strike with its tell, wind-up, chest turn, kinetic chain and follow-through ({} if none)."""
    s, fps = c.s, c.fps
    best, best_key = _fastest_strike(c)
    if not best:
        return best
    best["effector"] = best_key.split(":")[-1]
    best["path_corners"] = reactions.path_corners(_pts(s, best_key) or [], fps)
    keys = [
        k for k in ("hips", "pt:spine3", "pt:head", "tip:hand_l", "tip:hand_r", "toe_l", "toe_r") if k in s.world[0]
    ]
    tell = reactions.tell_s(
        body_rules.speeds(_pts(s, best_key) or [], fps), fps, [[w[k] for k in keys] for w in s.world]
    )
    best["tell_s"] = None if tell is None else round(tell, 3)
    split = _windup_split(c, best_key)
    if split:
        best["windup_split"] = split
    if chest:
        q0 = s.world_q[0][chest]
        best["chest_turn_deg"] = round(max(motion_math.q_angle_deg(q0, q[chest]) for q in s.world_q), 1)
    peaks = _chain_peaks(c, best_key)
    if peaks is not None:
        best["chain_peaks"] = peaks
    lsp = body_rules.speeds(_pts(s, best_key) or [], fps)
    best["follow_through_s"] = reactions.follow_through_s(lsp, fps)
    core = _first(s, "pt:spine3", "pt:spine2", "pt:neck", "pt:hips")
    if core and lsp:
        best["body_follow_s"] = reactions.follow_through_s(body_rules.speeds(core, fps), fps, reactions.hit_end(lsp))
    return best


def _windup_split(c: _Clip, key: str) -> dict | None:
    """A draw-back is against the body (the path relative to the hips), as for animals: when the fastest burst
    is a wind-up and the strike is a later burst going the other way, both are noted."""
    hp, ep = _pts(c.s, "hips"), _pts(c.s, key)
    if not (hp and ep):
        return None
    return reactions.split_windup([tuple(p - q for p, q in zip(e, h)) for e, h in zip(ep, hp)], c.fps)


def _chain_peaks(c: _Clip, key: str) -> list[int] | None:
    """Frames where hips, chest, upper arm, forearm and then the hand turn fastest (arm strikes only)."""
    roles, s = c.roles, c.s
    side = key[-1]
    chain = [
        roles.get(r)
        for r in ("hips", "spine3" if "spine3" in roles else "spine2", f"upperarm_{side}", f"lowerarm_{side}")
    ]
    bones = [b for b in chain if b]
    if len(bones) != len(chain) or not ("hand" in key or "lowerarm" in key):
        return None
    peaks = [
        body_rules.peak_frame([motion_math.q_angle_deg(s.world_q[i][b], s.world_q[i + 1][b]) for i in range(c.n - 1)])
        for b in bones
    ]
    return [*peaks, body_rules.peak_frame(body_rules.speeds(_pts(s, key) or [], c.fps))]


# ---------- verdicts ----------


def _issues(b: dict, name: str, feet_off_ground: bool, fps: float) -> list[Issue]:
    """(key, size, message) for every problem in one measurement. Bigger size = worse."""
    out: list[Issue] = []
    for side in "lr":
        out += _knee_issues(b.get(f"knee_{side}"), side)
        out += _elbow_issues(b.get(f"elbow_{side}"), side)
        out += _wrist_issues(b.get(f"wrist_{side}"), side)
    out += _trunk_issues(b)
    out += _air_issues(b, name, feet_off_ground)
    out += _balance_issues(b)
    out += _gait_issues(b, name)
    out += _spacing_issues(b, fps)
    st = b.get("strike")
    if st:
        out += _strike_issues(st, name, fps)
    return [_misread(k, v, m) for k, v, m in out]


def _knee_issues(k: dict | None, side: str) -> list[Issue]:
    """A knee bending backwards, folding through the thigh, or bending sideways."""
    if not k:
        return []
    out: list[Issue] = []
    word = SIDE_WORD[side]
    if k["backward_frames"]:
        out.append(
            (
                f"knee_back_{side}",
                k["worst_backward_deg"],
                f"FAIL {word} knee bends backwards ({k['worst_backward_deg']:.0f} degrees, "
                f"{len(k['backward_frames'])} frames). A knee is a hinge: it only folds forward.",
            )
        )
    if k["max_bend_deg"] > body_rules.KNEE_FOLD_FAIL:
        out.append(
            (
                f"knee_fold_{side}",
                k["max_bend_deg"],
                f"FAIL {word} knee folds {k['max_bend_deg']:.0f} degrees: past a full squat "
                "(about 155), so the shin is passing through the thigh.",
            )
        )
    if k["worst_sideways_deg"]:
        out.append(
            (
                f"knee_side_{side}",
                k["worst_sideways_deg"],
                f"WARN {word} knee bends sideways ({k['worst_sideways_deg']:.0f} degrees off "
                "its hinge): knees don't bend side to side; turn the thigh instead.",
            )
        )
    return out


def _elbow_issues(e: dict | None, side: str) -> list[Issue]:
    """An elbow bending the wrong way, folding past the upper arm, or bending sideways."""
    if not e:
        return []
    out: list[Issue] = []
    word = SIDE_WORD[side]
    if e["backward_frames"]:
        out.append(
            (
                f"elbow_back_{side}",
                e["worst_backward_deg"],
                f"FAIL {word} elbow bends the wrong way ({e['worst_backward_deg']:.0f} degrees, "
                f"{len(e['backward_frames'])} frames). An elbow is a hinge: it only folds one way.",
            )
        )
    if e["max_bend_deg"] > body_rules.ELBOW_FOLD_FAIL:
        out.append(
            (
                f"elbow_fold_{side}",
                e["max_bend_deg"],
                f"FAIL {word} elbow folds {e['max_bend_deg']:.0f} degrees: an elbow stops "
                "at about 150, where the forearm meets the upper arm.",
            )
        )
    if e["worst_sideways_deg"]:
        out.append(
            (
                f"elbow_side_{side}",
                e["worst_sideways_deg"],
                f"WARN {word} elbow bends sideways ({e['worst_sideways_deg']:.0f} degrees off "
                "its hinge): twist the forearm or turn the shoulder instead.",
            )
        )
    return out


def _wrist_issues(w: dict | None, side: str) -> list[Issue]:
    """A wrist bent past what a wrist manages."""
    if not (w and w["bend_deg"] > body_rules.WRIST_BEND_FAIL):
        return []
    return [
        (
            f"wrist_{side}",
            w["bend_deg"],
            f"FAIL {SIDE_WORD[side]} wrist bends {w['bend_deg']:.0f} degrees: a wrist manages about "
            "80 forward, 70 back, 30 to the side.",
        )
    ]


def _trunk_issues(b: dict) -> list[Issue]:
    """The head against the chest, the chest against the hips, and a thigh behind the pelvis."""
    out: list[Issue] = []
    nk = b.get("neck")
    if nk and (nk["bend_deg"] > body_rules.NECK_TURN_FAIL or nk["twist_deg"] > body_rules.NECK_TURN_FAIL):
        out.append(
            (
                "neck",
                max(nk["bend_deg"], nk["twist_deg"]),
                f"FAIL head turns {max(nk['bend_deg'], nk['twist_deg']):.0f} degrees against the chest: a neck "
                "turns about 80 and nods about 60. Turn the chest and shoulders too.",
            )
        )
    sp = b.get("spine")
    if sp and sp["twist_deg"] > body_rules.SPINE_TWIST_FAIL:
        out.append(
            (
                "spine_twist",
                sp["twist_deg"],
                f"FAIL chest twists {sp['twist_deg']:.0f} degrees against the hips: a spine twists about "
                "45-60. Turn the hips or step round instead.",
            )
        )
    if sp and sp["bend_deg"] > body_rules.SPINE_BEND_FAIL:
        out.append(
            (
                "spine_bend",
                sp["bend_deg"],
                f"FAIL chest bends {sp['bend_deg']:.0f} degrees against the hips: past what a spine does "
                "(about 90). Bend at the hips for the rest.",
            )
        )
    if b.get("hip_extension_deg", 0) > body_rules.HIP_EXTENSION_WARN:
        out.append(
            (
                "hip_ext",
                b["hip_extension_deg"],
                f"WARN a thigh swings {b['hip_extension_deg']:.0f} degrees behind the pelvis: a hip extends about "
                "20 walking and 30 sprinting. Tilt the pelvis forward to get more.",
            )
        )
    return out


def _air_issues(b: dict, name: str, feet_off_ground: bool) -> list[Issue]:
    """Floating off the ground, a run that never leaves it, and the fall and hang of each flight."""
    out: list[Issue] = []
    air_ok = has_word(name, AIR_OK) or feet_off_ground
    la = b.get("longest_airborne", 0)
    if not air_ok and la >= 2:
        out.append(
            (
                "float",
                la,
                f"WARN both feet leave the ground for {la} frames and nothing launches the body: "
                "outside a run or a jump, one foot stays down.",
            )
        )
    if has_word(name, RUNNING) and "airborne_frames" in b and b["airborne_frames"] == 0 and not feet_off_ground:
        out.append(
            (
                "no_flight",
                1.0,
                "WARN a run with no moment where both feet are off the ground: it reads as "
                "a fast walk. A run leaves the ground on every step.",
            )
        )
    out += _gravity_issues(b.get("air_gravity_m_s2", []))
    for v in reactions.hang_verdicts(b.get("hang_share", [])):
        out.append(("hang", 1 - min(b["hang_share"]), v))
    return out


def _gravity_issues(falls: list[float]) -> list[Issue]:
    """Each flight's fall against real gravity (9.8 m/s2): floaty below 6.5, heavy above 14."""
    out: list[Issue] = []
    for g in falls:
        if g < 6.5:
            out.append(
                (
                    "floaty",
                    9.81 - g,
                    f"WARN in the air the body falls at {g:.1f} m/s each second (real "
                    "gravity is 9.8): it floats. Fine for a stylised game jump if the game's gravity matches.",
                )
            )
        elif g > 14:
            out.append(
                (
                    "heavy",
                    g - 9.81,
                    f"WARN in the air the body falls at {g:.1f} m/s each second (real "
                    "gravity is 9.8): it drops like it's pulled down. Snappy, but check the game's jump "
                    "gravity matches.",
                )
            )
    return out


def _balance_issues(b: dict) -> list[Issue]:
    """Leaning sideways, sudden changes of speed on the feet, and the weight off a standing foot."""
    out: list[Issue] = []
    ln_ = b.get("lean")
    if ln_:
        for v in reactions.lean_verdicts(ln_, ln_.get("turning", False)):
            out.append(("lean", max(abs(ln_["mean_deg"]), ln_["excess_deg"]), v))
    if b.get("com_accel_max_m_s2", 0) > 30:
        out.append(
            (
                "jerk",
                b["com_accel_max_m_s2"],
                f"WARN the body changes speed at {b['com_accel_max_m_s2']:.0f} m/s every second while on its feet "
                "(over three times the pull of gravity): legs can't push that hard. Ease into stops and starts.",
            )
        )
    if b.get("one_foot_off_balance_m", 0) > body_rules.OFF_BALANCE_WARN_M:
        sd = SIDE_WORD.get(b.get("one_foot_side", ""), "one")
        out.append(
            (
                "one_foot",
                b["one_foot_off_balance_m"],
                f"WARN standing on the {sd} foot with the weight {b['one_foot_off_balance_m'] * 100:.0f} cm off "
                "it: shift the hips over the standing foot before the other one lifts (weight shifts lead).",
            )
        )
    return out


def _gait_issues(b: dict, name: str) -> list[Issue]:
    """A walk's cadence, arms swinging with the same-side leg, and a chest turning with the hips."""
    out: list[Issue] = []
    spm = b.get("steps_per_min")
    walking = spm and has_word(name, ("walk",)) and not has_word(name, RUNNING) and b.get("airborne_frames", 0) == 0
    if walking and (spm > 140 or spm < 70):
        out.append(
            (
                "cadence",
                abs(spm - 110),
                f"WARN {spm:.0f} steps a minute: a walk is 100-120 "
                f"({'shuffling or rushing' if spm > 140 else 'very slow, like wading'}).",
            )
        )
    if b.get("arm_leg_corr", -1) > 0.3 and b.get("arm_swing_m", 0) > 0.03 and b.get("leg_swing_m", 0) > 0.05:
        out.append(
            (
                "same_side",
                b["arm_leg_corr"],
                "WARN arms swing with the same-side leg (marching like a "
                "robot): each arm swings forward with the opposite leg.",
            )
        )
    if b.get("chest_hip_corr", -1) > 0.5 and b.get("hip_turn_deg", 0) > 2 and b.get("chest_turn_deg", 0) > 2:
        out.append(
            (
                "no_counter",
                b["chest_hip_corr"],
                "WARN the chest turns with the hips instead of against "
                "them: in a walk the shoulders twist the opposite way to the hips.",
            )
        )
    return out


def _spacing_issues(b: dict, fps: float) -> list[Issue]:
    """Parts gliding at one steady velocity, and an idle that moves as one block."""
    out: list[Issue] = []
    for v in reactions.linear_verdicts({k: tuple(r) for k, r in b.get("linear_runs", {}).items()}, fps):
        out.append(("linear", max(r[0] for r in b["linear_runs"].values()), v))
    for v in b.get("block_bob", []):
        out.append(("block", 1.0, v))
    return out


def _strike_label(effector: str) -> str:
    """How the verdicts name a strike: "toe_l" -> "the left toe's strike"."""
    part = effector[:-2].replace("lowerarm", "forearm") if effector[-2:] in ("_l", "_r") else effector
    side = "left " if effector.endswith("_l") else "right " if effector.endswith("_r") else ""
    return f"the {side}{part}'s strike"


def _strike_issues(st: dict, name: str, fps: float) -> list[Issue]:
    """An enemy's tell, a wind-up that outruns the hit, the hit's lead-in and length, and the body behind it."""
    out: list[Issue] = []
    nice = _strike_label(st["effector"])
    if is_enemy(name):  # an enemy's attack must give the player time to react
        for v in reactions.reaction_verdicts(st.get("tell_s"), nice):
            out.append(("tell", st.get("tell_s") or 0.0, v))
    # the fastest move was a draw-back going the other way, faster than the hit (as for animals, 0.8)
    for v in reactions.windup_outruns_verdicts(st.get("windup_split"), nice):
        out.append(("windup_fast", st["windup_split"]["windup_m_s"], v))
    f30 = st["hit_frames"] * 30.0 / fps
    if st["reach_m"] > 0.4 and st["windup_m"] < 0.03 and st["anticipation_s"] < 0.05:
        out.append(
            (
                "no_windup",
                st["reach_m"],
                f"WARN the {st['effector']} strikes {st['reach_m']:.2f} m from the "
                "first frame with no wind-up: a big hit needs a lead-in (anticipation), even a short one.",
            )
        )
    if f30 > 10:
        out.append(
            (
                "slow_hit",
                f30,
                f"WARN the hit takes {st['hit_frames']} frames ({f30:.0f} at 30 fps): 4-8 "
                "frames at 30 fps reads as a hit; longer reads as a push.",
            )
        )
    return out + _strike_body_issues(st)


def _strike_body_issues(st: dict) -> list[Issue]:
    """A strike where only the limb moves, its path turns corners, or the hand outruns the chest."""
    out: list[Issue] = []
    if st["reach_m"] > 0.4 and st.get("chest_turn_deg", 99) < 3:
        out.append(
            (
                "stiff_body",
                st["reach_m"],
                "WARN only the limb moves: the chest stays still. Let the move "
                "ripple into the shoulder and chest a little (everything is connected).",
            )
        )
    if st.get("path_corners"):
        out.append(
            ("arc", len(st["path_corners"]), reactions.arc_verdicts(st["path_corners"], f"the {st['effector']}")[0])
        )
    pk = st.get("chain_peaks")
    if pk and len(pk) >= 3 and pk[-1] + 2 < pk[1]:
        out.append(
            (
                "chain",
                pk[1] - pk[-1],
                "WARN the hand is fastest before the chest moves: power runs hips, "
                "chest, shoulder, elbow, hand, each a frame or two after the last.",
            )
        )
    return out


MISREAD_NOTE = (
    " Past anything a body can do: a broken clip (a mirrored bone) or GaitKeeper misreading the rig "
    "gives this. Measure the joint on the bones before blaming the clip."
)


def _misread(key: str, size: float, msg: str) -> tuple[str, float, str]:
    """A reading past what any body could do: still the clip's FAIL (a mirrored knee is a real fault), with a note
    to rule out the tool first. When most clips of a pack read it, misread_verdicts() blames the rig reading."""
    k = body_rules.misread_key(key)
    if k is None or size <= body_rules.MISREAD_DEG[k]:
        return key, size, msg
    return key, size, msg + MISREAD_NOTE


def misread_verdicts(clip_verdicts: dict[str, list[str]]) -> list[str]:
    """Rig-level TOOL? lines: the same reading no body could make in most clips of a file or pack (3+ clips, 60 %+)
    is the tool misreading the rig, not every clip being broken (seen on a pack whose every clip read upside down)."""
    n = len(clip_verdicts)
    if n < 3:
        return []
    import re

    hits: dict[str, list[str]] = {}
    for name, vs in clip_verdicts.items():
        for v in vs:
            if v.endswith(MISREAD_NOTE):
                what = (
                    re.sub(r"\(?\d+(\.\d+)? (degrees|frames)[^)]*\)?", "", v.split(".", 1)[0]).split(" ", 1)[1].strip()
                )
                hits.setdefault(what, [])
                if name not in hits[what]:
                    hits[what].append(name)
    return [
        f"TOOL? {len(names)} of {n} clips read '{what}' past anything a body can do: GaitKeeper is almost "
        "certainly misreading this rig (bone directions, rest pose or a root turn), not every clip being broken. "
        "Check one of these clips by eye; if it looks fine, please report the rig with the file."
        for what, names in sorted(hits.items())
        if len(names) >= 0.6 * n
    ]


def body_verdicts(before: dict, after: dict | None, name: str, feet_off_ground: bool, fps: float) -> list[str]:
    """Messages for one clip. With `after`, only problems that are new or at least 10% worse."""
    if after is None:
        return [m for _, _, m in _issues(before, name, feet_off_ground, fps)]
    was = {k: v for k, v, _ in _issues(before, name, feet_off_ground, fps)}
    return [m for k, v, m in _issues(after, name, feet_off_ground, fps) if k not in was or v > was[k] * 1.1 + 0.5]
