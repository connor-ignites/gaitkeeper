# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose Adapt maths: where in a clip one pose edit should land, and how strongly. No Blender, no numpy.

A pose edit made on one frame spreads in one of three ways:
- "whole": the same change on every frame (posture and stance: a straighter back, a wider stance).
- "steps": the same moment of every step. A walk or run repeats every `period` frames; the edit lands
  on that moment in every cycle, and (mirrored left for right) half a cycle later, when the other foot
  is in the same spot. Between those moments it fades out and back in smoothly.
- "here": only around the edited frame, fading in and out over `spread` frames so nothing pops.

Weights are 1 on the edited frame (the pose you made is the pose you get) and fade on a cosine curve,
which starts and ends flat, so the change never jerks in or out.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

MODES = ("whole", "steps", "here")


def bump(d: float, radius: float) -> float:
    """1 at d = 0, falling smoothly (flat at both ends) to 0 at |d| >= radius."""
    if radius <= 0:
        return 1.0 if abs(d) < 1e-9 else 0.0
    x = abs(d) / radius
    return 0.5 * (1 + math.cos(math.pi * x)) if x < 1 else 0.0


def loop_frames(n: int, cyclic: bool) -> int:
    """Distinct frames in a clip: a loop's last frame repeats its first."""
    return n - 1 if cyclic and n > 2 else n


def _alike(a: Sequence[float], b: Sequence[float]) -> float:
    """How alike two signals are, -1 to 1 (Lin's concordance): 1 only when they match value for value.
    Unlike plain correlation, a shifted copy (a ramp, a drift) doesn't count as a repeat."""
    n = len(a)
    if n < 3:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    den = va + vb + n * (ma - mb) ** 2
    if den < 1e-12:
        return 0.0
    return 2 * sum((x - ma) * (y - mb) for x, y in zip(a, b)) / den


def lag_corr(
    channels: Sequence[Sequence[float]], lag: int, cyclic: bool, others: Sequence[Sequence[float]] | None = None
) -> float:
    """How alike each channel is with itself (or with `others`) `lag` frames later, averaged over the
    channels (-1 to 1). A loop wraps around; a one-off clip compares only the overlap."""
    out = []
    for k, ch in enumerate(channels):
        other = others[k] if others is not None else ch
        m = len(ch)
        if cyclic:
            b = [other[(i + lag) % m] for i in range(m)]
            out.append(_alike(ch, b))
        elif lag < m - 2:
            out.append(_alike(ch[: m - lag], other[lag:]))
    return sum(out) / len(out) if out else 0.0


def step_period(
    channels: Sequence[Sequence[float]], fps: float, cyclic: bool, min_s: float = 0.4, alike: float = 0.85
) -> int | None:
    """Frames in one full gait cycle (left step + right step), from signals that repeat once per cycle
    (one foot's height, its distance ahead of the hips). The shortest lag at which the motion repeats.
    A loop always repeats over its whole length; None when a one-off clip never repeats."""
    m = len(channels[0]) if channels else 0
    if m < 4:
        return None
    lo = max(2, round(min_s * fps))
    for lag in range(lo, m if cyclic else m - 2):
        if cyclic and m % lag:  # a loop holds a whole number of cycles
            continue
        if lag_corr(channels, lag, cyclic) >= alike:
            return lag
    return m if cyclic else None


def sides_alternate(
    left: Sequence[Sequence[float]], right: Sequence[Sequence[float]], period: int, cyclic: bool, alike: float = 0.6
) -> bool:
    """True when the right side does what the left did half a cycle earlier (walks, runs, crawls),
    so a left-side edit belongs, mirrored, on the right half a cycle later."""
    half = period // 2
    if half < 1:
        return False
    return lag_corr(left, half, cyclic, right) >= alike


