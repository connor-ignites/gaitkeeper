# SPDX-License-Identifier: GPL-3.0-or-later
"""How a human body can and can't move, as measurements. Pure Python (no Blender, no numpy).

Every limit here is a measured range (anatomy, balance, gait, physics, game attack timing), with
its source or typical values noted beside it.
Positions are (x, y, z) in metres, Z up. Quaternions are (w, x, y, z).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Vec = tuple[float, float, float]
Quat = tuple[float, float, float, float]


# Anatomy limits (degrees). FAIL = no human joint does this; WARN = past the normal adult range.
KNEE_FOLD_FAIL = 165.0  # deep squat is about 150-160 degrees of knee flexion
ELBOW_FOLD_FAIL = 160.0  # elbow flexion stops at about 145-150 (the biceps meets the forearm)
HINGE_BACKWARD_FAIL = 15.0  # a knee bent this far the wrong way (knee hyperextension is 0-10)
ELBOW_BACKWARD_FAIL = 20.0  # elbows hyperextend more (0-15, some people 20)
HINGE_SIDEWAYS_WARN = 30.0  # a shin leaving the knee's hinge plane (a knee buckling sideways)
ELBOW_SIDEWAYS_WARN = 70.0  # forearms: a turned shoulder looks the same, so only extreme cases
NECK_TURN_FAIL = 95.0  # head against chest: turn about 80, nod about 50-70
SPINE_TWIST_FAIL = 80.0  # chest against hips about the spine: 40-60 normal
SPINE_BEND_FAIL = 110.0  # chest against hips, bending: 80-90 normal (more comes from the hips)
WRIST_BEND_FAIL = 100.0  # hand against forearm: flex 80, extend 70, side 20-30
HIP_EXTENSION_WARN = 50.0  # thigh behind the trunk: 10-20 walking, about 30 sprinting
OFF_BALANCE_WARN_M = 0.08  # the body's weight this far outside the planted feet would tip it over

# Readings no body could make, even a broken clip: past these the tool is more likely misreading the rig (bone
# directions, rest pose, a root turn) than the clip being wrong. On one commercial pack every clip read upside
# down, and Unity's Starter Assets walk read "knee bends backwards 73 degrees" and a thigh "swung 180": all
# tool misreads.
# A clip's FAIL past these gets a note (measure on the bones first); the same one in most clips of a pack is a
# rig-level "TOOL?" (body.misread_verdicts). Size alone can't tell: a mirrored knee is a real fault at 60-70.
MISREAD_DEG = {
    "knee_back": 45.0,
    "elbow_back": 60.0,
    "neck": 150.0,
    "spine_twist": 150.0,
    "spine_bend": 170.0,
    "wrist": 160.0,
    "hip_ext": 120.0,
}


def misread_key(key: str) -> str | None:
    """The MISREAD_DEG entry an issue key falls under ("knee_back_l" -> "knee_back"), or None."""
    for k in MISREAD_DEG:
        if key == k or key.startswith(k + "_"):
            return k
    return None


# ---------- vectors ----------


def sub(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Sequence[float], k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a: Sequence[float]) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Sequence[float]) -> Vec:
    n = length(a)
    return (0.0, 0.0, 0.0) if n < 1e-9 else (a[0] / n, a[1] / n, a[2] / n)


def angle_deg(a: Sequence[float], b: Sequence[float]) -> float:
    na, nb = length(a), length(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(a, b) / (na * nb)))))


UP: Vec = (0.0, 0.0, 1.0)


def flat(a: Sequence[float]) -> Vec:
    return unit((a[0], a[1], 0.0))


# ---------- quaternions ----------


def q_mul(a: Sequence[float], b: Sequence[float]) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def q_inv(q: Sequence[float]) -> Quat:
    return (q[0], -q[1], -q[2], -q[3])


def q_rotate(q: Sequence[float], v: Sequence[float]) -> Vec:
    p = q_mul(q_mul(q, (0.0, v[0], v[1], v[2])), q_inv(q))
    return (p[1], p[2], p[3])


def swing_twist_deg(q: Sequence[float], axis: Sequence[float]) -> tuple[float, float]:
    """Split a rotation into its twist about `axis` and the swing (bend) that's left, in degrees."""
    u = unit(axis)
    proj = dot((q[1], q[2], q[3]), u)
    tw = (q[0], u[0] * proj, u[1] * proj, u[2] * proj)
    n = math.sqrt(sum(c * c for c in tw))
    if n < 1e-9:
        twist = 180.0
        tw_q: Quat = (1.0, 0.0, 0.0, 0.0)
    else:
        tw_q = (tw[0] / n, tw[1] / n, tw[2] / n, tw[3] / n)
        twist = math.degrees(2 * math.acos(min(1.0, abs(tw_q[0]))))
    sw = q_mul(q, q_inv(tw_q))
    swing = math.degrees(2 * math.acos(min(1.0, abs(sw[0]))))
    return swing, twist


