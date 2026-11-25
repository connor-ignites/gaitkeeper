# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: E501 - the pinned verdicts below are whole sentences, kept verbatim
"""Characterization tests for core.body: measure_body and the verdicts pinned on synthetic clips.

The expected values were captured from the code before measure_body and _issues were split into helpers,
so any change in a returned dict, a key, a verdict's wording or the order of verdicts fails here.
"""

import math
import unittest
from types import SimpleNamespace

from conftest import axis_q
from core import body

UPPER_BONES = ("thigh_l", "thigh_r", "upperarm_l", "upperarm_r", "lowerarm_l", "lowerarm_r", "hand_l", "hand_r")
BONES = (*UPPER_BONES, "head", "hips", "spine3")
ROLES = {b: b for b in BONES}
LENGTHS = {"thigh_l": 0.45, "thigh_r": 0.45, "upperarm_l": 0.28, "upperarm_r": 0.28, "spine3": 0.4}
FPS = 30.0


def _add(a: tuple, b: tuple) -> tuple:
    return tuple(round(x + y, 6) for x, y in zip(a, b))


def _punch_x(i: int) -> float:
    """A right hand that draws back, then punches through (metres along y)."""
    if i < 8:
        return 0.0
    if i < 13:
        return -0.12 * (i - 8)
    if i < 27:
        return min(-0.6 + 0.09 * (i - 13), 0.66)
    return 0.66


def _limbs(w: dict, side: str, hips: tuple, t: float, k: dict, up: float, yaw: float, cyaw: float) -> bool:
    """Leg and arm points of one side for one frame; returns whether that foot is planted."""
    sx = -1.0 if side == "l" else 1.0
    ph = math.sin(t) if side == "l" else -math.sin(t)
    thigh = _add(hips, (sx * 0.1 * math.cos(yaw), sx * 0.1 * math.sin(yaw), 0.0))
    lift = max(0.0, ph) * 0.15
    if k["one_foot"]:
        lift = 0.2 if side == "l" else 0.0
    knee = _add(thigh, (0.0, k["stride"] * ph + 0.05 - k["knee_back"], -0.45 + lift))
    ankle = _add(knee, (0.0, k["stride"] * ph * 0.5 - 0.02 + k["knee_back"], -0.45 + lift))
    ankle = (ankle[0], ankle[1], max(ankle[2], 0.08 + up))
    w.update({f"pt:thigh_{side}": thigh, f"pt:calf_{side}": knee, f"pt:foot_{side}": ankle, f"ankle_{side}": ankle})
    w[f"ball_{side}"] = _add(ankle, (0.0, 0.1, -0.06))
    w[f"toe_{side}"] = _add(ankle, (0.0, 0.16, -0.07))
    sh = _add(hips, (sx * 0.2 * math.cos(cyaw), sx * 0.2 * math.sin(cyaw), 0.5))
    sw = k["arm_sign"] * ph * 0.2
    el = _add(sh, (0.0, sw, -0.28))
    hand = (0.3, _punch_x(k["i"]), 1.4) if k["punch"] and side == "r" else _add(el, (0.0, sw * 0.8 + 0.05, -0.24))
    w.update({f"pt:upperarm_{side}": sh, f"pt:lowerarm_{side}": el, f"pt:hand_{side}": hand})
    w[f"tip:lowerarm_{side}"] = hand
    w[f"tip:hand_{side}"] = _add(hand, (0.0, 0.02, -0.08))
    w[f"com:thigh_{side}"] = _add(thigh, (0.0, 0.0, -0.2))
    w[f"com:upperarm_{side}"] = _add(sh, (0.0, 0.0, -0.14))
    return lift < 0.01 and up < 0.01


DEFAULTS = {
    "n": 40,
    "cycles": 2.0,
    "speed": 1.2,
    "stride": 0.25,
    "arm_sign": -1.0,
    "hip_yaw": 8.0,
    "chest_sign": -1.0,
    "lift_at": None,
    "knee_back": 0.0,
    "neck_twist": 10.0,
    "lean": 0.0,
    "punch": False,
    "one_foot": False,
    "root": True,
    "drop": (),
}


def _frame(i: int, k: dict, flags: dict) -> tuple[dict, dict]:
    """World points and world rotations of one frame of the synthetic clip."""
    t = 2 * math.pi * k["cycles"] * i / max(k["n"] - 1, 1)
    up = 0.0
    if k["lift_at"] and k["lift_at"][0] <= i < k["lift_at"][1]:
        a, b = k["lift_at"]
        up = 0.6 * math.sin(math.pi * (i - a + 1) / (b - a + 1))
    hips = (0.0, k["speed"] * i / FPS, 1.0 + 0.02 * math.sin(2 * t) + up)
    w = {"hips": hips, "pt:hips": hips}
    if k["root"]:
        w["rootbone"] = (0.0, k["speed"] * i / FPS, up)
    yaw = math.radians(k["hip_yaw"] * math.sin(t))
    cyaw = math.radians(k["chest_sign"] * k["hip_yaw"] * 1.5 * math.sin(t))
    for side in "lr":
        flags[side].append(_limbs(w, side, hips, t, {**k, "i": i}, up, yaw, cyaw))
    lean = k["lean"]
    w["pt:spine2"] = _add(hips, (0.0, 0.0, 0.3))
    w["pt:spine3"] = _add(hips, (lean * 0.01, 0.0, 0.45))
    w["pt:neck"] = _add(hips, (lean * 0.02, 0.0, 0.6))
    w["pt:head"] = _add(hips, (lean * 0.025, 0.0, 0.7))
    w["tip:head"] = _add(hips, (lean * 0.03, 0.01 * math.sin(3 * t), 0.9))
    w["com:spine3"] = _add(hips, (0.0, 0.0, 0.3))
    for key in k["drop"]:
        del w[key]
    q = {b: axis_q((1.0, 0.0, 0.0), 20 * math.sin(t + j)) for j, b in enumerate(UPPER_BONES)}
    q["hips"] = axis_q((0.0, 0.0, 1.0), k["hip_yaw"] * math.sin(t))
    q["spine3"] = axis_q((0.0, 0.0, 1.0), k["chest_sign"] * k["hip_yaw"] * 4 * math.sin(t))
    q["head"] = axis_q((0.0, 0.0, 1.0), k["neck_twist"] * math.sin(t))
    if k["punch"]:
        q["spine3"] = axis_q((0.0, 0.0, 1.0), 2.0 * i)
    return w, q


def sample(**kw) -> tuple[SimpleNamespace, dict[str, list[bool]]]:
    """A synthetic full-body clip shaped like rig.Sample, plus its planted-foot flags."""
    k = {**DEFAULTS, **kw}
    flags: dict[str, list[bool]] = {"l": [], "r": []}
    frames = [_frame(i, k, flags) for i in range(k["n"])]
    s = SimpleNamespace(
        world=[w for w, _ in frames],
        world_q=[q for _, q in frames],
        rest_q=dict.fromkeys(BONES, (1.0, 0.0, 0.0, 0.0)),
        rest_axis=dict.fromkeys(BONES, (0.0, 0.0, 1.0)),
        rest_fwd=(0.0, 1.0, 0.0),
    )
    return s, flags


