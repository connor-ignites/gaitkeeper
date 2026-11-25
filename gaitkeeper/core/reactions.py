# SPDX-License-Identifier: GPL-3.0-or-later
"""How the loose parts of a hopping (or running) body react: head, arms, tail. No Blender here.

Two ways it goes wrong, both seen in review of a kangaroo hop:
- locked: the head, arms and tail ride along on the body as if bolted on ("the arms locked pose,
  the head and neck stiffness on jumps, none of it reacts with each other");
- floppy: they swing on loose springs and wobble back and forth ("now it just flops about").

What the reference footage shows (red and grey kangaroos, side and front on, 8 Nov 2026):
- the head keeps its gaze: its pitch in the world stays within a few degrees while the body bounces,
  with one small nod as the feet land;
- the forearms stay tucked at the chest and move a little with each landing, one way and back;
- the tail is a stiff lever: it swings up while the legs swing forward in the air and down at
  landing (against the legs, so the body doesn't spin), and it doesn't wag.

Every series here is one loop of a cyclic clip, one value per frame, in degrees.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# limits, per hop
HEAD_WORLD_PITCH_MAX = 14.0  # the head's pitch in the world may move this much, peak to peak
WOBBLE_MAX_TURNS = 2  # a part may change direction this many times a hop (once up, once back)
WOBBLE_HYST = 1.5  # degrees: smaller back-and-forth is noise, not a wobble
ARM_SWING_MAX = 24.0  # forearm tucked at the chest: this much swing, peak to peak, at most
LOCKED_MIN = 1.5  # less than this, peak to peak, reads as bolted on
TAIL_COUNTER_MIN = 0.3  # the tail should move against the legs at least this strongly (correlation)


def peak_to_peak(a: Sequence[float]) -> float:
    return (max(a) - min(a)) if a else 0.0


def unwrap(a: Sequence[float]) -> list[float]:
    """Angles in degrees without the jump at +-180."""
    out: list[float] = []
    for x in a:
        if out:
            while x - out[-1] > 180:
                x -= 360
            while x - out[-1] < -180:
                x += 360
        out.append(x)
    return out


def turns(a: Sequence[float], hyst: float = WOBBLE_HYST) -> int:
    """How many times a cyclic series changes direction by more than `hyst` (a clean swing gives 2)."""
    n = len(a)
    if n < 3 or peak_to_peak(a) < 2 * hyst:
        return 0
    # start at the lowest point, so the count round the loop is exact
    k0 = min(range(n), key=lambda i: a[i])
    seq = [a[(k0 + i) % n] for i in range(n + 1)]
    count, going_up, ext = 0, True, seq[0]
    for x in seq[1:]:
        if going_up:
            if x > ext:
                ext = x
            elif ext - x > hyst:
                count += 1
                going_up, ext = False, x
        else:
            if x < ext:
                ext = x
            elif x - ext > hyst:
                count += 1
                going_up, ext = True, x
    if not going_up:  # back down at the start: that last turn closes the loop
        count += 1
    return count


def correlation(a: Sequence[float], b: Sequence[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    ma, mb = sum(a[:n]) / n, sum(b[:n]) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a[:n]))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b[:n]))
    if sa < 1e-9 or sb < 1e-9:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a[:n], b[:n])) / (sa * sb)


def best_lag_correlation(a: Sequence[float], b: Sequence[float], most: int) -> float:
    """The strongest negative correlation of a against b shifted by up to `most` frames (cyclic)."""
    n = min(len(a), len(b))
    best = 1.0
    for s in range(-most, most + 1):
        best = min(best, correlation(a[:n], [b[(i - s) % n] for i in range(n)]))
    return best


def measure(series: dict[str, Sequence[float]], fps: float) -> dict:
    """series keys: head_world, head_rel, arm_l, arm_r, tail, legs (any may be missing)."""
    m: dict = {}
    if "head_world" in series:
        m["head_world_pitch_deg"] = round(peak_to_peak(unwrap(series["head_world"])), 1)
    for key in ("head_rel", "arm_l", "arm_r", "tail"):
        if key in series:
            s = unwrap(series[key])
            m[key] = {"range_deg": round(peak_to_peak(s), 1), "turns": turns(s)}
    if "tail" in series and "legs" in series:
        lag = max(1, round(0.06 * fps))
        m["tail_vs_legs"] = round(best_lag_correlation(unwrap(series["tail"]), unwrap(series["legs"]), lag), 2)
    return m


def verdicts(m: dict) -> list[str]:
    out = []
    hw = m.get("head_world_pitch_deg")
    if hw is not None and hw > HEAD_WORLD_PITCH_MAX:
        out.append(
            f"WARN the head pitches {hw:.0f} degrees in the world each hop: it bobs. A hopping animal "
            f"keeps its gaze steady (under {HEAD_WORLD_PITCH_MAX:.0f}); let the neck take the body's bounce."
        )
    names = {"head_rel": "the head", "arm_l": "the left arm", "arm_r": "the right arm", "tail": "the tail"}
    for key, label in names.items():
        p = m.get(key)
        if not p:
            continue
        if p["turns"] > WOBBLE_MAX_TURNS:
            out.append(
                f"WARN {label} changes direction {p['turns']} times a hop: it wobbles (flops about). "
                "A loose part swings out and back once per hop; make it stiffer and drive it from the hop."
            )
        if p["range_deg"] < LOCKED_MIN:
            out.append(
                f"WARN {label} moves only {p['range_deg']:.1f} degrees a hop: it rides along locked. "
                "Give it a small reaction to each landing."
            )
        if key.startswith("arm") and p["range_deg"] > ARM_SWING_MAX:
            out.append(
                f"WARN {label} swings {p['range_deg']:.0f} degrees a hop: kangaroo forearms stay tucked at "
                f"the chest (under {ARM_SWING_MAX:.0f})."
            )
    tv = m.get("tail_vs_legs")
    if tv is not None and tv > -TAIL_COUNTER_MIN:
        out.append(
            "WARN the tail doesn't move against the legs: it should swing up "
            "while the legs swing forward and down as they push back, as a counterweight."
        )
    return out


# ---------- strikes (kicks, punches): power comes from spacing ----------

STOP_MIN = 0.2  # the frame after the fastest one keeps at least this share of the speed (it drives through)
STUTTER = 0.6  # mid-strike, the effector may not drop below 60% of its speed so far and then speed up again


ENEMY_WORDS = ("enemy", "npc", "boss", "mob", "foe")
REACT_S = 0.3  # a player needs about this long to react to a simple thing they see (Ghost of Tsushima, GDC)


def is_enemy(name: str) -> bool:
    """A clip for an enemy (its name says so, or the add-on's "Clips are for: Enemies")."""
    low = name.lower()
    return any(w in low for w in ENEMY_WORDS)


def tell_s(
    speeds: Sequence[float], fps: float, body: Sequence[Sequence[Sequence[float]]] | None = None, moved: float = 0.03
) -> float | None:
    """The tell of the first strike: seconds from the first visible move to the start of the hit (the
    striking hand or foot at half its top speed). The first visible move is when any body point (hips,
    chest, head, hands, feet: `body`, per frame) has moved `moved` m from where the clip began, as a
    player reads the shoulder drawing back or the weight shifting, not just the fist; without `body`,
    when the striking point itself reaches 10% of its top speed. None with no clear strike."""
    if len(speeds) < 3:
        return None
    peak = max(speeds)
    if peak <= 0:
        return None
    hit = next(i for i, v in enumerate(speeds) if v >= peak / 2)
    if body:
        start = body[0]
        first = next((i for i, pts in enumerate(body) if any(math.dist(p, q) > moved for p, q in zip(pts, start))), hit)
    else:
        first = next(i for i, v in enumerate(speeds) if v >= 0.1 * peak)
    return max(0, hit - first) / fps


def reaction_verdicts(tell: float | None, name: str = "the strike") -> list[str]:
    """An enemy's attack must be readable: players react to what they see in about 300 ms, so an enemy
    that opens with a faster attack can't be answered. A follow-up in a combo can be quicker: by then
    the player is anticipating the rhythm, not reacting (Ghost of Tsushima, GDC 2021)."""
    if tell is None or tell >= REACT_S:
        return []
    return [
        f"WARN {name} gives {tell * 1000:.0f} ms from its first move to the hit: players need about "
        f"{REACT_S * 1000:.0f} ms to react to what they see, so an enemy can't open with it (it's fine as "
        "a follow-up in a combo, or for the player's own attacks). Hold or slow the wind-up."
    ]


def strike_verdicts(speeds: Sequence[float], name: str = "the strike") -> list[str]:
    """speeds: the striking foot or hand, m/s per frame. Catches the two things that made the
    kangaroo's tail kick feel weightless: a dead stop at full speed and a stutter on the way in."""
    if len(speeds) < 4 or max(speeds) < 2.0:
        return []
    out = []
    peak = max(range(len(speeds)), key=lambda i: speeds[i])
    top = speeds[peak]
    end = peak  # the last frame of the fast part
    while end + 1 < len(speeds) and speeds[end + 1] >= 0.5 * top:
        end += 1
    after = speeds[end + 1] if end + 1 < len(speeds) else speeds[end]
    if after < STOP_MIN * speeds[end]:
        out.append(
            f"WARN {name} arrives at {speeds[end]:.1f} m/s and stops dead the next frame ({after:.1f} m/s): "
            "it reads as "
            "robotic, with no weight. Drive through the target and slow over 2-3 frames."
        )
    start = peak
    while start > 0 and speeds[start - 1] > 0.25 * top:
        start -= 1
    run = speeds[start : peak + 1]
    for i in range(1, len(run) - 1):
        before = max(run[:i])
        if run[i] < STUTTER * before and run[i + 1] > before:
            out.append(
                f"WARN {name} stutters: it slows to {run[i]:.1f} m/s mid-strike, then speeds up again. "
                "Load up before it starts (a coil), then let it accelerate all the way into the hit."
            )
            break
    return out


# ---------- harsh corners: a fast hand or foot that turns sharply between two frames ----------

ARC_CORNER_DEG = 60.0  # a fast-moving foot or hand may not change direction by more than this in one frame
# Calibrated 8 Nov 2026: at 24-30 fps a toe peeling off the ground, a foot landing or a launch from a
# held coil turns 60-175 deg in one frame at 1.5-6 m/s in clips that passed review (kangaroo Hop, Run,
# HopSlow) and in good Quaternius UAL clips (Jog, Sprint, Jump_Start, Roll at up to 8.7 m/s). Only
# faster than that does a corner mean a broken, key-to-key path: the UAL Sword_Attack hand turns
# 61-72 deg a frame at 14-24 m/s (about a metre a frame: a polygon, not an arc).
ARC_MIN_SPEED = 9.0  # m/s on both sides of the frame


def path_corners(
    points: Sequence[Sequence[float]], fps: float, min_speed: float = ARC_MIN_SPEED, limit: float = ARC_CORNER_DEG
) -> list[int]:
    """Frames where a moving part (a foot, a hand) changes direction by more than `limit` degrees in
    one frame while moving fast on both sides of it: a corner in its path. A living limb travels on
    arcs and slows down to turn; a sharp corner at speed is two straight key-to-key lines meeting."""
    out = []
    for k in range(1, len(points) - 1):
        a = [points[k][i] - points[k - 1][i] for i in range(3)]
        b = [points[k + 1][i] - points[k][i] for i in range(3)]
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
        if min(na, nb) * fps < min_speed:
            continue
        c = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (na * nb)))
        if math.degrees(math.acos(c)) > limit:
            out.append(k)
    return out


