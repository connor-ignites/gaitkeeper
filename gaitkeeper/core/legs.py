# SPDX-License-Identifier: GPL-3.0-or-later
"""Legs on any rig (two legs, four legs, a hopper): do they stay under the body, in line, and does
the body carry weight? Pure Python; creature.py finds the legs in Blender and feeds this.

A leg is a chain of joints from its top (hip or shoulder) to its end (toe or paw), with a side
(l or r) and an end (hind or fore). Per frame we get every joint's position, plus the pelvis.

Rules:
- legs swing fore and aft in the body's side plane: a knee or hock that bows outward from the
  line between the hip and the foot reads as splayed (frog legs)
- feet land under the hips: feet much wider than the hips read as straddling
- a pair that lands together is hopping: the body must sink and spring on landing, the feet stay
  down only briefly, and in the air the body falls at real gravity
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from . import body_rules, reactions
from .names import has_word, says_hops

BOW_WARN = {"hind": 0.06, "fore": 0.18}  # share of the leg; a good dog pack bows hind 1-2%, fore 10-13%
BOW_WARN_DEFAULT = 0.08  # for a leg that is neither hind nor fore
CONTACT_TOL_M = 0.03  # a leg's end within this of the floor is down
TURN_WORDS = ("l", "r", "bl", "br", "fl", "fr", "left", "right", "turn", "pivot", "strafe")
MOVING = ("walk", "trot", "run", "hop", "gallop", "canter", "sprint", "jog", "jump", "leap", "bound", "charge", "lope")
FLYING = ("hop", "jump", "run", "leap", "bound", "gallop", "sprint", "charge")
WIDE_WARN = 1.25  # feet 1.25 times wider apart than the hips
SPRING_MIN = 0.06  # a hop's landing sinks the hips at least 6% of the leg's length
HOP_RATE = (1.25, 3.0)  # kangaroos: about 1.3-1.5 hops a second slow, 2-2.3 fast (measured on reference footage)


def lateral(top_l: Sequence[float], top_r: Sequence[float]) -> body_rules.Vec:
    """The body's right, from the two hips (or shoulders), flat on the ground."""
    return body_rules.flat(body_rules.sub(top_r, top_l))


def bow(joints: Sequence[Sequence[float]], right: Sequence[float], side: str) -> float:
    """How far (m) the middle joints stand out sideways from the straight line between the top and
    the end of the leg, outward positive."""
    top, end = joints[0], joints[-1]
    sign = 1.0 if side == "r" else -1.0
    worst = 0.0
    for j in joints[1:-1]:
        # where the line top->end passes at this joint's height along the leg
        ab = body_rules.sub(end, top)
        t = max(0.0, min(1.0, body_rules.dot(body_rules.sub(j, top), ab) / max(1e-9, body_rules.dot(ab, ab))))
        on_line = body_rules.add(top, body_rules.scale(ab, t))
        worst = max(worst, sign * body_rules.dot(body_rules.sub(j, on_line), right))
    return worst


def leg_length(joints: Sequence[Sequence[float]]) -> float:
    return sum(body_rules.length(body_rules.sub(b, a)) for a, b in itertools.pairwise(joints)) or 1.0


def contacts(ends: Sequence[Sequence[float]], floor: float | None = None) -> list[bool]:
    """Frames where a leg's end is down: within CONTACT_TOL_M of the floor. By height only: in an
    in-place cycle a planted foot slides back at the ground speed on purpose."""
    h = [p[2] for p in ends]
    floor = min(h) if floor is None else floor
    return [hh <= floor + CONTACT_TOL_M for hh in h]


def measure(
    legs: dict[str, list[list[Sequence[float]]]],
    pelvis: Sequence[Sequence[float]],
    fps: float,
    rest_width: dict[str, float] | None = None,
) -> dict:
    """legs: name ("hind_l", "fore_r", ...) -> per frame, its joints top to end."""
    out: dict = {"legs": {}, "rest_width": rest_width or {}}
    flags: dict[str, list[bool]] = {}
    floor = min(fr[-1][2] for leg in legs.values() for fr in leg)  # one floor for every foot
    for end in ("hind", "fore"):
        if f"{end}_l" in legs and f"{end}_r" in legs:
            _measure_pair(end, legs[f"{end}_l"], legs[f"{end}_r"], floor, out, flags)
    if flags:
        _measure_hops(flags, pelvis, fps, out)
    return out


