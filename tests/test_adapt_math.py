# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose Adapt blending maths (core.adapt_math)."""

import math
import unittest

from core import adapt_math as AM


class PoseAdapt(unittest.TestCase):
    """Where one pose edit lands in a clip (adapt_math): no Blender needed."""

    @staticmethod
    def gait(n, cycles, phase=0.0):
        """A foot's height and reach over a loop of n distinct frames holding `cycles` gait cycles."""
        t = [2 * math.pi * cycles * i / n + phase for i in range(n)]
        return [[max(0.0, math.sin(x)) * 0.1 for x in t], [0.3 * math.cos(x) for x in t]]

    def test_bump_is_one_at_the_edit_and_fades_flat(self):
        self.assertEqual(AM.bump(0, 4), 1.0)
        self.assertAlmostEqual(AM.bump(2, 4), 0.5)
        self.assertEqual(AM.bump(4, 4), 0.0)
        self.assertLess(AM.bump(3.9, 4), 0.01)  # flat as it ends: no jerk

    def test_period_of_one_and_two_cycle_loops(self):
        self.assertEqual(AM.step_period(self.gait(32, 1), 30, True), 32)
        self.assertEqual(AM.step_period(self.gait(64, 2), 30, True), 32)

    def test_one_off_clip_that_never_repeats_has_no_period(self):
        ramp = [[i * 0.01 for i in range(40)], [i * i * 0.001 for i in range(40)]]
        self.assertIsNone(AM.step_period(ramp, 30, False))

    def test_sides_take_turns_in_a_walk_not_in_a_hop(self):
        left = self.gait(32, 1)
        self.assertTrue(AM.sides_alternate(left, self.gait(32, 1, math.pi), 32, True))
        self.assertFalse(AM.sides_alternate(left, self.gait(32, 1), 32, True))  # both feet together: a hop

    def test_two_poses_close_together_blend_and_far_apart_fade(self):
        # close (gap 8 <= 2 x 6): a smooth run from one pose to the next, full strength between
        a, b, u, w = AM.blend_plan([4.0, 12.0], 8.0, 32.0, False, 6.0)
        self.assertEqual((a, b, w), (0, 1, 1.0))
        self.assertAlmostEqual(u, 0.5)
        self.assertEqual(AM.blend_plan([4.0, 12.0], 4.0, 32.0, False, 6.0), (0, 0, 0.0, 1.0))  # exact on a pose
        # far apart (gap 20 > 12): each fades on its own, nothing in the middle
        self.assertIsNone(AM.blend_plan([4.0, 24.0], 14.0, 32.0, False, 6.0))
        # whole clip (no fade) round a loop: between the last pose and the first, across the seam
        a, b, u, w = AM.blend_plan([3.0, 19.0], 27.0, 32.0, True, None)
        self.assertEqual((a, b, w), (1, 0, 1.0))
        self.assertAlmostEqual(u, 0.5)
        # whole clip, not a loop: past the last pose it holds
        self.assertEqual(AM.blend_plan([3.0, 19.0], 30.0, 32.0, False, None), (1, 1, 0.0, 1.0))