def arc_verdicts(corners: Sequence[int], name: str) -> list[str]:
    if not corners:
        return []
    msg = (
        f"WARN {name} turns a sharp corner at speed on frames {list(corners)[:6]}: its path should be an arc "
        "that slows into a change of direction. Round the path (add a breakdown key on the arc)."
    )
    return [msg]


# ---------- the striking foot of a hopper's kick ----------
# Review note on a tail kick: "the feet are still angled down wrong". Attempt 4 curled the
# toes 22 degrees down so "the claws lead". The footage says otherwise (measured 8 Nov 2026 on
# gridded close-ups): at the hit the long foot carries on the line of the shin or tips UP from it,
# about +21 deg in the BBC boxing pair (m05, frame 20) and about +11 deg in the jump kick (m17,
# frame 11), the toes stay straight along the foot, and the sole and claw tips push through the
# target. Only a foot that is NOT striking hangs with its toes pointing down.
# Angles are signed in the leg's own plane: + closes the ankle the way it is closed when standing
# (the foot tips up from the shin line in a kick), - opens it past straight (tips down).

ANKLE_AT_HIT_MIN = -5.0  # degrees: the striking foot may not tip down past the shin line more than this
ANKLE_AT_HIT_MAX = 45.0  # nor fold up so far that the heel, not the claws and sole, meets the target
TOE_CURL_MAX = 12.0  # the toes stay within this of their rest line along the foot at the hit