def _measure_pair(
    end: str,
    left_leg: list[list[Sequence[float]]],
    right_leg: list[list[Sequence[float]]],
    floor: float,
    out: dict,
    flags: dict[str, list[bool]],
) -> None:
    """One pair of legs (hind or fore): bow, feet width and time down, into `out`; contacts into `flags`."""
    n = len(left_leg)
    ln = (leg_length(left_leg[0]) + leg_length(right_leg[0])) / 2
    worst_bow = {"l": 0.0, "r": 0.0}
    width = []
    for i in range(n):
        right = lateral(left_leg[i][0], right_leg[i][0])
        for side, leg in (("l", left_leg), ("r", right_leg)):
            worst_bow[side] = max(worst_bow[side], bow(leg[i], right, side))
        hips_w = body_rules.dot(body_rules.sub(right_leg[i][0], left_leg[i][0]), right)
        feet_w = body_rules.dot(body_rules.sub(right_leg[i][-1], left_leg[i][-1]), right)
        width.append(feet_w / hips_w if hips_w > 1e-6 else 1.0)
    for side, leg in (("l", left_leg), ("r", right_leg)):
        flags[f"{end}_{side}"] = contacts([fr[-1] for fr in leg], floor)
        out["legs"][f"{end}_{side}"] = {
            "bow_share": round(worst_bow[side] / ln, 3),
            "bow_cm": round(worst_bow[side] * 100, 1),
            "down_share": round(sum(flags[f"{end}_{side}"]) / n, 2),
        }
    out[f"{end}_feet_width_ratio"] = round(sorted(width)[len(width) // 2], 2)
    out[f"{end}_leg_m"] = round(ln, 3)


def _measure_hops(flags: dict[str, list[bool]], pelvis: Sequence[Sequence[float]], fps: float, out: dict) -> None:
    """Whether the feet land together, time in the air, the fall and hang time in each flight, and how far
    the body sinks on landing, into `out`."""
    n = len(pelvis)
    # the pair lands together (a hop) or takes turns (a walk, trot, run)?
    hind = [k for k in flags if k.startswith("hind")] or list(flags)
    together = sum(1 for i in range(n) if all(flags[k][i] for k in hind) or not any(flags[k][i] for k in hind))
    out["hind_in_step"] = round(together / n, 2)
    air = [not any(f[i] for f in flags.values()) for i in range(n)]
    out["air_share"] = round(sum(air) / n, 2)
    runs = body_rules.true_runs(air)
    falls, hangs = [], []
    for st, ln_ in runs:
        if ln_ >= 6 and st > 0 and st + ln_ < n:
            zs = [pelvis[i][2] for i in range(st, st + ln_)]
            top = zs.index(max(zs))
            if 2 <= top <= ln_ - 3:
                falls.append(round(-body_rules.fall_acceleration(zs, fps), 1))
                h = reactions.hang_share(zs)
                if h is not None:
                    hangs.append(h)
    out["air_gravity_m_s2"] = falls
    out["hang_share"] = hangs
    # sink on landing: from touchdown to the lowest point while down
    leg_m = out.get("hind_leg_m", 1.0)
    down = [not a for a in air]
    sinks = []
    for st, ln_ in body_rules.true_runs(down):
        seg = [pelvis[i][2] for i in range(st, st + ln_)]
        if len(seg) >= 2:
            sinks.append((seg[0] - min(seg)) / leg_m)
    out["landing_sink_share"] = round(max(sinks), 3) if sinks else 0.0
    out["cycle_s"] = round((n - 1) / fps, 3)


def verdicts(m: dict, name: str, hopper: bool) -> list[str]:
    msgs = []
    from .body import words_of

    ws = words_of(name)
    turning = any(w in TURN_WORDS for w in ws)
    # stance rules only for straight-line moving clips: sitting, lying, digging and eating spread legs on purpose
    moving = any(w.startswith(k) for w in ws for k in MOVING) and not turning
    for leg, v in m.get("legs", {}).items():
        end, side = leg.split("_")
        if v["bow_share"] > BOW_WARN.get(end, BOW_WARN_DEFAULT) and moving:
            joint = "knee" if end == "hind" else "elbow"
            msgs.append(
                f"WARN {'left' if side == 'l' else 'right'} {end} leg: the {joint} bows {v['bow_cm']:.0f} cm out "
                f"from the line between {'hip' if end == 'hind' else 'shoulder'} and foot ({v['bow_share']:.0%} of "
                "the leg): it splays. Legs swing in the body's side plane; turn the bend so the "
                f"{joint} points {'forward' if end == 'hind' else 'back'}."
            )
    for end in ("hind", "fore"):
        r = m.get(f"{end}_feet_width_ratio")
        rest = m.get("rest_width", {}).get(end, 1.0)
        if moving and r and r > WIDE_WARN and r > rest * 1.15:  # the rig's own stance is reported once, not per clip
            msgs.append(
                f"WARN {end} feet land {r:.1f} times as wide apart as the {'hips' if end == 'hind' else 'shoulders'}: "
                "they straddle. Feet go under the body."
            )
    # the hop rules are for hoppers (kangaroos, wallabies, rabbits): a dog's jump is a different move
    if hopper and says_hops(name) and m.get("air_share", 0) > 0:
        down = max((v["down_share"] for k, v in m["legs"].items() if k.startswith("hind")), default=0)
        rate = 1 / m["cycle_s"] if m.get("cycle_s") else 0
        if m.get("landing_sink_share", 1) < SPRING_MIN:
            msgs.append(
                f"WARN the landing sinks the hips only {m['landing_sink_share']:.0%} of the leg: no spring, so it "
                "feels weightless. Land into a deep crouch (the heel drops, the hock folds) and spring out."
            )
        if down > 0.46:
            msgs.append(
                f"WARN the feet are down {down:.0%} of each hop: it sits on the ground. A hop touches down briefly "
                "(about 40% of the cycle at a slow hop, under a third at speed) and spends the rest in the air."
            )
        if rate and not HOP_RATE[0] <= rate <= HOP_RATE[1] and not has_word(name, ("kick",)):
            msgs.append(
                f"WARN {rate:.1f} hops a second: kangaroos hop about 1.3 to 1.5 times a second at a slow "
                "hop and 2 to 2.3 at speed (they go faster mostly with longer hops). Make the cycle 0.45-0.75 s."
            )
    if any(w.startswith(k) for w in ws for k in FLYING):
        msgs += reactions.hang_verdicts(m.get("hang_share", []))
    for g in m.get("air_gravity_m_s2", []) if any(w.startswith(k) for w in ws for k in FLYING) else []:
        if g < 6.5 or g > 14:
            msgs.append(
                f"WARN in the air the hips fall at {g:.1f} m/s each second (real gravity is 9.8): "
                f"{'it floats' if g < 6.5 else 'it is yanked down'}. Match the arc to the game's gravity."
            )
    return msgs