def smoothstep(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def axis(n: int, mode: str, cyclic: bool, spread: float, period: int | None) -> tuple[float, bool, float | None]:
    """Where poses sit, for a spread mode: (axis length, wraps round, fade radius or None for no fade).
    "whole" and "here" use the clip's own frames; "steps" uses the step cycle (a pose's phase)."""
    m = loop_frames(n, cyclic)
    if mode == "steps" and period:
        return float(period), True, max(1.0, min(float(spread), period / 4))
    return float(m), cyclic, (None if mode == "whole" else max(1.0, float(spread)))


def position(i: int, n: int, mode: str, cyclic: bool, period: int | None) -> float:
    """Frame i on the axis: its frame, or its moment in the step cycle."""
    m = loop_frames(n, cyclic)
    j = i % m if cyclic else i
    return float(j % period) if mode == "steps" and period else float(j)


def blend_plan(
    keys: Sequence[float], x: float, length: float, wraps: bool, radius: float | None
) -> tuple[int, int, float, float] | None:
    """How several kept poses shape one frame. `keys` are the poses' positions on the axis (sorted, no
    repeats); returns (a, b, u, w): the change at x is the change of pose a blended toward pose b by u,
    applied at strength w. None when no pose reaches x.

    Between two neighbouring poses closer than two fade radii (always, with no fade) the change runs
    smoothly from one pose's change to the next, so every pose is kept exactly and nothing dips in
    between; past the outer poses it fades out over the radius (or holds, with no fade)."""
    k = len(keys)
    if k == 0:
        return None
    for i, p in enumerate(keys):
        if abs(x - p) < 1e-9 or (wraps and abs(abs(x - p) - length) < 1e-9):
            return i, i, 0.0, 1.0
    right = next((i for i, p in enumerate(keys) if p > x), None)
    left = next((i for i in range(k - 1, -1, -1) if keys[i] < x), None)
    if wraps:
        if right is None:
            right = 0
        if left is None:
            left = k - 1
    gl = (x - keys[left]) % length if wraps and left is not None else (x - keys[left] if left is not None else None)
    gr = (keys[right] - x) % length if wraps and right is not None else (keys[right] - x if right is not None else None)
    if left is not None and right is not None and (left != right or wraps):
        gap = gl + gr  # type: ignore[operator]
        if radius is None or gap <= 2 * radius:
            if left == right:  # one pose, wrapping round to itself
                return left, left, 0.0, 1.0
            return left, right, smoothstep(gl / gap), 1.0  # type: ignore[operator]
    if radius is None:  # no fade: hold the nearest end pose
        near = left if right is None else right if left is None else (left if gl <= gr else right)  # type: ignore[operator]
        return near, near, 0.0, 1.0  # type: ignore[return-value]
    cands = [(gl, left), (gr, right)]
    d, near = min((c for c in cands if c[1] is not None), key=lambda c: c[0])  # type: ignore[type-var]
    w = bump(d, radius)  # type: ignore[arg-type]
    return (near, near, 0.0, w) if w > 0 else None  # type: ignore[return-value]


def sides_together(
    left: Sequence[Sequence[float]], right: Sequence[Sequence[float]], cyclic: bool, alike: float = 0.6
) -> bool:
    """True when both sides do the same thing at the same time (a hop, a bound): a change to one leg
    belongs, mirrored, on the other leg at the same moment."""
    return lag_corr(left, 0, cyclic, right) >= alike


def describe(
    mode: str, n: int, cyclic: bool, spread: float, period: int | None, frames: Sequence[int], mirror: bool
) -> str:
    """Plain words for where the change went."""
    m = loop_frames(n, cyclic)
    poses = f"{len(frames)} poses, " if len(frames) > 1 else ""
    if mode == "whole":
        return (
            poses
            + ("blended across the whole clip" if len(frames) > 1 else "the whole clip")
            + (", both sides" if mirror else "")
        )
    if mode == "steps" and period:
        steps = max(1, round(m / period))
        how = f"{poses}the same moment of every step ({steps} cycle{'s' if steps != 1 else ''} of {period} frames"
        return how + (", mirrored on the other foot's step)" if mirror else ")")
    r = int(max(1.0, float(spread)))
    return poses + f"frames {max(0, min(frames) - r)} to {min(n - 1, max(frames) + r)} (fading in and out)"