def _signed(u: Sequence[float], v: Sequence[float], axis: Sequence[float]) -> float:
    vp = [v[i] - axis[i] * sum(v[j] * axis[j] for j in range(3)) for i in range(3)]
    c = [u[1] * vp[2] - u[2] * vp[1], u[2] * vp[0] - u[0] * vp[2], u[0] * vp[1] - u[1] * vp[0]]
    return math.degrees(math.atan2(sum(c[i] * axis[i] for i in range(3)), sum(u[i] * vp[i] for i in range(3))))


def foot_angles(
    shin: Sequence[Sequence[float]],
    foot: Sequence[Sequence[float]],
    toe: Sequence[Sequence[float]],
    rest: tuple[Sequence[float], Sequence[float], Sequence[float]],
) -> tuple[list[float], list[float]]:
    """shin, foot, toe: per frame, each bone's direction (knee to hock, hock to toe joint, toe joint
    to claw tip) in the SHIN's own frame, so swinging the whole leg changes nothing. rest: the same
    three in the rest pose. Returns per frame the ankle angle (+ foot tipped up from the shin line,
    the way a standing ankle closes; 0 in line; - tipped down past it) and the toe curl against its
    rest line (- curled down toward the sole, + bent up)."""
    rs, rf, rt = rest
    axis = [rs[1] * rf[2] - rs[2] * rf[1], rs[2] * rf[0] - rs[0] * rf[2], rs[0] * rf[1] - rs[1] * rf[0]]
    n = math.sqrt(sum(x * x for x in axis))
    if n < 1e-9:
        return [0.0] * len(shin), [0.0] * len(shin)
    axis = [x / n for x in axis]  # the ankle's hinge: standing, the foot turns from the shin about it by +
    toe_rest = _signed(rf, rt, axis)
    ankle = [_signed(s, f, axis) for s, f in zip(shin, foot)]
    curl = [_signed(f, t, axis) - toe_rest for f, t in zip(foot, toe)]
    return ankle, curl


