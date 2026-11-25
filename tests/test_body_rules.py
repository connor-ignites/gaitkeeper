# SPDX-License-Identifier: GPL-3.0-or-later
"""Body rules: joint angles, balance, timing helpers (core.body_rules)."""

import math
import unittest

from conftest import axis_q
from core import body_rules


class BodyRules(unittest.TestCase):
    """How a body can and can't move (core/body_rules.py)."""

    @staticmethod
    def leg(bends):
        # hip above knee above ankle, facing +Y; a positive bend folds the shin back (-Y)
        prox, joint, dist = [], [], []
        for a in bends:
            r = math.radians(a)
            prox.append((0.0, 0.0, 1.0))
            joint.append((0.0, 0.0, 0.5))
            dist.append((0.0, -0.5 * math.sin(r), 0.5 - 0.5 * math.cos(r)))
        return prox, joint, dist

    def test_knee_bending_backwards_fails(self):
        prox, joint, dist = self.leg([40] * 5 + [-40] * 3)
        anatomy = body_rules.cross((0, 0, -1), (0, -1, 0))  # the shin folds away from where the feet point
        r = body_rules.hinge(prox, joint, dist, [(1, 0, 0, 0)] * 8, ref_local=anatomy)
        self.assertEqual(r["backward_frames"], [5, 6, 7])
        self.assertAlmostEqual(r["worst_backward_deg"], 40, places=0)
        self.assertAlmostEqual(r["max_bend_deg"], 40, places=0)

    def test_one_stray_frame_is_not_a_pose(self):
        prox, joint, dist = self.leg([40, 40, -30, 40, 40])
        r = body_rules.hinge(prox, joint, dist, [(1, 0, 0, 0)] * 5, ref_local=(-1, 0, 0))
        self.assertEqual(r["backward_frames"], [])

    def test_clip_bent_backwards_throughout_is_still_caught(self):
        prox, joint, dist = self.leg([-50] * 6)
        r = body_rules.hinge(prox, joint, dist, [(1, 0, 0, 0)] * 6, ref_local=(-1, 0, 0))
        self.assertEqual(len(r["backward_frames"]), 6)

    def test_swinging_the_whole_leg_changes_nothing(self):
        prox, joint, dist = self.leg([30, 60, 90])
        q = axis_q((1, 0, 0), 50)  # the thigh swings forward 50 degrees
        moved = [[body_rules.q_rotate(q, p) for p in pts] for pts in (prox, joint, dist)]
        r = body_rules.hinge(*moved, [q] * 3, ref_local=(-1, 0, 0))
        self.assertEqual(r["backward_frames"], [])
        self.assertAlmostEqual(r["max_bend_deg"], 90, places=3)

    def test_knee_buckling_sideways_warns(self):
        prox, joint, dist = self.leg([40] * 6)
        for i in (3, 4):  # the shin swings 45 degrees out of its hinge plane
            dist[i] = (0.5 * math.sin(math.radians(45)), -0.3, 0.1)
        r = body_rules.hinge(prox, joint, dist, [(1, 0, 0, 0)] * 6, ref_local=(-1, 0, 0))
        self.assertGreater(r["worst_sideways_deg"], body_rules.HINGE_SIDEWAYS_WARN)

    def test_neck_twist_is_measured_against_the_chest(self):
        chest = axis_q((0, 0, 1), 30)  # the whole body has turned 30: that's fine
        head = body_rules.q_mul(chest, axis_q((0, 0, 1), 100))
        bend, twist = body_rules.relative_turn((1, 0, 0, 0), (1, 0, 0, 0), chest, head, (0, 0, 1))
        self.assertAlmostEqual(twist, 100, places=3)
        self.assertAlmostEqual(bend, 0, places=3)

    def test_gravity_from_a_jump_arc(self):
        fps = 30.0
        hs = [1.0 + 3.0 * (i / fps) - 0.5 * 9.81 * (i / fps) ** 2 for i in range(15)]
        self.assertAlmostEqual(body_rules.fall_acceleration(hs, fps), -9.81, places=3)

    def test_hip_extension_sign(self):
        down, fwd = (0, 0, -1), (0, 1, 0)
        back = (0, -math.sin(math.radians(30)), -math.cos(math.radians(30)))
        front = (0, math.sin(math.radians(60)), -math.cos(math.radians(60)))
        self.assertAlmostEqual(body_rules.hip_extension_deg(down, fwd, back), 30, places=3)
        self.assertLess(body_rules.hip_extension_deg(down, fwd, front), 0)

    def test_strike_wind_up(self):
        fps = 30.0
        windup = [(0, 0, 1.4)] * 3 + [(0, -0.05 * k, 1.4) for k in range(1, 5)]  # pulled back 20 cm
        punch = [(0, -0.2 + 0.25 * k, 1.4) for k in range(1, 5)]  # then 1 m forward in 4 frames
        st = body_rules.strike(windup + punch + [punch[-1]] * 6, fps)
        self.assertGreater(st["windup_m"], 0.15)
        self.assertLessEqual(st["hit_frames"], 6)
        cold = body_rules.strike([(0, 0.2 * k, 1.4) for k in range(5)] + [(0, 0.8, 1.4)] * 6, fps)
        self.assertEqual(cold["windup_m"], 0.0)

    def test_arm_swing_against_leg(self):
        t = [i / 32 * 2 * math.pi for i in range(32)]
        legs = [math.sin(x) for x in t]
        self.assertLess(body_rules.correlation([-math.sin(x) for x in t], legs), -0.99)
        self.assertGreater(body_rules.correlation(legs, legs), 0.99)
