# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-Python motion maths for the motion tool. No Blender, no numpy, so it is unit-tested directly.

Quaternions are (w, x, y, z) tuples. Positions are (x, y, z) tuples in metres, Z up (Blender).
A "clip" here is a list of frames sampled at a fixed rate.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence

Quat = tuple[float, float, float, float]
Vec = tuple[float, float, float]


# ---------- quaternions ----------


def q_norm(q: Sequence[float]) -> Quat:
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def q_dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def q_align(q: Sequence[float], ref: Sequence[float]) -> Quat:
    """Same rotation as q, on the same hemisphere as ref (q and -q are the same rotation)."""
    return tuple(-c for c in q) if q_dot(q, ref) < 0 else tuple(q)  # type: ignore[return-value]


def q_slerp(a: Sequence[float], b: Sequence[float], t: float) -> Quat:
    b = q_align(b, a)
    d = min(1.0, max(-1.0, q_dot(a, b)))
    if d > 0.9995:
        return q_norm([x + (y - x) * t for x, y in zip(a, b)])
    th = math.acos(d)
    s = math.sin(th)
    wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
    return q_norm([x * wa + y * wb for x, y in zip(a, b)])


def q_angle_deg(a: Sequence[float], b: Sequence[float]) -> float:
    d = min(1.0, abs(q_dot(q_norm(a), q_norm(b))))
    return math.degrees(2 * math.acos(d))


# ---------- signals ----------


def smooth_weights(flags: Sequence[float], radius: int, cyclic: bool) -> list[float]:
    """Box-blur a 0..1 signal (e.g. "foot on the ground") so edits fade in and out."""
    n = len(flags)
    out = []
    for i in range(n):
        acc, cnt = 0.0, 0
        for k in range(-radius, radius + 1):
            j = i + k
            if cyclic:
                j %= n
            elif j < 0 or j >= n:
                continue
            acc += flags[j]
            cnt += 1
        out.append(acc / cnt)
    return out


def loop_blend_weights(n: int, blend: int) -> list[float]:
    """Weight (0..1) of the clip's first frame mixed into each of the last `blend` frames, so the
    last frame matches the first exactly and the seam disappears."""
    w = [0.0] * n
    blend = max(1, min(blend, n - 1))
    for k in range(blend):
        i = n - blend + k
        t = (k + 1) / blend
        w[i] = t * t * (3 - 2 * t)  # smoothstep
    return w


# ---------- contact and checks ----------


def contacts(
    heights: Sequence[float], speeds: Sequence[float], ground: float, h_tol: float = 0.04, v_tol: float | None = None
) -> list[bool]:
    """A foot is planted when it is near its lowest height and not moving fast vertically-or-sideways
    compared with its own swing. v_tol defaults to 35% of the foot's peak speed."""
    peak = max(speeds) if speeds else 0.0
    vt = v_tol if v_tol is not None else max(0.35 * peak, 0.05)  # a still foot on an idle is planted
    return [h <= ground + h_tol and s <= vt for h, s in zip(heights, speeds)]


def runs(flags: Sequence[bool], cyclic: bool) -> list[tuple[int, int]]:
    """(start, length) of each True run; a run crossing the loop seam is joined when cyclic."""
    n = len(flags)
    out: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if flags[i]:
            j = i
            while j < n and flags[j]:
                j += 1
            out.append((i, j - i))
            i = j
        else:
            i += 1
    if cyclic and len(out) > 1 and out[0][0] == 0 and out[-1][0] + out[-1][1] == n:
        s, ln = out.pop()
        first = out.pop(0)
        out.append((s, ln + first[1]))
    return out