def strike_foot_verdicts(
    ankle: Sequence[float], curl: Sequence[float], hit: Sequence[int], name: str = "the kicking foot"
) -> list[str]:
    """hit: the frames of contact (the fast part of the strike and the push through)."""
    if not hit:
        return []
    out = []
    a = [ankle[k] for k in hit]
    c = [curl[k] for k in hit]
    if min(a) < ANKLE_AT_HIT_MIN:
        out.append(
            f"WARN {name} tips DOWN {-min(a):.0f} deg past the shin line at the hit: in real footage the foot "
            "carries on the shin's line or tips up 10-20 deg, so the sole and claw tips drive into the target. "
            "A pointed foot reads as limp."
        )
    if max(a) > ANKLE_AT_HIT_MAX:
        out.append(
            f"WARN {name} folds up {max(a):.0f} deg from the shin at the hit: the heel leads instead of the "
            "sole and claws. Open the ankle toward the shin's line (10-20 deg up)."
        )
    worst = min(c, key=lambda x: -abs(x))
    if abs(worst) > TOE_CURL_MAX:
        way = "down" if worst < 0 else "up"
        out.append(
            f"WARN the toes of {name} curl {way} {abs(worst):.0f} deg at the hit: in real footage they stay "
            "straight along the foot, claw tips first."
        )
    return out


# ---------- spacing and overlap (8 Nov 2026, from animation-polish videos) ----------
# AnimMonks (timing, spacing and arcs): equal spacing between keys reads mechanical; a move eases
# out of one pose and into the next. Aaron Blaise (four tips for weight): weight comes from contrast,
# fast then slow, never one steady rate. New Frame Plus (follow-through and overlapping action): a
# body that moves and stops all at once looks stiff; motion ripples out from the core, the
# shoulders a frame or two behind the torso, the hands a frame behind that, the loose bits last.

LINEAR_MIN_SPEED = 0.3  # m/s: slower parts are drifting, not moving between poses
LINEAR_DV = 0.02  # velocity may change by under 2% of the speed per frame to count as linear
LINEAR_RUN_S = 0.25  # this long at a perfectly steady velocity reads as a computer in-between
GROUND_TOL = 0.03  # m: a part within this of its lowest point counts as planted on the floor
# Calibrated 8 Nov 2026: no run of even 4 frames in the 42 good Quaternius UAL clips (every bone end,
# relative to the hips), the reviewed kangaroo Hop, Run and kick attempt 5. A known-bad
# kangaroo Walk: both hands glide at one steady velocity for 9 frames (0.3 s).


def linear_run(
    points: Sequence[Sequence[float]], fps: float, grounded: Sequence[bool] | None = None
) -> tuple[int, int]:
    """(frames, first frame) of the longest stretch where a part moves at one steady velocity
    (same speed and direction, faster than LINEAR_MIN_SPEED): linear spacing. `grounded` marks frames
    where the part is planted on the floor: a planted foot in an in-place clip slides back at the
    steady game speed by design, so those frames never count (Border Collie crouch walks)."""
    v = [[(points[i + 1][j] - points[i][j]) * fps for j in range(3)] for i in range(len(points) - 1)]
    best, start, run = 0, 0, 0
    for i in range(1, len(v)):
        sp = math.sqrt(sum(x * x for x in v[i]))
        dv = math.sqrt(sum((v[i][j] - v[i - 1][j]) ** 2 for j in range(3)))
        down = grounded is not None and (grounded[i] or grounded[i + 1])
        if sp > LINEAR_MIN_SPEED and dv < LINEAR_DV * sp and not down:
            run += 1
            if run > best:
                best, start = run, i - run
        else:
            run = 0
    return (best + 1, start) if best else (0, 0)


