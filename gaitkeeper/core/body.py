# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper body checks: anatomy, balance, gait and physics, in plain English.

No Blender import, so it runs on any object shaped like rig.Sample (unit-tested with a fake).
The rules and where they come from are in tools/motion/BODY.md.
"""

from __future__ import annotations

import math
import re
from typing import Any

from . import body_rules as br
from . import motion_math as mm
from . import reactions as R

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


def words_of(name: str) -> list[str]:
    """Clip name to lower-case words: "Bad_SpineWrung-Loop2" -> bad, spine, wrung, loop."""
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)]


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


def _has(name: str, words: tuple[str, ...]) -> bool:
    """A word of the clip name starts with one of `words` (so "Running" counts, "Wrung" doesn't)."""
    return any(t.startswith(w) for t in words_of(name) for w in words)


def _pts(s: Any, key: str) -> list[tuple] | None:
    return [w[key] for w in s.world] if key in s.world[0] else None


def _first(s: Any, *keys: str) -> list[tuple] | None:
    for k in keys:
        p = _pts(s, k)
        if p is not None:
            return p
    return None


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
    n = len(s.world)
    out: dict = {}
    # ---- hinge joints ----
    for side in "lr":
        hip, knee, ankle = (_pts(s, f"pt:{r}_{side}") for r in ("thigh", "calf", "foot"))
        thigh = roles.get(f"thigh_{side}")
        if hip and knee and ankle and thigh:
            # the knee's hinge axis, from the rest pose: the shin folds back, away from where the feet point
            ref = None
            fwd = getattr(s, "rest_fwd", None)
            if fwd and thigh in s.rest_q:
                axis = br.cross(s.rest_axis[thigh], br.scale(fwd, -1.0))
                ref = br.q_rotate(br.q_inv(s.rest_q[thigh]), br.unit(axis))
            out[f"knee_{side}"] = br.hinge(hip, knee, ankle, [q[thigh] for q in s.world_q], ref_local=ref)
        sh, el = _pts(s, f"pt:upperarm_{side}"), _pts(s, f"pt:lowerarm_{side}")
        wr = _first(s, f"pt:hand_{side}", f"tip:lowerarm_{side}")
        ua = roles.get(f"upperarm_{side}")
        if sh and el and wr and ua:
            out[f"elbow_{side}"] = br.hinge(
                sh,
                el,
                wr,
                [q[ua] for q in s.world_q],
                backward_limit=br.ELBOW_BACKWARD_FAIL,
                sideways_limit=br.ELBOW_SIDEWAYS_WARN,
            )
    # ---- neck, spine, wrists: turns against the parent, compared with the rest pose ----
    chest = next((roles[r] for r in ("spine3", "spine2", "spine1") if r in roles), None)

    def turn(parent: str | None, child: str | None) -> dict | None:
        if not parent or not child or child not in s.rest_q:
            return None
        bend = twist = 0.0
        for q in s.world_q:
            b, t = br.relative_turn(s.rest_q[parent], s.rest_q[child], q[parent], q[child], s.rest_axis[child])
            bend, twist = max(bend, b), max(twist, t)
        return {"bend_deg": round(bend, 1), "twist_deg": round(twist, 1)}

    for key, parent, child in (
        ("neck", chest, roles.get("head")),
        ("spine", roles.get("hips"), chest),
        ("wrist_l", roles.get("lowerarm_l"), roles.get("hand_l")),
        ("wrist_r", roles.get("lowerarm_r"), roles.get("hand_r")),
    ):
        t = turn(parent, child)
        if t:
            out[key] = t
    # ---- hip extension (thigh behind the pelvis) ----
    pelvis_b = roles.get("hips")
    hl, hr = _pts(s, "pt:thigh_l"), _pts(s, "pt:thigh_r")
    fwd = getattr(s, "rest_fwd", None)
    if pelvis_b and fwd and pelvis_b in s.rest_q:
        worst = 0.0
        inv_rest = br.q_inv(s.rest_q[pelvis_b])
        f0 = br.q_rotate(inv_rest, fwd)
        for side in "lr":
            thigh, hip, knee = roles.get(f"thigh_{side}"), _pts(s, f"pt:thigh_{side}"), _pts(s, f"pt:calf_{side}")
            if not thigh or not hip or not knee or thigh not in s.rest_axis:
                continue
            # neutral is straight down at rest, not the rest thigh: some files rest mid-stride (Starter Assets:
            # one thigh 21 degrees back, the other 29 forward), which read as a 180-degree swing
            d0 = br.q_rotate(inv_rest, (0.0, 0.0, -1.0))
            for i in range(n):
                d = br.q_rotate(br.q_inv(s.world_q[i][pelvis_b]), br.sub(knee[i], hip[i]))
                worst = max(worst, br.hip_extension_deg(d0, f0, d))
        out["hip_extension_deg"] = round(worst, 1)
    # ---- centre of mass ----
    com = [mm.com([(w["com:" + nm], ln) for nm, ln in lengths.items() if "com:" + nm in w]) for w in s.world]
    # ---- feet on the ground ----
    sole = {}
    for side in "lr":
        k = f"ball_{side}" if f"ball_{side}" in s.world[0] else f"ankle_{side}"
        if k in s.world[0]:
            sole[side] = [min(w.get(f"toe_{side}", w[k])[2], w[k][2]) for w in s.world]
    if len(sole) == 2 and len(flags) == 2:
        ground = min(min(v) for v in sole.values())
        air = [
            not flags["l"][i] and not flags["r"][i] and sole["l"][i] > ground + 0.05 and sole["r"][i] > ground + 0.05
            for i in range(n)
        ]
        out["airborne_frames"] = sum(air)
        runs = br.true_runs(air)
        out["longest_airborne"] = max((ln for _, ln in runs), default=0)
        falls, hangs = [], []
        for st, ln in runs:
            # only whole flights: one cut off by the clip's start or end isn't a full arc
            if ln >= 6 and not feet_off_ground and st > 0 and st + ln < n:
                zs = [com[i][2] for i in range(st, st + ln)]
                top = zs.index(max(zs))
                # a real arc: rises then falls, with the top well inside the flight
                if 2 <= top <= ln - 3 and max(zs) - zs[0] > 0.02 and max(zs) - zs[-1] > 0.02:
                    falls.append(round(-br.fall_acceleration(zs, fps), 2))
                    h = R.hang_share(zs)
                    if h is not None:
                        hangs.append(h)
        out["air_gravity_m_s2"] = falls
        out["hang_share"] = hangs
        # steps a minute
        steps = sum(len(mm.runs(flags[sd], cyclic)) for sd in "lr")
        secs = (n - 1) / fps if n > 1 else 1.0
        out["steps_per_min"] = round(steps / secs * 60, 1) if secs > 0 else 0.0
        # COM sudden changes of speed while a foot is down
        acc = br.accel_series(com, fps, span=3)
        grounded = [a for i, a in enumerate(acc, start=3) if flags["l"][i] or flags["r"][i]]
        out["com_accel_max_m_s2"] = round(max(grounded), 1) if grounded else 0.0
        # standing on one foot: is the weight over it?
        if standing_still and not _has(name, AIR_OK + GAIT + ATTACK + SUPPORTED):
            # static balance only: a moving body falls into its next step on purpose
            worst, worst_side = 0.0, ""
            for i in range(n):
                down = [sd for sd in "lr" if flags[sd][i]]
                if len(down) != 1:
                    continue
                j = min(i + 1, n - 1)
                if i == j or br.length(br.sub(com[j], com[i])) * fps > 0.25:
                    continue
                sd = down[0]
                pts = [s.world[i][k] for k in (f"ankle_{sd}", f"ball_{sd}", f"toe_{sd}") if k in s.world[i]]
                if pts:
                    d = mm.outside_support(com[i], pts)
                    if d > worst:
                        worst, worst_side = d, sd
            out["one_foot_off_balance_m"] = round(worst, 3)
            out["one_foot_side"] = worst_side
    # ---- gait: arms against legs, chest against hips ----
    if _has(name, GAIT) and hl and hr:
        al, ar = _pts(s, "ankle_l"), _pts(s, "ankle_r")
        wl = _first(s, "pt:hand_l", "tip:lowerarm_l")
        wr2 = _first(s, "pt:hand_r", "tip:lowerarm_r")
        fwd = [br.unit(br.cross(br.UP, br.flat(br.sub(hr[i], hl[i])))) for i in range(n)]
        if al and ar and wl and wr2:
            leg = [br.dot(br.sub(al[i], ar[i]), fwd[i]) for i in range(n)]
            arm = [br.dot(br.sub(wl[i], wr2[i]), fwd[i]) for i in range(n)]
            out["arm_leg_corr"] = round(br.correlation(arm, leg), 2)
            out["arm_swing_m"] = round(br.spread(arm), 3)
            out["leg_swing_m"] = round(br.spread(leg), 3)
        sl, sr = _pts(s, "pt:upperarm_l"), _pts(s, "pt:upperarm_r")
        if sl and sr:

            def yaw(a: list[tuple], b: list[tuple]) -> list[float]:
                ys = [math.degrees(math.atan2(b[i][1] - a[i][1], b[i][0] - a[i][0])) for i in range(n)]
                return [(y - ys[0] + 180) % 360 - 180 for y in ys]

            py, cy = yaw(hl, hr), yaw(sl, sr)
            out["chest_hip_corr"] = round(br.correlation(cy, py), 2)
            out["hip_turn_deg"] = round(br.spread(py), 1)
            out["chest_turn_deg"] = round(br.spread(cy), 1)
    # ---- spacing: a part gliding at one steady velocity (linear in-betweens) ----
    hp = _pts(s, "pt:hips") or _pts(s, "hips")
    if hp:
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
                rel = [br.sub(p[i], hp[i]) for i in range(n)]
                r = R.linear_run(rel, fps, [q[2] < floor_z + R.GROUND_TOL for q in p])
                if r[0]:
                    runs[label] = r
        # the hips against the root bone: a travelling clip moves the whole body at the game speed
        rb = _pts(s, "rootbone")
        r = R.linear_run([br.sub(hp[i], rb[i]) for i in range(n)] if rb and rb[0] != hp[0] else hp, fps)
        if r[0]:
            runs["hips"] = r
        out["linear_runs"] = runs
        # ---- leaning sideways in a walk or run (clamped, or it looks drunk) ----
        top = _first(s, "pt:neck", "pt:head")
        if _has(name, GAIT) and top and hl and hr:
            turning = any(w in TURN_WORDS for w in words_of(name))
            rb = _pts(s, "rootbone")
            path = rb if rb and rb[0] != hp[0] and travels else (hp if travels else None)
            if path is not None or not turning:
                need = R.turn_lean_deg(path, fps) if path is not None else None
                out["lean"] = R.lean_measure(R.side_lean_deg(hp, top, hl, hr), need)
                out["lean"]["turning"] = turning
        # ---- overlap: in an idle, the head and hands trail the hips' bob ----
        if cyclic and "idle" in name.lower() and not _has(name, ("sit", "driv", "lying", "sleep")):
            m = n - 1 if n > 2 else n  # a loop's last frame repeats the first
            parts = {
                lab: [p[i][2] for i in range(m)]
                for lab, key in (("head", "pt:head"), ("hands", "pt:hand_l"))
                if (p := _pts(s, key))
            }
            out["block_bob"] = R.block_verdicts([hp[i][2] for i in range(m)], parts, fps)
    # ---- attacks: anticipation, hit, recovery, wind-up, kinetic chain ----
    if _has(name, ATTACK):
        best: dict = {}
        best_key = ""
        for key in ("tip:hand_l", "tip:hand_r", "tip:lowerarm_l", "tip:lowerarm_r", "toe_l", "toe_r"):
            p = _pts(s, key)
            if p is None:
                continue
            st = br.strike(p, fps)
            if st and st["peak_speed_m_s"] > best.get("peak_speed_m_s", 0):
                best, best_key = st, key
        if best:
            best["effector"] = best_key.split(":")[-1]
            best["path_corners"] = R.path_corners(_pts(s, best_key) or [], fps)
            keys = [
                k
                for k in ("hips", "pt:spine3", "pt:head", "tip:hand_l", "tip:hand_r", "toe_l", "toe_r")
                if k in s.world[0]
            ]
            tell = R.tell_s(br.speeds(_pts(s, best_key) or [], fps), fps, [[w[k] for k in keys] for w in s.world])
            best["tell_s"] = None if tell is None else round(tell, 3)
            # A draw-back is against the body (the path relative to the hips), as for animals: when the
            # fastest burst is a wind-up and the strike is a later burst going the other way, note both.
            hp, ep = _pts(s, "hips"), _pts(s, best_key)
            if hp and ep:
                split = R.split_windup([tuple(p - q for p, q in zip(e, h)) for e, h in zip(ep, hp)], fps)
                if split:
                    best["windup_split"] = split
            out["strike"] = best
            if chest:
                q0 = s.world_q[0][chest]
                best["chest_turn_deg"] = round(max(mm.q_angle_deg(q0, q[chest]) for q in s.world_q), 1)
            side = best_key[-1]
            chain = [
                roles.get(r)
                for r in ("hips", "spine3" if "spine3" in roles else "spine2", f"upperarm_{side}", f"lowerarm_{side}")
            ]
            if all(chain) and ("hand" in best_key or "lowerarm" in best_key):
                peaks = []
                for b in chain:
                    if b is None:
                        continue
                    ang = [mm.q_angle_deg(s.world_q[i][b], s.world_q[i + 1][b]) for i in range(n - 1)]
                    peaks.append(br.peak_frame(ang))
                hand_sp = br.speeds(_pts(s, best_key) or [], fps)
                best["chain_peaks"] = [*peaks, br.peak_frame(hand_sp)]
            lsp = br.speeds(_pts(s, best_key) or [], fps)
            best["follow_through_s"] = R.follow_through_s(lsp, fps)
            core = _first(s, "pt:spine3", "pt:spine2", "pt:neck", "pt:hips")
            if core and lsp:
                best["body_follow_s"] = R.follow_through_s(br.speeds(core, fps), fps, R.hit_end(lsp))
    return out


def _issues(b: dict, name: str, feet_off_ground: bool, fps: float) -> list[tuple[str, float, str]]:
    """(key, size, message) for every problem in one measurement. Bigger size = worse."""
    out: list[tuple[str, float, str]] = []
    side_word = {"l": "left", "r": "right"}
    for side in "lr":
        k = b.get(f"knee_{side}")
        if k:
            if k["backward_frames"]:
                out.append(
                    (
                        f"knee_back_{side}",
                        k["worst_backward_deg"],
                        f"FAIL {side_word[side]} knee bends backwards ({k['worst_backward_deg']:.0f} degrees, "
                        f"{len(k['backward_frames'])} frames). A knee is a hinge: it only folds forward.",
                    )
                )
            if k["max_bend_deg"] > br.KNEE_FOLD_FAIL:
                out.append(
                    (
                        f"knee_fold_{side}",
                        k["max_bend_deg"],
                        f"FAIL {side_word[side]} knee folds {k['max_bend_deg']:.0f} degrees: past a full squat "
                        "(about 155), so the shin is passing through the thigh.",
                    )
                )
            if k["worst_sideways_deg"]:
                out.append(
                    (
                        f"knee_side_{side}",
                        k["worst_sideways_deg"],
                        f"WARN {side_word[side]} knee bends sideways ({k['worst_sideways_deg']:.0f} degrees off "
                        "its hinge): knees don't bend side to side; turn the thigh instead.",
                    )
                )
        e = b.get(f"elbow_{side}")
        if e:
            if e["backward_frames"]:
                out.append(
                    (
                        f"elbow_back_{side}",
                        e["worst_backward_deg"],
                        f"FAIL {side_word[side]} elbow bends the wrong way ({e['worst_backward_deg']:.0f} degrees, "
                        f"{len(e['backward_frames'])} frames). An elbow is a hinge: it only folds one way.",
                    )
                )
            if e["max_bend_deg"] > br.ELBOW_FOLD_FAIL:
                out.append(
                    (
                        f"elbow_fold_{side}",
                        e["max_bend_deg"],
                        f"FAIL {side_word[side]} elbow folds {e['max_bend_deg']:.0f} degrees: an elbow stops "
                        "at about 150, where the forearm meets the upper arm.",
                    )
                )
            if e["worst_sideways_deg"]:
                out.append(
                    (
                        f"elbow_side_{side}",
                        e["worst_sideways_deg"],
                        f"WARN {side_word[side]} elbow bends sideways ({e['worst_sideways_deg']:.0f} degrees off "
                        "its hinge): twist the forearm or turn the shoulder instead.",
                    )
                )
        w = b.get(f"wrist_{side}")
        if w and w["bend_deg"] > br.WRIST_BEND_FAIL:
            out.append(
                (
                    f"wrist_{side}",
                    w["bend_deg"],
                    f"FAIL {side_word[side]} wrist bends {w['bend_deg']:.0f} degrees: a wrist manages about "
                    "80 forward, 70 back, 30 to the side.",
                )
            )
    nk = b.get("neck")
    if nk and (nk["bend_deg"] > br.NECK_TURN_FAIL or nk["twist_deg"] > br.NECK_TURN_FAIL):
        out.append(
            (
                "neck",
                max(nk["bend_deg"], nk["twist_deg"]),
                f"FAIL head turns {max(nk['bend_deg'], nk['twist_deg']):.0f} degrees against the chest: a neck "
                "turns about 80 and nods about 60. Turn the chest and shoulders too.",
            )
        )
    sp = b.get("spine")
    if sp:
        if sp["twist_deg"] > br.SPINE_TWIST_FAIL:
            out.append(
                (
                    "spine_twist",
                    sp["twist_deg"],
                    f"FAIL chest twists {sp['twist_deg']:.0f} degrees against the hips: a spine twists about "
                    "45-60. Turn the hips or step round instead.",
                )
            )
        if sp["bend_deg"] > br.SPINE_BEND_FAIL:
            out.append(
                (
                    "spine_bend",
                    sp["bend_deg"],
                    f"FAIL chest bends {sp['bend_deg']:.0f} degrees against the hips: past what a spine does "
                    "(about 90). Bend at the hips for the rest.",
                )
            )
    if b.get("hip_extension_deg", 0) > br.HIP_EXTENSION_WARN:
        out.append(
            (
                "hip_ext",
                b["hip_extension_deg"],
                f"WARN a thigh swings {b['hip_extension_deg']:.0f} degrees behind the pelvis: a hip extends about "
                "20 walking and 30 sprinting. Tilt the pelvis forward to get more.",
            )
        )
    air_ok = _has(name, AIR_OK) or feet_off_ground
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
    if _has(name, RUNNING) and "airborne_frames" in b and b["airborne_frames"] == 0 and not feet_off_ground:
        out.append(
            (
                "no_flight",
                1.0,
                "WARN a run with no moment where both feet are off the ground: it reads as "
                "a fast walk. A run leaves the ground on every step.",
            )
        )
    for g in b.get("air_gravity_m_s2", []):
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
    for v in R.hang_verdicts(b.get("hang_share", [])):
        out.append(("hang", 1 - min(b["hang_share"]), v))
    ln_ = b.get("lean")
    if ln_:
        for v in R.lean_verdicts(ln_, ln_.get("turning", False)):
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
    if b.get("one_foot_off_balance_m", 0) > 0.08:
        sd = {"l": "left", "r": "right"}.get(b.get("one_foot_side", ""), "one")
        out.append(
            (
                "one_foot",
                b["one_foot_off_balance_m"],
                f"WARN standing on the {sd} foot with the weight {b['one_foot_off_balance_m'] * 100:.0f} cm off "
                "it: shift the hips over the standing foot before the other one lifts (weight shifts lead).",
            )
        )
    spm = b.get("steps_per_min")
    walking = spm and _has(name, ("walk",)) and not _has(name, RUNNING) and b.get("airborne_frames", 0) == 0
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
    for v in R.linear_verdicts({k: tuple(r) for k, r in b.get("linear_runs", {}).items()}, fps):
        out.append(("linear", max(r[0] for r in b["linear_runs"].values()), v))
    for v in b.get("block_bob", []):
        out.append(("block", 1.0, v))
    st = b.get("strike")
    nice = ""
    if st:
        eff = st["effector"]
        part = eff[:-2].replace("lowerarm", "forearm") if eff[-2:] in ("_l", "_r") else eff
        side = "left " if eff.endswith("_l") else "right " if eff.endswith("_r") else ""
        nice = f"the {side}{part}'s strike"
    if st and R.is_enemy(name):  # an enemy's attack must give the player time to react
        for v in R.reaction_verdicts(st.get("tell_s"), nice):
            out.append(("tell", st.get("tell_s") or 0.0, v))
    if st:
        # the fastest move was a draw-back going the other way, faster than the hit (as for animals, 0.8)
        for v in R.windup_outruns_verdicts(st.get("windup_split"), nice):
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
            out.append(("arc", len(st["path_corners"]), R.arc_verdicts(st["path_corners"], f"the {st['effector']}")[0]))
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
    return [_misread(k, v, m) for k, v, m in out]


MISREAD_NOTE = (
    " Past anything a body can do: a broken clip (a mirrored bone) or GaitKeeper misreading the rig "
    "gives this. Measure the joint on the bones before blaming the clip."
)


def _misread(key: str, size: float, msg: str) -> tuple[str, float, str]:
    """A reading past what any body could do: still the clip's FAIL (a mirrored knee is a real fault), with a note
    to rule out the tool first. When most clips of a pack read it, misread_verdicts() blames the rig reading."""
    k = br.misread_key(key)
    if k is None or size <= br.MISREAD_DEG[k]:
        return key, size, msg
    return key, size, msg + MISREAD_NOTE


def misread_verdicts(clip_verdicts: dict[str, list[str]]) -> list[str]:
    """Rig-level TOOL? lines: the same reading no body could make in most clips of a file or pack (3+ clips, 60 %+)
    is the tool misreading the rig, not every clip being broken (12 Nov 2026: every Kevin Iglesias clip)."""
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