def minimal_punch() -> SimpleNamespace:
    """Hips and one hand only (no rest pose): a hand that draws back faster than it punches."""
    xs = (
        [0.0] * 4 + [-0.12 * i for i in range(1, 6)] + [-0.6] * 4 + [-0.6 + 0.09 * i for i in range(1, 15)] + [0.66] * 6
    )
    world = [{"hips": (0.0, 0.0, 1.0), "tip:hand_r": (x, 0.3, 1.4)} for x in xs]
    return SimpleNamespace(world=world, world_q=[{} for _ in world], rest_q={}, rest_axis={})


NO_THIGH_L = {r: b for r, b in ROLES.items() if r != "thigh_l"}
STILL = {"speed": 0.0, "stride": 0.0}
PUNCH = {**STILL, "punch": True}

# label: (sample kwargs, name, roles, travels, feet_off_ground, cyclic, standing_still)
SCENARIOS = {
    "walk": ({}, "Walk_Fwd", ROLES, True, False, True, False),
    "walk_robot": ({"arm_sign": 1.0, "chest_sign": 1.0, "cycles": 6.0}, "Walk_Robot", ROLES, True, False, True, False),
    "walk_slow": ({"cycles": 0.5, "n": 60}, "Walk_Slow", ROLES, True, False, True, False),
    "walk_left_still": ({"speed": 0.0, "lean": 8.0}, "Walk_Left", ROLES, False, False, True, False),
    "walk_left_no_root": ({"lean": 8.0, "root": False}, "Walk_Left", ROLES, True, False, True, False),
    "walk_no_thigh_role": ({}, "Walk_Fwd", NO_THIGH_L, True, False, True, False),
    "run": ({"lift_at": (10, 22), "speed": 3.0}, "Run_Loop", ROLES, True, False, True, False),
    "run_no_flight": ({"speed": 3.0}, "Run_Loop", ROLES, True, False, True, False),
    "idle_one_foot": ({**STILL, "one_foot": True}, "Idle_Breath", ROLES, False, False, True, True),
    "idle_float": ({**STILL, "lift_at": (10, 30)}, "Idle_Float", ROLES, False, False, True, True),
    "jump": ({"speed": 0.0, "lift_at": (10, 30)}, "Jump_Start", ROLES, False, True, False, False),
    "knee_back": ({"knee_back": 0.4, "neck_twist": 120.0}, "Walk_Broken", ROLES, True, False, True, False),
    "punch": (PUNCH, "Punch_Haymaker", ROLES, False, False, False, False),
    "enemy": (PUNCH, "Enemy_Slash", ROLES, False, False, False, False),
    "punch_no_roles": (PUNCH, "Punch_Jab", {}, False, False, False, False),
    "punch_dropped_keys": (
        {**PUNCH, "drop": ("tip:lowerarm_l", "toe_l")},
        "Kick_Low",
        ROLES,
        False,
        False,
        False,
        False,
    ),
    "short": ({"n": 2}, "Walk_Fwd", ROLES, True, False, True, False),
    "single": ({"n": 1}, "Idle", ROLES, False, False, False, True),
    "single_punch": ({"n": 1}, "Punch_Jab", ROLES, False, False, False, True),
    "punch_no_hips": ({**PUNCH, "drop": ("hips",)}, "Punch_Jab", ROLES, False, False, False, False),
}


def measure(label: str) -> tuple[dict, list[str]]:
    kw, name, roles, travels, feet_off, cyclic, still = SCENARIOS[label]
    s, flags = sample(**kw)
    b = body.measure_body(s, FPS, roles, flags, LENGTHS, name, travels, feet_off, cyclic, still)
    return b, body.body_verdicts(b, None, name, feet_off, FPS)


# Hand-made measurements that reach every verdict _issues can give.
EVERYTHING = {
    "knee_l": {"max_bend_deg": 170, "backward_frames": [1, 2], "worst_backward_deg": 30, "worst_sideways_deg": 25},
    "knee_r": {"max_bend_deg": 20, "backward_frames": [5, 6, 7], "worst_backward_deg": 80, "worst_sideways_deg": 0},
    "elbow_l": {"max_bend_deg": 160, "backward_frames": [3, 4], "worst_backward_deg": 20, "worst_sideways_deg": 30},
    "elbow_r": {"max_bend_deg": 10, "backward_frames": [], "worst_backward_deg": 0, "worst_sideways_deg": 0},
    "wrist_l": {"bend_deg": 100, "twist_deg": 0},
    "wrist_r": {"bend_deg": 120, "twist_deg": 0},
    "neck": {"bend_deg": 90, "twist_deg": 10},
    "spine": {"bend_deg": 100, "twist_deg": 70},
    "hip_extension_deg": 40,
    "longest_airborne": 5,
    "airborne_frames": 0,
    "air_gravity_m_s2": [4.0, 9.8, 20.0],
    "hang_share": [0.1, 0.4],
    "lean": {"mean_deg": 10.0, "excess_deg": 20.0, "range_deg": 5.0, "turning": False},
    "com_accel_max_m_s2": 45.0,
    "one_foot_off_balance_m": 0.12,
    "one_foot_side": "r",
    "steps_per_min": 150.0,
    "arm_leg_corr": 0.5,
    "arm_swing_m": 0.1,
    "leg_swing_m": 0.2,
    "chest_hip_corr": 0.8,
    "hip_turn_deg": 5.0,
    "chest_turn_deg": 5.0,
    "linear_runs": {"left hand": (10, 2), "head": (12, 0)},
    "block_bob": ["WARN the head bobs with the hips."],
}
SLOW_TURN = {"steps_per_min": 60.0, "lean": {"mean_deg": 10.0, "excess_deg": 20.0, "range_deg": 5.0, "turning": True}}
STRIKE = {
    "effector": "toe_l",
    "hit_frames": 12,
    "reach_m": 0.6,
    "windup_m": 0.01,
    "anticipation_s": 0.02,
    "tell_s": 0.1,
    "windup_split": {"windup_m_s": 4.0, "strike_m_s": 2.0},
    "chest_turn_deg": 1.0,
    "path_corners": [3, 5],
    "chain_peaks": [5, 9, 2, 4, 3],
}
FOREARM = {"effector": "lowerarm_l", "hit_frames": 5, "reach_m": 0.3, "windup_m": 0.1, "anticipation_s": 0.2}
WEAPON = {**STRIKE, "effector": "weapon", "tell_s": None, "chain_peaks": [1, 2, 3]}
ISSUES = {
    "empty": ({}, "Walk_Fwd", False),
    "everything_walk": (EVERYTHING, "Walk_Fwd", False),
    "everything_jump": (EVERYTHING, "Jump_Up", False),
    "everything_feet_off": (EVERYTHING, "Walk_Fwd", True),
    "run_no_flight": ({"airborne_frames": 0, "steps_per_min": 170.0}, "Run_Loop", False),
    "slow_turn": (SLOW_TURN, "Walk_Turn", False),
    "enemy_kick": ({"strike": STRIKE}, "Boss_Kick", False),
    "kick": ({"strike": STRIKE}, "Kick_High", False),
    "enemy_forearm": ({"strike": FOREARM}, "Enemy_Jab", False),
    "weapon": ({"strike": WEAPON}, "Enemy_Swing", False),
}