def linear_verdicts(runs: dict[str, tuple[int, int]], fps: float) -> list[str]:
    """runs: part -> (frames, first frame) from linear_run."""
    bad = {k: r for k, r in runs.items() if r[0] / fps >= LINEAR_RUN_S}
    if not bad:
        return []
    k, (n, f) = max(bad.items(), key=lambda kv: kv[1][0])
    others = sorted(set(bad) - {k})
    also = f" (also {', '.join(others[:3])})" if others else ""
    return [
        f"WARN {k} moves at one steady speed for {n} frames from frame {f}{also}: even spacing reads as "
        "mechanical. Ease out of the first pose and into the next (slow, fast, slow)."
    ]


OVERLAP_MIN_BOB = 0.005  # m: the hips must bob at least this much for overlap to show
OVERLAP_LOCK_CORR = 0.95  # a part following the hips this closely with no lag rides along locked
# Calibrated 8 Nov 2026 on the Quaternius UAL idles: the head trails the hips' bob by 2-6 frames
# (Idle 2, Torch 3, Talking 4, Spell 5, Crouch 6). In walks, jogs and sprints the head follows with
# no lag (the torso is stiff up and down), so this is judged on idles only.


def lag_frames(lead: Sequence[float], follow: Sequence[float], most: int) -> tuple[int, float]:
    """(lag, correlation): how many frames `follow` trails `lead` in a loop (negative: it leads)."""
    n = min(len(lead), len(follow))
    best = (0, -2.0)
    for s in range(-most, most + 1):
        c = correlation(lead[:n], [follow[(i + s) % n] for i in range(n)])
        if c > best[1] + 1e-9:
            best = (s, c)
    return best


def block_verdicts(hips_z: Sequence[float], parts_z: dict[str, Sequence[float]], fps: float) -> list[str]:
    """An idle loop whose head and hands bob with the hips on the same frame: it moves as one block."""
    if len(hips_z) < 6 or max(hips_z) - min(hips_z) < OVERLAP_MIN_BOB or not parts_z:
        return []
    most = max(2, round(fps / 4))
    for z in parts_z.values():
        lag, c = lag_frames(hips_z, z, most)
        if lag != 0 or c < OVERLAP_LOCK_CORR:
            return []
    return [
        f"WARN the {', '.join(parts_z)} bob with the hips on the same frame: the body moves as one block. "
        "Let the motion ripple up: the head and hands trail the hips by a frame or two (2-6 in good idles)."
    ]


# ---------- the root bone's path (GDC 2015, Just Cause 3: responsive high-fidelity movement) ----------
# The game moves the character's capsule along the root bone. The root should travel in a smooth
# line; the body may sway around it, but if the root copies the hips' side-to-side sway with every
# step, the capsule (and the camera on it) wobbles. Calibrated 8 Nov 2026 on the Quaternius UAL
# root-motion clips: the root sways 0.0 cm in all ten travelling clips while the hips sway 0.3-3.7 cm.

ROOT_SWAY_MAX_CM = 1.0


def side_sway_cm(points: Sequence[Sequence[float]], start: Sequence[float], end: Sequence[float]) -> float:
    """Side-to-side wobble (cm, peak to peak) of a path, across the line from start to end, after
    taking out slow curves (a moving average over 15 frames), so a curved path isn't a sway."""
    d = [end[0] - start[0], end[1] - start[1]]
    n = math.hypot(*d)
    if n < 1e-6 or len(points) < 3:
        return 0.0
    side = (-d[1] / n, d[0] / n)
    off = [(p[0] - start[0]) * side[0] + (p[1] - start[1]) * side[1] for p in points]
    k = 7
    inner = range(k, len(off) - k) if len(off) > 2 * k + 2 else range(len(off))  # full windows only
    wob = [off[i] - sum(off[max(0, i - k) : i + k + 1]) / len(off[max(0, i - k) : i + k + 1]) for i in inner]
    return 100 * (max(wob) - min(wob))


def root_sway_verdicts(root_cm: float, hips_cm: float) -> list[str]:
    if root_cm > ROOT_SWAY_MAX_CM and root_cm > 0.5 * hips_cm:
        return [
            f"WARN the root bone sways {root_cm:.1f} cm side to side with the steps (the hips {hips_cm:.1f} cm): the "
            "character's collider and the camera will wobble in a game. Keep the root on a smooth line and let "
            "the body sway around it."
        ]
    return []


# ---------- hang time: fast out of the take-off, slow over the top (8 Nov 2026) ----------
# Aaron Blaise (four tips for weight): weight reads from timing contrast. A thrown body leaves the
# ground fast and slows into the top of its arc, hangs there, then speeds up again on the way down.
# A real arc (a parabola) spends about half its flight in the top quarter of its height; a body
# moved up and down at one steady speed (a straight in-between, the "triangle" arc) spends only a
# quarter there, so it has no hang time and reads as weightless or mechanical.