def relative_turn(
    parent_rest: Sequence[float],
    child_rest: Sequence[float],
    parent_now: Sequence[float],
    child_now: Sequence[float],
    axis_rest: Sequence[float],
) -> tuple[float, float]:
    """(bend, twist) of the child against its parent, compared with the rest pose. World rotations
    in, so it works whatever bones sit between them (neck bones between chest and head).
    `axis_rest` is the long axis of the child in world space at rest (twist is about it)."""
    rel_rest = q_mul(q_inv(parent_rest), child_rest)
    rel_now = q_mul(q_inv(parent_now), child_now)
    delta = q_mul(rel_now, q_inv(rel_rest))  # expressed in the parent's frame
    axis_parent = q_rotate(q_inv(parent_rest), axis_rest)
    return swing_twist_deg(delta, axis_parent)


# ---------- hinge joints (knees, elbows) ----------


def hinge(
    prox: Sequence[Vec],
    joint: Sequence[Vec],
    dist: Sequence[Vec],
    upper_q: Sequence[Quat],
    ref_local: Sequence[float] | None = None,
    backward_limit: float = HINGE_BACKWARD_FAIL,
    sideways_limit: float = HINGE_SIDEWAYS_WARN,
) -> dict:
    """A hinge (knee, elbow) bends one way, in one plane, about an axis fixed in the upper bone.
    Everything is measured in the upper bone's own frame, so swinging the whole limb changes nothing.
    `ref_local` is the hinge axis in that frame (knees: known from the rest pose, where the feet
    point forward). Without it, the axis the clip mostly bends about is used (elbows).
    Per frame: the bend in the hinge plane (+ the right way, - the wrong way) and how far the lower
    bone leaves that plane (a sideways bend)."""
    n = len(joint)
    ul, vl = [], []
    for i in range(n):
        qi = q_inv(upper_q[i])
        ul.append(q_rotate(qi, sub(joint[i], prox[i])))
        vl.append(q_rotate(qi, sub(dist[i], joint[i])))
    acc: Vec = (0.0, 0.0, 0.0)
    for u, v in zip(ul, vl):
        bend = angle_deg(u, v)
        if bend >= 30:
            acc = add(acc, scale(unit(cross(u, v)), bend))
    ref = unit(acc)  # the axis this clip mostly bends about
    if length(ref) > 0.5:
        # refit on the frames that agree with it, so a few buckled frames can't drag it toward them
        acc2: Vec = (0.0, 0.0, 0.0)
        for u, v in zip(ul, vl):
            bend = angle_deg(u, v)
            ax = unit(cross(u, v))
            if bend >= 30 and angle_deg(ax, ref) < 20:
                acc2 = add(acc2, scale(ax, bend))
        if length(acc2) > 0:
            ref = unit(acc2)
    if ref_local is not None and (length(ref) < 0.5 or dot(ref, ref_local) < 0):
        # no clear bend, or the clip mostly bends the wrong way: judge it against the anatomy
        ref = unit(ref_local)
    out: dict = {"max_bend_deg": 0.0, "backward_frames": [], "worst_backward_deg": 0.0, "worst_sideways_deg": 0.0}
    if length(ref) < 0.5:
        return out
    signed, side = [], []
    for u, v in zip(ul, vl):
        vp = sub(v, scale(ref, dot(v, ref)))
        signed.append(math.degrees(math.atan2(dot(cross(u, vp), ref), dot(u, vp))))
        side.append(math.degrees(math.asin(min(1.0, abs(dot(unit(v), ref))))))
    out["max_bend_deg"] = round(max(signed), 1)
    back = [i for i, a in enumerate(signed) if a < -backward_limit]
    # one stray frame isn't a pose: two in a row is
    back = [i for i in back if (i - 1 in back) or (i + 1 in back)]
    out["backward_frames"] = back
    if back:
        out["worst_backward_deg"] = round(-min(signed[i] for i in back), 1)
    wide = [i for i, a in enumerate(side) if a > sideways_limit]
    wide = [i for i in wide if (i - 1 in wide) or (i + 1 in wide)]
    if wide:
        out["worst_sideways_deg"] = round(max(side[i] for i in wide), 1)
    return out


# ---------- hips ----------