def dist2d(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def slide_per_contact(
    positions: Sequence[Vec], flags: Sequence[bool], fps: float, cyclic: bool, treadmill: Vec = (0.0, 0.0, 0.0)
) -> list[float]:
    """Sliding speed (m/s) of a planted foot, per contact. `treadmill` is the clip's in-place
    ground speed (an in-place walk moves planted feet backward at a steady speed; that's correct).
    The score is the planted foot's average speed after removing that steady drift."""
    n = len(positions)
    out = []
    for start, length in runs(flags, cyclic):
        if length < 2:
            continue
        idx = [(start + k) % n for k in range(length)]
        moved = 0.0
        for a, b in itertools.pairwise(idx):
            pa, pb = positions[a], positions[b]
            dx = (pb[0] - pa[0]) - treadmill[0] / fps
            dy = (pb[1] - pa[1]) - treadmill[1] / fps
            moved += math.hypot(dx, dy)
        out.append(moved * fps / (length - 1))
    return out


def drop_sweeps(
    positions: Sequence[Vec],
    flags: Sequence[bool],
    fps: float,
    cyclic: bool,
    max_dev: float = 1.0,
    heights: Sequence[float] | None = None,
    lift: float = 0.006,
) -> list[bool]:
    """A foot low and level can still be swinging: a shuffle or crouch walk sweeps the foot forward a
    centimetre off the floor. Such frames are not planted. A planted foot moves at the clip's steady
    ground speed (zero, or the in-place treadmill speed); a frame whose sideways speed is more than
    max_dev m/s away from the planted frames' typical (median) velocity, with the foot at least `lift`
    above its lowest point, is a sweep. A foot racing along AT its lowest point is dragged across the
    floor: that stays planted, so it is reported as skating."""
    n = len(positions)
    if n < 3 or not any(flags):
        return list(flags)
    vel = []
    for i in range(n):
        j = (i + 1) % n if cyclic else i + 1
        a, b = (positions[i], positions[j]) if j < n and j != i else (positions[i - 1], positions[i])
        vel.append(((b[0] - a[0]) * fps, (b[1] - a[1]) * fps))
    if cyclic and dist2d(positions[-1], positions[0]) < 1e-6:
        vel[-1] = vel[0]  # a loop's last frame repeats its first: it moves as the first does
    planted = sorted(v for v, f in zip(vel, flags) if f)
    mx = sorted(v[0] for v in planted)[len(planted) // 2]
    my = sorted(v[1] for v in planted)[len(planted) // 2]
    hs = list(heights) if heights is not None else [p[2] for p in positions]
    low = min(hs)
    return [f and (math.hypot(v[0] - mx, v[1] - my) <= max_dev or h < low + lift) for f, v, h in zip(flags, vel, hs)]


def treadmill_velocity(positions: Sequence[Vec], flags: Sequence[bool], fps: float, robust: bool = False) -> Vec:
    """The planted feet's velocity across the clip (the in-place ground speed), or zero. The checks
    use the mean (calibrated on the UAL packs). The fixer uses the median (robust=True): a few dragged
    frames mustn't make it lock a standing clip's feet to a moving path."""
    vx, vy = [], []
    for i in range(len(positions) - 1):
        if flags[i] and flags[i + 1]:
            vx.append((positions[i + 1][0] - positions[i][0]) * fps)
            vy.append((positions[i + 1][1] - positions[i][1]) * fps)
    if not vx:
        return (0.0, 0.0, 0.0)
    k = len(vx)
    if not robust:
        return (sum(vx) / k, sum(vy) / k, 0.0)
    vx.sort()
    vy.sort()

    def mid(v):
        return v[k // 2] if k % 2 else (v[k // 2 - 1] + v[k // 2]) / 2

    return (mid(vx), mid(vy), 0.0)


def pops(
    angles_per_frame: Sequence[float],
    ratio: float = 2.5,
    floor_deg: float = 8.0,
    skip_angles: Sequence[float] | None = None,
) -> list[int]:
    """Frames where a bone suddenly turns much faster than on the frames either side: a pop.
    A fast but smooth move (a foot rolling off the toe) builds up and slows down, so it isn't one.
    `angles_per_frame[i]` is the angle turned between frame i and i+1; `skip_angles[i]`, when
    given, the angle between frame i and i+2 (to tell a spike that comes back from a fast move)."""
    a = list(angles_per_frame)
    out = []
    for i, v in enumerate(a):
        prev = a[i - 1] if i > 0 else None
        nxt = a[i + 1] if i + 1 < len(a) else None
        around = [x for x in (prev, nxt) if x is not None]
        if not around:
            continue
        if v > floor_deg and v > ratio * (sum(around) / len(around)):
            out.append(i)
    # A one-frame spike (the pose jumps out and straight back, what key compression does) turns
    # two big steps in a row, and each hid the other above (a 35-degree calf
    # spike passed that way). Judge the pair against the steps outside it, and only when the pose comes
    # back (frame i+2 near frame i): a strike snapping into a new pose is a style, not a pop.
    # Report the jumped-to frame, so the fixer re-keys that pose from the frames either side.
    if skip_angles is None:
        return out
    for i in range(min(len(a) - 1, len(skip_angles))):
        if i in out or i + 1 in out:
            continue
        outer = [x for x in (a[i - 1] if i > 0 else None, a[i + 2] if i + 2 < len(a) else None) if x is not None]
        low = min(a[i], a[i + 1])
        back = skip_angles[i] < 0.5 * low
        if outer and back and low > floor_deg and low > ratio * (sum(outer) / len(outer)):
            out.append(i + 1)
    return sorted(out)


def com(points: Sequence[tuple[Vec, float]]) -> Vec:
    """Mass-weighted centre of mass from (position, weight) pairs."""
    tw = sum(w for _, w in points) or 1.0
    return (
        sum(p[0] * w for p, w in points) / tw,
        sum(p[1] * w for p, w in points) / tw,
        sum(p[2] * w for p, w in points) / tw,
    )


def dist_to_segment2d(p: Sequence[float], a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    t = 0.0 if len_sq == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / len_sq))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def hull2d(points: Sequence[Sequence[float]]) -> list[tuple[float, float]]:
    """Convex hull (x, y) of the points, counter-clockwise (monotone chain)."""
    pts = sorted({(round(p[0], 6), round(p[1], 6)) for p in points})
    if len(pts) <= 2:
        return pts

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def outside_support(c: Sequence[float], feet_points: Sequence[Sequence[float]]) -> float:
    """How far (m, on the ground) the centre of mass is outside the area the planted feet cover.
    0 when it's over the feet."""
    h = hull2d(feet_points)
    if len(h) == 1:
        return math.hypot(c[0] - h[0][0], c[1] - h[0][1])
    if len(h) == 2:
        return dist_to_segment2d(c, h[0], h[1])
    inside = all((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) >= 0 for a, b in zip(h, h[1:] + h[:1]))
    if inside:
        return 0.0
    return min(dist_to_segment2d(c, a, b) for a, b in zip(h, h[1:] + h[:1]))