HANG_TOP = 0.25  # the top quarter of the rise
HANG_MIN_SHARE = 0.28  # a parabola gives 0.44-0.5 even with a lower landing; a steady-speed arc 0.25
# Calibrated 8 Nov 2026: the kangaroo hops that passed review (Hop, Run, HopSlow attempt 4) spend 0.40-0.50
# of each flight near the top; known-bad kangaroo Hop and Run 0.33-0.36; Kelpie_Hop 0.30
# (falling at 9.6 m/s2, so a real arc cut into few frames) and Kelpie_JumpAttack 0.50.
HANG_MIN_RISE = 0.08  # m: smaller hops are too small to judge
HANG_MIN_FRAMES = 8


def hang_share(heights: Sequence[float]) -> float | None:
    """The share of a flight's frames spent in the top quarter of its rise (None if too small to judge).
    heights: the body's centre (hips or centre of mass) on each frame in the air."""
    if len(heights) < HANG_MIN_FRAMES:
        return None
    top = max(heights)
    rise = top - max(heights[0], heights[-1])
    if rise < HANG_MIN_RISE:
        return None
    band = top - HANG_TOP * rise
    return round(sum(1 for h in heights if h >= band) / len(heights), 2)


def hang_verdicts(shares: Sequence[float]) -> list[str]:
    worst = min(shares, default=1.0)
    if worst >= HANG_MIN_SHARE:
        return []
    return [
        f"WARN no hang time in the air: the body spends only {worst:.0%} of the flight near the top of its arc "
        "(a thrown body spends about half). It moves up and down at one speed. Leave the ground fast, slow into the "
        "top and hang there, then speed up on the way down (fast, slow, fast)."
    ]


# ---------- follow-through after a hit (New Frame Plus: follow-through and overlapping action) ----------
# A strike where everything stops the moment it lands reads as robotic: the body carries on past the
# hit and settles over a few frames, the core and the loose parts last. A fighting game may hold the
# fist at full stretch for a few frames on purpose (the Quaternius punches and sword swing do, and
# read fine), so the striking hand or foot alone stopping isn't a fault; the whole body stopping
# with it is. strike_verdicts already catches the limb stopping dead on the very next frame.

SETTLE_SHARE = 0.12  # a part has settled once it moves under 12% of its own peak speed
FOLLOW_MIN_S = 0.1  # something (the limb, or the body behind it) keeps moving at least this long


def hit_end(speeds: Sequence[float]) -> int:
    """The last frame of the fast part of a strike (over half the peak speed)."""
    peak = max(range(len(speeds)), key=lambda i: speeds[i])
    end = peak
    while end + 1 < len(speeds) and speeds[end + 1] >= 0.5 * speeds[peak]:
        end += 1
    return end


def follow_through_s(speeds: Sequence[float], fps: float, end: int | None = None) -> float | None:
    """Seconds a part keeps moving after the hit's fast part ends (`end`, default: this part's own
    hit) until it settles (under SETTLE_SHARE of its peak speed). None when the clip ends first."""
    if len(speeds) < 4 or max(speeds) <= 0:
        return None
    end = hit_end(speeds) if end is None else end
    top = max(speeds)
    for k in range(end + 1, len(speeds)):
        if speeds[k] < SETTLE_SHARE * top:
            return round((k - end - 1) / fps, 3)
    return None


# Calibrated 8 Nov 2026 on leg strikes: the tail kick that passed review (attempt 5) keeps the body moving
# 0.47 s after the hit; attempt 1 ("needs more coil and snap") and two known-bad kicks (GrappleKick
# and JumpKick) stop limb and body within 67 ms. People are measured but not judged: the Quaternius
# punches and sword swing stop the fist and chest together at full stretch (a fighting-game hold),
# and they are the clean baseline.


def follow_verdicts(limb_s: float | None, body_s: float | None, name: str = "the strike") -> list[str]:
    """limb_s: the striking hand or foot; body_s: the chest (or the hips) after the same hit."""
    if limb_s is None or limb_s >= FOLLOW_MIN_S or body_s is None or body_s >= FOLLOW_MIN_S:
        return []
    return [
        f"WARN {name} and the body stop together {max(limb_s, body_s) * 1000:.0f} ms after the hit: no "
        "follow-through. Let the body carry on past the target and settle over 3-6 frames, the chest and loose "
        "parts last; a short wind-up is paid for with a longer follow-through."
    ]


# ---------- leaning: clamp it, or the body looks drunk (GDC 2015, Just Cause 3) ----------
# A body leans into a turn only as much as the turn needs: tan(lean) = sideways acceleration / g.
# Leaning more, or listing to one side on a straight line, reads as drunk or falling over.

LEAN_LIST_MAX = 8.0  # degrees: the average sideways lean of a straight walk or run (a list to one side)
LEAN_EXCESS_MAX = 15.0  # degrees: the most the body may lean beyond what the turn needs, on any frame