def hip_extension_deg(
    thigh_rest_local: Sequence[float], fwd_rest_local: Sequence[float], thigh_now_local: Sequence[float]
) -> float:
    """How far the thigh has swung behind its rest direction, in the pelvis's side view (degrees,
    + = behind). All three directions are in the pelvis bone's own frame, so a tilted or rolling
    body doesn't fool it."""
    d0 = unit(thigh_rest_local)
    lat = unit(cross(d0, fwd_rest_local))  # turning d0 about lat moves the thigh forward (flexion)
    d = unit(thigh_now_local)
    dp = sub(d, scale(lat, dot(d, lat)))
    if length(dp) < 0.2:  # thigh pointing straight out to the side: no side-view angle
        return 0.0
    return -math.degrees(math.atan2(dot(cross(d0, dp), lat), dot(d0, dp)))


# ---------- signals ----------


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


def spread(a: Sequence[float]) -> float:
    """Half the peak-to-peak range."""
    return (max(a) - min(a)) / 2 if a else 0.0


def true_runs(flags: Sequence[bool]) -> list[tuple[int, int]]:
    out, i, n = [], 0, len(flags)
    while i < n:
        if flags[i]:
            j = i
            while j < n and flags[j]:
                j += 1
            out.append((i, j - i))
            i = j
        else:
            i += 1
    return out


def fall_acceleration(heights: Sequence[float], fps: float) -> float:
    """Vertical acceleration (m/s^2, negative = down) of a least-squares parabola through the
    heights. In the air, with nothing to push on, a body's centre of mass falls at 9.81."""
    n = len(heights)
    if n < 3:
        return 0.0
    ts = [i / fps for i in range(n)]
    # normal equations for h = c0 + c1 t + c2 t^2
    s = [sum(t**k for t in ts) for k in range(5)]
    r = [sum(h * t**k for h, t in zip(heights, ts)) for k in range(3)]
    m = [[s[0], s[1], s[2]], [s[1], s[2], s[3]], [s[2], s[3], s[4]]]

    def det3(a: list[list[float]]) -> float:
        return (
            a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
            - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
            + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
        )

    d = det3(m)
    if abs(d) < 1e-12:
        return 0.0
    m2 = [[*row[:2], r[i]] for i, row in enumerate(m)]
    return 2 * det3(m2) / d


def accel_series(points: Sequence[Sequence[float]], fps: float, span: int = 2) -> list[float]:
    """Horizontal acceleration magnitude (m/s^2) per frame, from velocities `span` frames apart
    (smooths out frame noise so only real changes of speed count)."""
    n = len(points)
    out = []
    for i in range(span, n - span):
        v1 = ((points[i][0] - points[i - span][0]) * fps / span, (points[i][1] - points[i - span][1]) * fps / span)
        v2 = ((points[i + span][0] - points[i][0]) * fps / span, (points[i + span][1] - points[i][1]) * fps / span)
        out.append(math.hypot(v2[0] - v1[0], v2[1] - v1[1]) * fps / span)
    return out


def speeds(points: Sequence[Sequence[float]], fps: float) -> list[float]:
    return [length(sub(points[i + 1], points[i])) * fps for i in range(len(points) - 1)]


# ---------- strikes (attacks) ----------


def strike(effector: Sequence[Vec], fps: float) -> dict:
    """Anticipation, hit and recovery of the fastest move in the clip. The hit is the burst where
    the effector (hand, foot or weapon tip) moves at over half its peak speed. A wind-up is a move
    against the strike direction before it starts."""
    sp = speeds(effector, fps)
    if not sp:
        return {}
    peak_i = max(range(len(sp)), key=lambda i: sp[i])
    peak = sp[peak_i]
    a = peak_i
    while a > 0 and sp[a - 1] >= peak / 2:
        a -= 1
    b = peak_i
    while b < len(sp) - 1 and sp[b + 1] >= peak / 2:
        b += 1
    direction = unit(sub(effector[b + 1], effector[a]))
    # wind-up: before the strike, the effector was pulled back against it, so earlier points sit
    # further along the strike direction than the point where the strike starts
    windup = max(0.0, max((dot(sub(effector[i], effector[a]), direction) for i in range(a + 1)), default=0.0))
    return {
        "peak_speed_m_s": round(peak, 2),
        "hit_frames": b - a + 1,
        "hit_start": a,
        "anticipation_s": round(a / fps, 3),
        "recovery_s": round((len(sp) - 1 - b) / fps, 3),
        "windup_m": round(windup, 3),
        "reach_m": round(length(sub(effector[b + 1], effector[a])), 3),
    }


def peak_frame(values: Sequence[float]) -> int:
    return max(range(len(values)), key=lambda i: values[i]) if values else 0
