# SPDX-License-Identifier: GPL-3.0-or-later
"""Quaternion and timing maths (core.motion_math)."""

import unittest

from conftest import axis_q
from core import motion_math


class Quats(unittest.TestCase):
    def test_slerp_halfway(self):
        q = motion_math.q_slerp((1, 0, 0, 0), axis_q((0, 0, 1), 90), 0.5)
        self.assertAlmostEqual(motion_math.q_angle_deg((1, 0, 0, 0), q), 45, places=4)


class Time(unittest.TestCase):
    def test_loop_blend_ends_on_first_frame(self):
        w = motion_math.loop_blend_weights(10, 3)
        self.assertEqual(w[-1], 1.0)
        self.assertEqual(w[:7], [0.0] * 7)


class Checks(unittest.TestCase):
    def walk(self, slide=0.0):
        """A planted foot moving back at 1 m/s (treadmill) for 10 frames, then swinging."""
        fps, pos = 30.0, []
        for i in range(20):
            if i < 10:
                jitter = slide / fps * (1 if i % 2 else -1)
                pos.append((0.0, -i / fps + jitter, 0.0))
            else:
                pos.append((0.0, -0.3 + (i - 10) * 0.06, 0.1))
        return pos, fps

    def test_contacts_and_runs(self):
        pos, fps = self.walk()
        h = [p[2] for p in pos]
        sp = [abs(pos[min(i + 1, 19)][2] - pos[i][2]) * fps for i in range(20)]
        flags = motion_math.contacts(h, sp, 0.0)
        self.assertEqual(sum(flags[:9]), 9)
        self.assertEqual(motion_math.runs([True, True, False, True], cyclic=True), [(3, 3)])

    def test_a_low_sweep_is_not_planted_but_a_floor_drag_is(self):
        # in place: the planted foot moves back 3 cm a frame; then it sweeps forward 12 cm a frame
        ys = [i * 0.03 for i in range(20)] + [0.57 - 0.12 * k for k in range(1, 5)]
        lifted = [(0, y, 0.0 if i < 20 else 0.012) for i, y in enumerate(ys)]
        flags = [True] * len(ys)
        out = motion_math.drop_sweeps(lifted, flags, 30, False)
        self.assertTrue(all(out[:19]))
        self.assertFalse(any(out[20:]))  # 1 cm up and racing forward: a swing, not a slide
        dragged = [(0, y, 0.0) for y in ys]
        self.assertTrue(all(motion_math.drop_sweeps(dragged, flags, 30, False)))  # on the floor: a drag, stays planted

    def test_ground_speed_ignores_a_few_dragged_frames(self):
        still = [(0, 0, 0)] * 10 + [(0, 0.3 * k, 0) for k in range(1, 4)]
        self.assertAlmostEqual(motion_math.treadmill_velocity(still, [True] * 13, 30, robust=True)[1], 0.0)

    def test_treadmill_is_not_sliding(self):
        pos, fps = self.walk()
        flags = [i < 10 for i in range(20)]
        tm = motion_math.treadmill_velocity(pos, flags, fps)
        self.assertAlmostEqual(tm[1], -1.0, places=6)
        self.assertLess(max(motion_math.slide_per_contact(pos, flags, fps, False, tm)), 1e-6)

    def test_jitter_is_sliding(self):
        pos, fps = self.walk(slide=0.5)
        flags = [i < 10 for i in range(20)]
        tm = motion_math.treadmill_velocity(pos, flags, fps)
        self.assertGreater(max(motion_math.slide_per_contact(pos, flags, fps, False, tm)), 0.5)

    def test_pops_find_spikes_not_smooth_fast_moves(self):
        smooth_fast = [2, 6, 12, 18, 12, 6, 2]
        self.assertEqual(motion_math.pops(smooth_fast), [])
        self.assertEqual(motion_math.pops([2, 2, 30, 2, 2]), [2])

    def test_pops_find_a_one_frame_spike_out_and_back(self):
        # a 35-degree calf spike (steps 30 then 37) hid itself from the rule above.
        steps, back = [5, 6, 30, 37, 3, 5], [10, 25, 8, 36, 8]
        self.assertEqual(motion_math.pops(steps, skip_angles=back), [3])
        self.assertEqual(motion_math.pops(steps), [])  # without the poses, only the old rule runs
        # a strike snapping into a new pose and holding it is a style, not a pop
        self.assertEqual(motion_math.pops(steps, skip_angles=[10, 25, 60, 36, 8]), [])
        self.assertEqual(motion_math.pops([2, 6, 12, 18, 12, 6, 2], skip_angles=[8, 18, 30, 30, 18]), [])

    def test_balance_helpers(self):
        c = motion_math.com([((0, 0, 1), 1.0), ((2, 0, 1), 1.0)])
        self.assertEqual(c, (1.0, 0.0, 1.0))
        self.assertAlmostEqual(motion_math.dist_to_segment2d((1, 1), (0, 0), (2, 0)), 1.0)

    def test_support_area_of_both_feet(self):
        feet = [(0, 0), (0, 0.25), (0.3, 0), (0.3, 0.25)]  # two feet side by side, toes forward
        self.assertEqual(motion_math.outside_support((0.15, 0.1), feet), 0.0)
        self.assertAlmostEqual(motion_math.outside_support((0.15, 0.45), feet), 0.2)
        self.assertAlmostEqual(motion_math.outside_support((0.5, 0.0), [(0, 0)]), 0.5)

    def test_still_idle_foot_counts_as_planted(self):
        self.assertEqual(motion_math.contacts([0.0, 0.001, 0.0], [0.001, 0.002, 0.001], 0.0), [True, True, True])