def side_lean_deg(
    low: Sequence[Sequence[float]],
    high: Sequence[Sequence[float]],
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
) -> list[float]:
    """Per frame, how far the body leans sideways (degrees, + toward its right): the line from `low`
    (the hips) to `high` (the neck or head) against straight up, across the body (left to right hip)."""
    out = []
    for lo, hi, a, b in zip(low, high, left, right):
        side = [b[0] - a[0], b[1] - a[1]]
        n = math.hypot(*side)
        if n < 1e-9:
            out.append(0.0)
            continue
        v = [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]]
        across = (v[0] * side[0] + v[1] * side[1]) / n
        out.append(math.degrees(math.atan2(across, max(1e-9, v[2]))))
    return out


def turn_lean_deg(path: Sequence[Sequence[float]], fps: float, span: int = 3) -> list[float]:
    """Per frame, the lean a turn needs (degrees, + toward the right of travel): atan(sideways
    acceleration / g), from the path the body travels (the root bone). 0 on a straight line."""
    n = len(path)
    out = [0.0] * n
    for i in range(span, n - span):
        v1 = [(path[i][j] - path[i - span][j]) * fps / span for j in range(2)]
        v2 = [(path[i + span][j] - path[i][j]) * fps / span for j in range(2)]
        v = [(v1[j] + v2[j]) / 2 for j in range(2)]
        sp = math.hypot(*v)
        if sp < 0.3:
            continue
        a = [(v2[j] - v1[j]) * fps / span for j in range(2)]
        right = (v[1] / sp, -v[0] / sp)
        out[i] = math.degrees(math.atan2(a[0] * right[0] + a[1] * right[1], 9.81))
    if n > 2 * span:  # the ends carry the nearest measured lean
        out[:span] = [out[span]] * span
        out[n - span :] = [out[n - span - 1]] * span
    return out


def lean_measure(lean: Sequence[float], need: Sequence[float] | None = None) -> dict:
    need = need or [0.0] * len(lean)
    extra = [x - y for x, y in zip(lean, need)]
    return {
        "mean_deg": round(sum(extra) / len(extra), 1) if extra else 0.0,
        "excess_deg": round(max((abs(x) for x in extra), default=0.0), 1),
        "range_deg": round(peak_to_peak(lean), 1),
    }


def lean_verdicts(m: dict, turning: bool) -> list[str]:
    out = []
    if not turning and abs(m["mean_deg"]) > LEAN_LIST_MAX:
        way = "right" if m["mean_deg"] > 0 else "left"
        out.append(
            f"WARN the body lists {abs(m['mean_deg']):.0f} degrees to the {way} the whole time on a straight line: "
            "it reads as drunk or injured. Stand the spine up over the hips."
        )
    elif m["excess_deg"] > LEAN_EXCESS_MAX:
        out.append(
            f"WARN the body leans {m['excess_deg']:.0f} degrees further sideways than the move needs: it looks "
            "drunk or about to fall. Clamp the lean to what the turn's speed asks for (a few degrees walking)."
        )
    return out


# ---------- an animal's strikes with its arms, claws or jaws (0.8) ----------
# Learned 10 Nov 2026 from a punch-biomechanics video (hips turn, pull the shoulders, then the arm
# pops), a fighting-game director's attack breakdown (snap to the wind-up pose is fine for a player
# move; the pose at the hit must be crisp; the recovery uses its time) and frame-by-frame wolf bites
# from an open-world game (the front legs brake and the head drops first, the mouth opens before
# contact, the body brings the head, then it pulls back with its weight). Calibrated on the Border
# Collie pack's bites (good) and a kangaroo and kelpie with known faults.

UPPER_STRIKE = ("punch", "jab", "swipe", "claw", "slash", "maul", "box", "bite", "attack", "headbutt", "snap")
NOT_A_STRIKE = ("hit", "scratch", "react", "death", "die", "dead", "hurt", "stagger")
CHAIN_LEAD_FRAMES = 2  # the striking point may peak at most this many frames before the body behind it
JAW_OPEN_MIN = 8.0  # degrees: a bite opens its mouth at least this far on the way in
JAW_LATE_S = 0.15  # the widest gape may come at most this long after the hit starts


def is_upper_strike(name: str) -> bool:
    """A clip named as a strike with the arms, claws or jaws (not a hit reaction or a scratch)."""
    low = name.lower()
    return any(w in low for w in UPPER_STRIKE) and not any(w in low for w in NOT_A_STRIKE)