EXPECTED: dict = {
    "measure": {
        "walk": (
            {
                "knee_l": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [1, 2, 3, 4, 5, 6, 7, 8, 21, 22, 23, 24, 25, 26, 27, 28],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [11, 12, 13, 14, 15, 16, 17, 18, 31, 32, 33, 34, 35, 36, 37, 38],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 42.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 23.7,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 184.6,
                "com_accel_max_m_s2": 0.0,
                "arm_leg_corr": -1.0,
                "arm_swing_m": 0.576,
                "leg_swing_m": 0.742,
                "chest_hip_corr": -1.0,
                "hip_turn_deg": 8.0,
                "chest_turn_deg": 12.0,
                "linear_runs": {},
                "lean": {"mean_deg": -0.0, "excess_deg": 0.0, "range_deg": 0.0, "turning": False},
            },
            [
                "FAIL left knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "FAIL right knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "WARN 185 steps a minute: a walk is 100-120 (shuffling or rushing).",
            ],
        ),
        "walk_robot": (
            {
                "knee_l": {
                    "max_bend_deg": 6.0,
                    "backward_frames": [1, 2, 7, 8, 9, 14, 15, 20, 21, 22, 27, 28, 33, 34, 35],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": 6.0,
                    "backward_frames": [4, 5, 6, 11, 12, 17, 18, 19, 24, 25, 30, 31, 32, 37, 38],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 21.8},
                "spine": {"bend_deg": 0.0, "twist_deg": 23.8},
                "wrist_l": {"bend_deg": 33.6, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 23.6,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 553.8,
                "com_accel_max_m_s2": 0.0,
                "arm_leg_corr": 1.0,
                "arm_swing_m": 0.68,
                "leg_swing_m": 0.737,
                "chest_hip_corr": 1.0,
                "hip_turn_deg": 7.9,
                "chest_turn_deg": 11.9,
                "linear_runs": {"hips": (2, 12)},
                "lean": {"mean_deg": -0.0, "excess_deg": 0.0, "range_deg": 0.0, "turning": False},
            },
            [
                "FAIL left knee bends backwards (26 degrees, 15 frames). A knee is a hinge: it only folds forward.",
                "FAIL right knee bends backwards (26 degrees, 15 frames). A knee is a hinge: it only folds forward.",
                "WARN 554 steps a minute: a walk is 100-120 (shuffling or rushing).",
                "WARN arms swing with the same-side leg (marching like a robot): each arm swings forward with the opposite leg.",
                "WARN the chest turns with the hips instead of against them: in a walk the shoulders twist the opposite way to the hips.",
            ],
        ),
        "walk_slow": (
            {
                "knee_l": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [
                        7,
                        8,
                        9,
                        10,
                        11,
                        12,
                        13,
                        14,
                        15,
                        16,
                        17,
                        18,
                        19,
                        20,
                        21,
                        22,
                        23,
                        24,
                        25,
                        26,
                        27,
                        28,
                        29,
                        30,
                        31,
                        32,
                        33,
                        34,
                        35,
                        36,
                        37,
                        38,
                        39,
                        40,
                        41,
                        42,
                        43,
                        44,
                        45,
                        46,
                        47,
                        48,
                        49,
                        50,
                        51,
                        52,
                    ],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 42.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.7, "twist_deg": 0.0},
                "hip_extension_deg": 23.7,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 61.0,
                "com_accel_max_m_s2": 0.0,
                "arm_leg_corr": -1.0,
                "arm_swing_m": 0.288,
                "leg_swing_m": 0.371,
                "chest_hip_corr": -1.0,
                "hip_turn_deg": 4.0,
                "chest_turn_deg": 6.0,
                "linear_runs": {"left hand": (7, 0), "right hand": (7, 0), "left foot": (7, 0), "right foot": (3, 4)},
                "lean": {"mean_deg": 0.0, "excess_deg": 0.0, "range_deg": 0.0, "turning": False},
            },
            [
                "FAIL left knee bends backwards (26 degrees, 46 frames). A knee is a hinge: it only folds forward.",
                "WARN 61 steps a minute: a walk is 100-120 (very slow, like wading).",
            ],
        ),
        "walk_left_still": (
            {
                "knee_l": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [1, 2, 3, 4, 5, 6, 7, 8, 21, 22, 23, 24, 25, 26, 27, 28],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [11, 12, 13, 14, 15, 16, 17, 18, 31, 32, 33, 34, 35, 36, 37, 38],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 42.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 23.7,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 184.6,
                "com_accel_max_m_s2": 0.0,
                "arm_leg_corr": -1.0,
                "arm_swing_m": 0.576,
                "leg_swing_m": 0.742,
                "chest_hip_corr": -1.0,
                "hip_turn_deg": 8.0,
                "chest_turn_deg": 12.0,
                "linear_runs": {},
            },
            [
                "FAIL left knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "FAIL right knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "WARN 185 steps a minute: a walk is 100-120 (shuffling or rushing).",
            ],
        ),
        "walk_left_no_root": (
            {
                "knee_l": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [1, 2, 3, 4, 5, 6, 7, 8, 21, 22, 23, 24, 25, 26, 27, 28],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [11, 12, 13, 14, 15, 16, 17, 18, 31, 32, 33, 34, 35, 36, 37, 38],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 42.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 23.7,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 184.6,
                "com_accel_max_m_s2": 0.0,
                "arm_leg_corr": -1.0,
                "arm_swing_m": 0.576,
                "leg_swing_m": 0.742,
                "chest_hip_corr": -1.0,
                "hip_turn_deg": 8.0,
                "chest_turn_deg": 12.0,
                "linear_runs": {"hips": (2, 4)},
                "lean": {"mean_deg": 14.9, "excess_deg": 14.9, "range_deg": 0.1, "turning": True},
            },
            [
                "FAIL left knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "FAIL right knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "WARN 185 steps a minute: a walk is 100-120 (shuffling or rushing).",
            ],
        ),
        "walk_no_thigh_role": (
            {
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [11, 12, 13, 14, 15, 16, 17, 18, 31, 32, 33, 34, 35, 36, 37, 38],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 42.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 23.7,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 184.6,
                "com_accel_max_m_s2": 0.0,
                "arm_leg_corr": -1.0,
                "arm_swing_m": 0.576,
                "leg_swing_m": 0.742,
                "chest_hip_corr": -1.0,
                "hip_turn_deg": 8.0,
                "chest_turn_deg": 12.0,
                "linear_runs": {},
                "lean": {"mean_deg": -0.0, "excess_deg": 0.0, "range_deg": 0.0, "turning": False},
            },
            [
                "FAIL right knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "WARN 185 steps a minute: a walk is 100-120 (shuffling or rushing).",
            ],
        ),
        "run": (
            {
                "knee_l": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [1, 2, 3, 4, 5, 6, 7, 8, 21, 22, 23, 24, 25, 26, 27, 28],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [11, 12, 13, 14, 15, 16, 17, 18, 31, 32, 33, 34, 35, 36, 37, 38],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 42.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 23.7,
                "airborne_frames": 12,
                "longest_airborne": 12,
                "air_gravity_m_s2": [26.0],
                "hang_share": [0.42],
                "steps_per_min": 138.5,
                "com_accel_max_m_s2": 0.0,
                "arm_leg_corr": -1.0,
                "arm_swing_m": 0.576,
                "leg_swing_m": 0.742,
                "chest_hip_corr": -1.0,
                "hip_turn_deg": 8.0,
                "chest_turn_deg": 12.0,
                "linear_runs": {},
                "lean": {"mean_deg": 0.0, "excess_deg": 0.0, "range_deg": 0.0, "turning": False},
            },
            [
                "FAIL left knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "FAIL right knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "WARN in the air the body falls at 26.0 m/s each second (real gravity is 9.8): it drops like it's pulled down. Snappy, but check the game's jump gravity matches.",
            ],
        ),
        "run_no_flight": (
            {
                "knee_l": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [1, 2, 3, 4, 5, 6, 7, 8, 21, 22, 23, 24, 25, 26, 27, 28],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [11, 12, 13, 14, 15, 16, 17, 18, 31, 32, 33, 34, 35, 36, 37, 38],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 42.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 23.7,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 184.6,
                "com_accel_max_m_s2": 0.0,
                "arm_leg_corr": -1.0,
                "arm_swing_m": 0.576,
                "leg_swing_m": 0.742,
                "chest_hip_corr": -1.0,
                "hip_turn_deg": 8.0,
                "chest_turn_deg": 12.0,
                "linear_runs": {},
                "lean": {"mean_deg": 0.0, "excess_deg": 0.0, "range_deg": 0.0, "turning": False},
            },
            [
                "FAIL left knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "FAIL right knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "WARN a run with no moment where both feet are off the ground: it reads as a fast walk. A run leaves the ground on every step.",
            ],
        ),
        "idle_one_foot": (
            {
                "knee_l": {
                    "max_bend_deg": -15.9,
                    "backward_frames": [
                        0,
                        1,
                        2,
                        3,
                        4,
                        5,
                        6,
                        7,
                        8,
                        9,
                        10,
                        11,
                        12,
                        13,
                        14,
                        15,
                        16,
                        17,
                        18,
                        19,
                        20,
                        21,
                        22,
                        23,
                        24,
                        25,
                        26,
                        27,
                        28,
                        29,
                        30,
                        31,
                        32,
                        33,
                        34,
                        35,
                        36,
                        37,
                        38,
                        39,
                    ],
                    "worst_backward_deg": 15.9,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 42.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 0.0,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 46.2,
                "com_accel_max_m_s2": 0.0,
                "one_foot_off_balance_m": 0.108,
                "one_foot_side": "r",
                "linear_runs": {},
                "block_bob": [
                    "WARN the head, hands bob with the hips on the same frame: the body moves as one block. Let the motion ripple up: the head and hands trail the hips by a frame or two (2-6 in good idles)."
                ],
            },
            [
                "FAIL left knee bends backwards (16 degrees, 40 frames). A knee is a hinge: it only folds forward.",
                "WARN standing on the right foot with the weight 11 cm off it: shift the hips over the standing foot before the other one lifts (weight shifts lead).",
                "WARN the head, hands bob with the hips on the same frame: the body moves as one block. Let the motion ripple up: the head and hands trail the hips by a frame or two (2-6 in good idles).",
            ],
        ),
        "idle_float": (
            {
                "knee_l": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 42.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 0.0,
                "airborne_frames": 20,
                "longest_airborne": 20,
                "air_gravity_m_s2": [10.29],
                "hang_share": [0.4],
                "steps_per_min": 92.3,
                "com_accel_max_m_s2": 0.0,
                "one_foot_off_balance_m": 0.108,
                "one_foot_side": "l",
                "linear_runs": {},
                "block_bob": [
                    "WARN the head, hands bob with the hips on the same frame: the body moves as one block. Let the motion ripple up: the head and hands trail the hips by a frame or two (2-6 in good idles)."
                ],
            },
            [
                "WARN both feet leave the ground for 20 frames and nothing launches the body: outside a run or a jump, one foot stays down.",
                "WARN standing on the left foot with the weight 11 cm off it: shift the hips over the standing foot before the other one lifts (weight shifts lead).",
                "WARN the head, hands bob with the hips on the same frame: the body moves as one block. Let the motion ripple up: the head and hands trail the hips by a frame or two (2-6 in good idles).",
            ],
        ),
        "jump": (
            {
                "knee_l": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [1, 2, 3, 4, 5, 6, 7, 8, 21, 22, 23, 24, 25, 26, 27, 28],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": 6.1,
                    "backward_frames": [11, 12, 13, 14, 15, 16, 17, 18, 31, 32, 33, 34, 35, 36, 37, 38],
                    "worst_backward_deg": 25.7,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 42.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 23.7,
                "airborne_frames": 20,
                "longest_airborne": 20,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 184.6,
                "com_accel_max_m_s2": 0.0,
                "linear_runs": {},
            },
            [
                "FAIL left knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
                "FAIL right knee bends backwards (26 degrees, 16 frames). A knee is a hinge: it only folds forward.",
            ],
        ),
        "knee_back": (
            {
                "knee_l": {
                    "max_bend_deg": 82.7,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": 82.7,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 151.9},
                "spine": {"bend_deg": 0.0, "twist_deg": 40.0},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 52.9,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 184.6,
                "com_accel_max_m_s2": 0.0,
                "arm_leg_corr": -1.0,
                "arm_swing_m": 0.576,
                "leg_swing_m": 0.742,
                "chest_hip_corr": -1.0,
                "hip_turn_deg": 8.0,
                "chest_turn_deg": 12.0,
                "linear_runs": {},
                "lean": {"mean_deg": -0.0, "excess_deg": 0.0, "range_deg": 0.0, "turning": False},
            },
            [
                "FAIL head turns 152 degrees against the chest: a neck turns about 80 and nods about 60. Turn the chest and shoulders too. Past anything a body can do: a broken clip (a mirrored bone) or GaitKeeper misreading the rig gives this. Measure the joint on the bones before blaming the clip.",
                "WARN a thigh swings 53 degrees behind the pelvis: a hip extends about 20 walking and 30 sprinting. Tilt the pelvis forward to get more.",
                "WARN 185 steps a minute: a walk is 100-120 (shuffling or rushing).",
            ],
        ),
        "punch": (
            {
                "knee_l": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 177.7,
                    "backward_frames": [12, 13, 14, 15, 16],
                    "worst_backward_deg": 176.1,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 80.2},
                "spine": {"bend_deg": 0.0, "twist_deg": 78.8},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 0.0,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 276.9,
                "com_accel_max_m_s2": 0.0,
                "linear_runs": {"right hand": (2, 9)},
                "strike": {
                    "peak_speed_m_s": 3.6,
                    "hit_frames": 19,
                    "hit_start": 8,
                    "anticipation_s": 0.267,
                    "recovery_s": 0.4,
                    "windup_m": 0.0,
                    "reach_m": 0.66,
                    "effector": "hand_r",
                    "path_corners": [],
                    "tell_s": 0.233,
                    "chest_turn_deg": 78.0,
                    "chain_peaks": [19, 31, 0, 23, 10],
                    "follow_through_s": 0.0,
                    "body_follow_s": 0.3,
                },
            },
            [
                "FAIL right elbow bends the wrong way (176 degrees, 5 frames). An elbow is a hinge: it only folds one way. Past anything a body can do: a broken clip (a mirrored bone) or GaitKeeper misreading the rig gives this. Measure the joint on the bones before blaming the clip.",
                "FAIL right elbow folds 178 degrees: an elbow stops at about 150, where the forearm meets the upper arm.",
                "WARN the hit takes 19 frames (19 at 30 fps): 4-8 frames at 30 fps reads as a hit; longer reads as a push.",
                "WARN the hand is fastest before the chest moves: power runs hips, chest, shoulder, elbow, hand, each a frame or two after the last.",
            ],
        ),
        "enemy": (
            {
                "knee_l": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 177.7,
                    "backward_frames": [12, 13, 14, 15, 16],
                    "worst_backward_deg": 176.1,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 80.2},
                "spine": {"bend_deg": 0.0, "twist_deg": 78.8},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 0.0,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 276.9,
                "com_accel_max_m_s2": 0.0,
                "linear_runs": {"right hand": (2, 9)},
                "strike": {
                    "peak_speed_m_s": 3.6,
                    "hit_frames": 19,
                    "hit_start": 8,
                    "anticipation_s": 0.267,
                    "recovery_s": 0.4,
                    "windup_m": 0.0,
                    "reach_m": 0.66,
                    "effector": "hand_r",
                    "path_corners": [],
                    "tell_s": 0.233,
                    "chest_turn_deg": 78.0,
                    "chain_peaks": [19, 31, 0, 23, 10],
                    "follow_through_s": 0.0,
                    "body_follow_s": 0.3,
                },
            },
            [
                "FAIL right elbow bends the wrong way (176 degrees, 5 frames). An elbow is a hinge: it only folds one way. Past anything a body can do: a broken clip (a mirrored bone) or GaitKeeper misreading the rig gives this. Measure the joint on the bones before blaming the clip.",
                "FAIL right elbow folds 178 degrees: an elbow stops at about 150, where the forearm meets the upper arm.",
                "WARN the right hand's strike gives 233 ms from its first move to the hit: players need about 300 ms to react to what they see, so an enemy can't open with it (it's fine as a follow-up in a combo, or for the player's own attacks). Hold or slow the wind-up.",
                "WARN the hit takes 19 frames (19 at 30 fps): 4-8 frames at 30 fps reads as a hit; longer reads as a push.",
                "WARN the hand is fastest before the chest moves: power runs hips, chest, shoulder, elbow, hand, each a frame or two after the last.",
            ],
        ),
        "punch_no_roles": (
            {
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 276.9,
                "com_accel_max_m_s2": 0.0,
                "linear_runs": {"right hand": (2, 9)},
                "strike": {
                    "peak_speed_m_s": 3.6,
                    "hit_frames": 19,
                    "hit_start": 8,
                    "anticipation_s": 0.267,
                    "recovery_s": 0.4,
                    "windup_m": 0.0,
                    "reach_m": 0.66,
                    "effector": "hand_r",
                    "path_corners": [],
                    "tell_s": 0.233,
                    "follow_through_s": 0.0,
                    "body_follow_s": 0.3,
                },
            },
            [
                "WARN the hit takes 19 frames (19 at 30 fps): 4-8 frames at 30 fps reads as a hit; longer reads as a push."
            ],
        ),
        "punch_dropped_keys": (
            {
                "knee_l": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 177.7,
                    "backward_frames": [12, 13, 14, 15, 16],
                    "worst_backward_deg": 176.1,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 80.2},
                "spine": {"bend_deg": 0.0, "twist_deg": 78.8},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 0.0,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 276.9,
                "com_accel_max_m_s2": 0.0,
                "linear_runs": {"right hand": (2, 9)},
                "strike": {
                    "peak_speed_m_s": 3.6,
                    "hit_frames": 19,
                    "hit_start": 8,
                    "anticipation_s": 0.267,
                    "recovery_s": 0.4,
                    "windup_m": 0.0,
                    "reach_m": 0.66,
                    "effector": "hand_r",
                    "path_corners": [],
                    "tell_s": 0.233,
                    "chest_turn_deg": 78.0,
                    "chain_peaks": [19, 31, 0, 23, 10],
                    "follow_through_s": 0.0,
                    "body_follow_s": 0.3,
                },
            },
            [
                "FAIL right elbow bends the wrong way (176 degrees, 5 frames). An elbow is a hinge: it only folds one way. Past anything a body can do: a broken clip (a mirrored bone) or GaitKeeper misreading the rig gives this. Measure the joint on the bones before blaming the clip.",
                "FAIL right elbow folds 178 degrees: an elbow stops at about 150, where the forearm meets the upper arm.",
                "WARN the hit takes 19 frames (19 at 30 fps): 4-8 frames at 30 fps reads as a hit; longer reads as a push.",
                "WARN the hand is fastest before the chest moves: power runs hips, chest, shoulder, elbow, hand, each a frame or two after the last.",
            ],
        ),
        "short": (
            {
                "knee_l": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 0.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 0.0},
                "wrist_l": {"bend_deg": 9.5, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 32.3, "twist_deg": 0.0},
                "hip_extension_deg": 0.0,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 3600.0,
                "com_accel_max_m_s2": 0.0,
                "arm_leg_corr": 0.0,
                "arm_swing_m": 0.0,
                "leg_swing_m": 0.0,
                "chest_hip_corr": 0.0,
                "hip_turn_deg": 0.0,
                "chest_turn_deg": 0.0,
                "linear_runs": {},
                "lean": {"mean_deg": 0.0, "excess_deg": 0.0, "range_deg": 0.0, "turning": False},
            },
            ["WARN 3600 steps a minute: a walk is 100-120 (shuffling or rushing)."],
        ),
        "single": (
            {
                "knee_l": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 0.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 0.0},
                "wrist_l": {"bend_deg": 9.5, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 32.3, "twist_deg": 0.0},
                "hip_extension_deg": 0.0,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 120.0,
                "com_accel_max_m_s2": 0.0,
                "one_foot_off_balance_m": 0.0,
                "one_foot_side": "",
                "linear_runs": {},
            },
            [],
        ),
        "single_punch": (
            {
                "knee_l": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 0.0},
                "spine": {"bend_deg": 0.0, "twist_deg": 0.0},
                "wrist_l": {"bend_deg": 9.5, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 32.3, "twist_deg": 0.0},
                "hip_extension_deg": 0.0,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 120.0,
                "com_accel_max_m_s2": 0.0,
                "linear_runs": {},
            },
            [],
        ),
        "punch_no_hips": (
            {
                "knee_l": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_l": {
                    "max_bend_deg": 0.0,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "knee_r": {
                    "max_bend_deg": -8.9,
                    "backward_frames": [],
                    "worst_backward_deg": 0.0,
                    "worst_sideways_deg": 0.0,
                },
                "elbow_r": {
                    "max_bend_deg": 177.7,
                    "backward_frames": [12, 13, 14, 15, 16],
                    "worst_backward_deg": 176.1,
                    "worst_sideways_deg": 0.0,
                },
                "neck": {"bend_deg": 0.0, "twist_deg": 80.2},
                "spine": {"bend_deg": 0.0, "twist_deg": 78.8},
                "wrist_l": {"bend_deg": 33.7, "twist_deg": 0.0},
                "wrist_r": {"bend_deg": 33.6, "twist_deg": 0.0},
                "hip_extension_deg": 0.0,
                "airborne_frames": 0,
                "longest_airborne": 0,
                "air_gravity_m_s2": [],
                "hang_share": [],
                "steps_per_min": 276.9,
                "com_accel_max_m_s2": 0.0,
                "linear_runs": {"right hand": (2, 9)},
                "strike": {
                    "peak_speed_m_s": 3.6,
                    "hit_frames": 19,
                    "hit_start": 8,
                    "anticipation_s": 0.267,
                    "recovery_s": 0.4,
                    "windup_m": 0.0,
                    "reach_m": 0.66,
                    "effector": "hand_r",
                    "path_corners": [],
                    "tell_s": 0.233,
                    "chest_turn_deg": 78.0,
                    "chain_peaks": [19, 31, 0, 23, 10],
                    "follow_through_s": 0.0,
                    "body_follow_s": 0.3,
                },
            },
            [
                "FAIL right elbow bends the wrong way (176 degrees, 5 frames). An elbow is a hinge: it only folds one way. Past anything a body can do: a broken clip (a mirrored bone) or GaitKeeper misreading the rig gives this. Measure the joint on the bones before blaming the clip.",
                "FAIL right elbow folds 178 degrees: an elbow stops at about 150, where the forearm meets the upper arm.",
                "WARN the hit takes 19 frames (19 at 30 fps): 4-8 frames at 30 fps reads as a hit; longer reads as a push.",
                "WARN the hand is fastest before the chest moves: power runs hips, chest, shoulder, elbow, hand, each a frame or two after the last.",
            ],
        ),
    },
    "minimal_punch": (
        {
            "linear_runs": {"right hand": (14, 12)},
            "strike": {
                "peak_speed_m_s": 3.6,
                "hit_frames": 5,
                "hit_start": 3,
                "anticipation_s": 0.1,
                "recovery_s": 0.8,
                "windup_m": 0.0,
                "reach_m": 0.6,
                "effector": "hand_r",
                "path_corners": [],
                "tell_s": 0.0,
                "windup_split": {
                    "windup": (3, 7),
                    "strike": (12, 25),
                    "windup_m_s": 3.6,
                    "strike_m_s": 2.7,
                    "windup_m": 0.6,
                },
                "follow_through_s": 0.0,
            },
        },
        [
            "WARN right hand moves at one steady speed for 14 frames from frame 12: even spacing reads as mechanical. Ease out of the first pose and into the next (slow, fast, slow).",
            "WARN the right hand's strike: the wind-up (3.6 m/s) is faster than the strike itself (2.7 m/s), so the draw-back reads as the attack and the hit looks weak. Draw back slower (a held coil), then make the strike the fastest move in the clip.",
        ],
    ),
    "issues": {
        "empty": [],
        "everything_walk": [
            (
                "knee_back_l",
                30,
                "FAIL left knee bends backwards (30 degrees, 2 frames). A knee is a hinge: it only folds forward.",
            ),
            (
                "knee_fold_l",
                170,
                "FAIL left knee folds 170 degrees: past a full squat (about 155), so the shin is passing through the thigh.",
            ),
            (
                "knee_side_l",
                25,
                "WARN left knee bends sideways (25 degrees off its hinge): knees don't bend side to side; turn the thigh instead.",
            ),
            (
                "elbow_back_l",
                20,
                "FAIL left elbow bends the wrong way (20 degrees, 2 frames). An elbow is a hinge: it only folds one way.",
            ),
            (
                "elbow_side_l",
                30,
                "WARN left elbow bends sideways (30 degrees off its hinge): twist the forearm or turn the shoulder instead.",
            ),
            (
                "knee_back_r",
                80,
                "FAIL right knee bends backwards (80 degrees, 3 frames). A knee is a hinge: it only folds forward. Past anything a body can do: a broken clip (a mirrored bone) or GaitKeeper misreading the rig gives this. Measure the joint on the bones before blaming the clip.",
            ),
            (
                "wrist_r",
                120,
                "FAIL right wrist bends 120 degrees: a wrist manages about 80 forward, 70 back, 30 to the side.",
            ),
            (
                "float",
                5,
                "WARN both feet leave the ground for 5 frames and nothing launches the body: outside a run or a jump, one foot stays down.",
            ),
            (
                "floaty",
                5.8100000000000005,
                "WARN in the air the body falls at 4.0 m/s each second (real gravity is 9.8): it floats. Fine for a stylised game jump if the game's gravity matches.",
            ),
            (
                "heavy",
                10.19,
                "WARN in the air the body falls at 20.0 m/s each second (real gravity is 9.8): it drops like it's pulled down. Snappy, but check the game's jump gravity matches.",
            ),
            (
                "hang",
                0.9,
                "WARN no hang time in the air: the body spends only 10% of the flight near the top of its arc (a thrown body spends about half). It moves up and down at one speed. Leave the ground fast, slow into the top and hang there, then speed up on the way down (fast, slow, fast).",
            ),
            (
                "lean",
                20.0,
                "WARN the body lists 10 degrees to the right the whole time on a straight line: it reads as drunk or injured. Stand the spine up over the hips.",
            ),
            (
                "jerk",
                45.0,
                "WARN the body changes speed at 45 m/s every second while on its feet (over three times the pull of gravity): legs can't push that hard. Ease into stops and starts.",
            ),
            (
                "one_foot",
                0.12,
                "WARN standing on the right foot with the weight 12 cm off it: shift the hips over the standing foot before the other one lifts (weight shifts lead).",
            ),
            ("cadence", 40.0, "WARN 150 steps a minute: a walk is 100-120 (shuffling or rushing)."),
            (
                "same_side",
                0.5,
                "WARN arms swing with the same-side leg (marching like a robot): each arm swings forward with the opposite leg.",
            ),
            (
                "no_counter",
                0.8,
                "WARN the chest turns with the hips instead of against them: in a walk the shoulders twist the opposite way to the hips.",
            ),
            (
                "linear",
                12,
                "WARN head moves at one steady speed for 12 frames from frame 0 (also left hand): even spacing reads as mechanical. Ease out of the first pose and into the next (slow, fast, slow).",
            ),
            ("block", 1.0, "WARN the head bobs with the hips."),
        ],
        "everything_jump": [
            (
                "knee_back_l",
                30,
                "FAIL left knee bends backwards (30 degrees, 2 frames). A knee is a hinge: it only folds forward.",
            ),
            (
                "knee_fold_l",
                170,
                "FAIL left knee folds 170 degrees: past a full squat (about 155), so the shin is passing through the thigh.",
            ),
            (
                "knee_side_l",
                25,
                "WARN left knee bends sideways (25 degrees off its hinge): knees don't bend side to side; turn the thigh instead.",
            ),
            (
                "elbow_back_l",
                20,
                "FAIL left elbow bends the wrong way (20 degrees, 2 frames). An elbow is a hinge: it only folds one way.",
            ),
            (
                "elbow_side_l",
                30,
                "WARN left elbow bends sideways (30 degrees off its hinge): twist the forearm or turn the shoulder instead.",
            ),
            (
                "knee_back_r",
                80,
                "FAIL right knee bends backwards (80 degrees, 3 frames). A knee is a hinge: it only folds forward. Past anything a body can do: a broken clip (a mirrored bone) or GaitKeeper misreading the rig gives this. Measure the joint on the bones before blaming the clip.",
            ),
            (
                "wrist_r",
                120,
                "FAIL right wrist bends 120 degrees: a wrist manages about 80 forward, 70 back, 30 to the side.",
            ),
            (
                "floaty",
                5.8100000000000005,
                "WARN in the air the body falls at 4.0 m/s each second (real gravity is 9.8): it floats. Fine for a stylised game jump if the game's gravity matches.",
            ),
            (
                "heavy",
                10.19,
                "WARN in the air the body falls at 20.0 m/s each second (real gravity is 9.8): it drops like it's pulled down. Snappy, but check the game's jump gravity matches.",
            ),
            (
                "hang",
                0.9,
                "WARN no hang time in the air: the body spends only 10% of the flight near the top of its arc (a thrown body spends about half). It moves up and down at one speed. Leave the ground fast, slow into the top and hang there, then speed up on the way down (fast, slow, fast).",
            ),
            (
                "lean",
                20.0,
                "WARN the body lists 10 degrees to the right the whole time on a straight line: it reads as drunk or injured. Stand the spine up over the hips.",
            ),
            (
                "jerk",
                45.0,
                "WARN the body changes speed at 45 m/s every second while on its feet (over three times the pull of gravity): legs can't push that hard. Ease into stops and starts.",
            ),
            (
                "one_foot",
                0.12,
                "WARN standing on the right foot with the weight 12 cm off it: shift the hips over the standing foot before the other one lifts (weight shifts lead).",
            ),
            (
                "same_side",
                0.5,
                "WARN arms swing with the same-side leg (marching like a robot): each arm swings forward with the opposite leg.",
            ),
            (
                "no_counter",
                0.8,
                "WARN the chest turns with the hips instead of against them: in a walk the shoulders twist the opposite way to the hips.",
            ),
            (
                "linear",
                12,
                "WARN head moves at one steady speed for 12 frames from frame 0 (also left hand): even spacing reads as mechanical. Ease out of the first pose and into the next (slow, fast, slow).",
            ),
            ("block", 1.0, "WARN the head bobs with the hips."),
        ],
        "everything_feet_off": [
            (
                "knee_back_l",
                30,
                "FAIL left knee bends backwards (30 degrees, 2 frames). A knee is a hinge: it only folds forward.",
            ),
            (
                "knee_fold_l",
                170,
                "FAIL left knee folds 170 degrees: past a full squat (about 155), so the shin is passing through the thigh.",
            ),
            (
                "knee_side_l",
                25,
                "WARN left knee bends sideways (25 degrees off its hinge): knees don't bend side to side; turn the thigh instead.",
            ),
            (
                "elbow_back_l",
                20,
                "FAIL left elbow bends the wrong way (20 degrees, 2 frames). An elbow is a hinge: it only folds one way.",
            ),
            (
                "elbow_side_l",
                30,
                "WARN left elbow bends sideways (30 degrees off its hinge): twist the forearm or turn the shoulder instead.",
            ),
            (
                "knee_back_r",
                80,
                "FAIL right knee bends backwards (80 degrees, 3 frames). A knee is a hinge: it only folds forward. Past anything a body can do: a broken clip (a mirrored bone) or GaitKeeper misreading the rig gives this. Measure the joint on the bones before blaming the clip.",
            ),
            (
                "wrist_r",
                120,
                "FAIL right wrist bends 120 degrees: a wrist manages about 80 forward, 70 back, 30 to the side.",
            ),
            (
                "floaty",
                5.8100000000000005,
                "WARN in the air the body falls at 4.0 m/s each second (real gravity is 9.8): it floats. Fine for a stylised game jump if the game's gravity matches.",
            ),
            (
                "heavy",
                10.19,
                "WARN in the air the body falls at 20.0 m/s each second (real gravity is 9.8): it drops like it's pulled down. Snappy, but check the game's jump gravity matches.",
            ),
            (
                "hang",
                0.9,
                "WARN no hang time in the air: the body spends only 10% of the flight near the top of its arc (a thrown body spends about half). It moves up and down at one speed. Leave the ground fast, slow into the top and hang there, then speed up on the way down (fast, slow, fast).",
            ),
            (
                "lean",
                20.0,
                "WARN the body lists 10 degrees to the right the whole time on a straight line: it reads as drunk or injured. Stand the spine up over the hips.",
            ),
            (
                "jerk",
                45.0,
                "WARN the body changes speed at 45 m/s every second while on its feet (over three times the pull of gravity): legs can't push that hard. Ease into stops and starts.",
            ),
            (
                "one_foot",
                0.12,
                "WARN standing on the right foot with the weight 12 cm off it: shift the hips over the standing foot before the other one lifts (weight shifts lead).",
            ),
            ("cadence", 40.0, "WARN 150 steps a minute: a walk is 100-120 (shuffling or rushing)."),
            (
                "same_side",
                0.5,
                "WARN arms swing with the same-side leg (marching like a robot): each arm swings forward with the opposite leg.",
            ),
            (
                "no_counter",
                0.8,
                "WARN the chest turns with the hips instead of against them: in a walk the shoulders twist the opposite way to the hips.",
            ),
            (
                "linear",
                12,
                "WARN head moves at one steady speed for 12 frames from frame 0 (also left hand): even spacing reads as mechanical. Ease out of the first pose and into the next (slow, fast, slow).",
            ),
            ("block", 1.0, "WARN the head bobs with the hips."),
        ],
        "run_no_flight": [
            (
                "no_flight",
                1.0,
                "WARN a run with no moment where both feet are off the ground: it reads as a fast walk. A run leaves the ground on every step.",
            )
        ],
        "slow_turn": [
            (
                "lean",
                20.0,
                "WARN the body leans 20 degrees further sideways than the move needs: it looks drunk or about to fall. Clamp the lean to what the turn's speed asks for (a few degrees walking).",
            ),
            ("cadence", 50.0, "WARN 60 steps a minute: a walk is 100-120 (very slow, like wading)."),
        ],
        "enemy_kick": [
            (
                "tell",
                0.1,
                "WARN the left toe's strike gives 100 ms from its first move to the hit: players need about 300 ms to react to what they see, so an enemy can't open with it (it's fine as a follow-up in a combo, or for the player's own attacks). Hold or slow the wind-up.",
            ),
            (
                "windup_fast",
                4.0,
                "WARN the left toe's strike: the wind-up (4.0 m/s) is faster than the strike itself (2.0 m/s), so the draw-back reads as the attack and the hit looks weak. Draw back slower (a held coil), then make the strike the fastest move in the clip.",
            ),
            (
                "no_windup",
                0.6,
                "WARN the toe_l strikes 0.60 m from the first frame with no wind-up: a big hit needs a lead-in (anticipation), even a short one.",
            ),
            (
                "slow_hit",
                12.0,
                "WARN the hit takes 12 frames (12 at 30 fps): 4-8 frames at 30 fps reads as a hit; longer reads as a push.",
            ),
            (
                "stiff_body",
                0.6,
                "WARN only the limb moves: the chest stays still. Let the move ripple into the shoulder and chest a little (everything is connected).",
            ),
            (
                "arc",
                2,
                "WARN the toe_l turns a sharp corner at speed on frames [3, 5]: its path should be an arc that slows into a change of direction. Round the path (add a breakdown key on the arc).",
            ),
            (
                "chain",
                6,
                "WARN the hand is fastest before the chest moves: power runs hips, chest, shoulder, elbow, hand, each a frame or two after the last.",
            ),
        ],
        "kick": [
            (
                "windup_fast",
                4.0,
                "WARN the left toe's strike: the wind-up (4.0 m/s) is faster than the strike itself (2.0 m/s), so the draw-back reads as the attack and the hit looks weak. Draw back slower (a held coil), then make the strike the fastest move in the clip.",
            ),
            (
                "no_windup",
                0.6,
                "WARN the toe_l strikes 0.60 m from the first frame with no wind-up: a big hit needs a lead-in (anticipation), even a short one.",
            ),
            (
                "slow_hit",
                12.0,
                "WARN the hit takes 12 frames (12 at 30 fps): 4-8 frames at 30 fps reads as a hit; longer reads as a push.",
            ),
            (
                "stiff_body",
                0.6,
                "WARN only the limb moves: the chest stays still. Let the move ripple into the shoulder and chest a little (everything is connected).",
            ),
            (
                "arc",
                2,
                "WARN the toe_l turns a sharp corner at speed on frames [3, 5]: its path should be an arc that slows into a change of direction. Round the path (add a breakdown key on the arc).",
            ),
            (
                "chain",
                6,
                "WARN the hand is fastest before the chest moves: power runs hips, chest, shoulder, elbow, hand, each a frame or two after the last.",
            ),
        ],
        "enemy_forearm": [],
        "weapon": [
            (
                "windup_fast",
                4.0,
                "WARN the weapon's strike: the wind-up (4.0 m/s) is faster than the strike itself (2.0 m/s), so the draw-back reads as the attack and the hit looks weak. Draw back slower (a held coil), then make the strike the fastest move in the clip.",
            ),
            (
                "no_windup",
                0.6,
                "WARN the weapon strikes 0.60 m from the first frame with no wind-up: a big hit needs a lead-in (anticipation), even a short one.",
            ),
            (
                "slow_hit",
                12.0,
                "WARN the hit takes 12 frames (12 at 30 fps): 4-8 frames at 30 fps reads as a hit; longer reads as a push.",
            ),
            (
                "stiff_body",
                0.6,
                "WARN only the limb moves: the chest stays still. Let the move ripple into the shoulder and chest a little (everything is connected).",
            ),
            (
                "arc",
                2,
                "WARN the weapon turns a sharp corner at speed on frames [3, 5]: its path should be an arc that slows into a change of direction. Round the path (add a breakdown key on the arc).",
            ),
        ],
    },
    "after": [
        "FAIL head turns 130 degrees against the chest: a neck turns about 80 and nods about 60. Turn the chest and shoulders too."
    ],
}


class MeasureBodyPinned(unittest.TestCase):
    def test_measurements_and_verdicts_are_unchanged(self):
        for label in SCENARIOS:
            with self.subTest(label):
                self.assertEqual(measure(label), EXPECTED["measure"][label])

    def test_minimal_punch_is_unchanged(self):
        b = body.measure_body(minimal_punch(), FPS, {}, {}, {}, "Punch_Haymaker", False, False, False)
        self.assertEqual((b, body.body_verdicts(b, None, "Punch_Haymaker", False, FPS)), EXPECTED["minimal_punch"])


class IssuesPinned(unittest.TestCase):
    def test_issue_keys_sizes_and_messages_are_unchanged(self):
        for label, (b, name, feet_off) in ISSUES.items():
            with self.subTest(label):
                self.assertEqual(body._issues(b, name, feet_off, FPS), EXPECTED["issues"][label])

    def test_before_and_after_compare_is_unchanged(self):
        after = {**EVERYTHING, "neck": {"bend_deg": 130, "twist_deg": 10}, "hip_extension_deg": 41}
        got = body.body_verdicts(EVERYTHING, after, "Walk_Fwd", False, FPS)
        self.assertEqual(got, EXPECTED["after"])