def chain_verdicts(peaks: Sequence[int], name: str = "the strike") -> list[str]:
    """peaks: the frame each joint is fastest, from the body (first) out to the striking point (last).
    Power runs from the body out; a point fastest well before the body behind it is an arm (or neck)
    swinging on its own, with the body catching up afterwards."""
    if len(peaks) < 2:
        return []
    body = max(peaks[:-1])
    if peaks[-1] + CHAIN_LEAD_FRAMES >= body:
        return []
    return [
        f"WARN {name} is fastest {body - peaks[-1]} frames before the body behind it moves hardest: it swings on "
        "its own and the body catches up after. Let the body drive it: the chest (or the lunge) first, then the "
        "shoulder or neck, the claws or jaws last, each a frame or two after the last."
    ]


def windup_verdicts(stats: dict, name: str = "the strike") -> list[str]:
    """No lead-in at all: a big strike from the first frame (the same rule as for people)."""
    if stats.get("reach_m", 0) > 0.4 and stats.get("windup_m", 1) < 0.03 and stats.get("anticipation_s", 1) < 0.05:
        return [
            f"WARN {name} hits {stats['reach_m']:.2f} m from the first frame with no wind-up: draw back (or drop "
            "and brace, for a bite) first, even for a few frames, or a blend from idle jumps straight into the hit."
        ]
    return []


def jaw_verdicts(open_deg: Sequence[float], hit_start: int, fps: float, name: str = "the bite") -> list[str]:
    """open_deg: how far the mouth is open each frame (degrees from its rest angle). A bite opens on the
    way in and closes on the target: shut all through the strike, or gaping only after the hit, reads as
    a head-butt."""
    if not open_deg:
        return []
    by = min(len(open_deg), hit_start + round(JAW_LATE_S * fps) + 1)  # on the way in, up to just after it starts
    early = max(open_deg[:by], default=0.0)
    if early >= JAW_OPEN_MIN:
        return []
    widest = max(range(len(open_deg)), key=lambda i: open_deg[i])
    if open_deg[widest] < JAW_OPEN_MIN:
        return [
            f"WARN {name}: the mouth stays shut (opens {open_deg[widest]:.0f} degrees at most). Open the jaw on "
            "the way in and close it on the target."
        ]
    return [
        f"WARN {name}: the mouth only opens {(widest - hit_start) / fps * 1000:.0f} ms after the strike starts, "
        "too late to bite with. Open it as the head drives in and close it at the hit."
    ]


WINDUP_OPPOSITE_COS = -0.3  # a burst this far against the next one is drawing back for it
WINDUP_FASTER = 1.15  # a wind-up this much faster than its strike steals the hit


def bursts(speeds: Sequence[float], frac: float = 0.5) -> list[tuple[int, int]]:
    """Runs of frames (speed indices, first and last) where a part moves at over `frac` of its top speed."""
    if not speeds:
        return []
    cut = frac * max(speeds)
    out, start = [], None
    for i, v in enumerate(speeds):
        if v >= cut and start is None:
            start = i
        elif v < cut and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(speeds) - 1))
    return out


def split_windup(points: Sequence[Sequence[float]], fps: float) -> dict | None:
    """When the fastest burst is a draw-back (a claw lifted high before it swipes down), the strike is the
    later burst that goes the other way. Returns the two bursts (point indices) and their top speeds, or
    None when the fastest burst is the strike itself."""
    sp = [math.dist(points[i + 1], points[i]) * fps for i in range(len(points) - 1)]
    runs = bursts(sp)
    if len(runs) < 2:
        return None
    top = max(range(len(runs)), key=lambda k: max(sp[runs[k][0] : runs[k][1] + 1]))
    a0, a1 = runs[top]
    da = [q - p for p, q in zip(points[a0], points[a1 + 1])]
    for b0, b1 in runs[top + 1 :]:
        db = [q - p for p, q in zip(points[b0], points[b1 + 1])]
        na, nb = math.hypot(*da), math.hypot(*db)
        if na < 1e-6 or nb < 0.2:
            continue
        if sum(x * y for x, y in zip(da, db)) / (na * nb) < WINDUP_OPPOSITE_COS:
            return {
                "windup": (a0, a1),
                "strike": (b0, b1),
                "windup_m_s": round(max(sp[a0 : a1 + 1]), 2),
                "strike_m_s": round(max(sp[b0 : b1 + 1]), 2),
                "windup_m": round(na, 3),
            }
    return None


def windup_outruns_verdicts(split: dict | None, name: str = "the strike") -> list[str]:
    if not split or split["windup_m_s"] < WINDUP_FASTER * split["strike_m_s"]:
        return []
    return [
        f"WARN {name}: the wind-up ({split['windup_m_s']:.1f} m/s) is faster than the strike itself "
        f"({split['strike_m_s']:.1f} m/s), so the draw-back reads as the attack and the hit looks weak. Draw back "
        "slower (a held coil), then make the strike the fastest move in the clip."
    ]
