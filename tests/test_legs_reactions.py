# SPDX-License-Identifier: GPL-3.0-or-later
"""Animal legs and hopping (core.legs) and reactions of loose parts (core.reactions)."""

import math
import unittest

from core import legs, reactions


class Legs(unittest.TestCase):
    @staticmethod
    def leg(knee_out, side, n=6):
        x = 0.15 if side == "r" else -0.15
        out = 1 if side == "r" else -1
        return [[(x, 0, 1.0), (x + out * knee_out, -0.1, 0.55), (x, 0.05, 0.1), (x, -0.1, 0.0)] for _ in range(n)]

    def test_splayed_knees_are_caught_and_straight_legs_pass(self):
        pel = [(0, 0, 1.0)] * 6
        bad = legs.measure({"hind_l": self.leg(0.15, "l"), "hind_r": self.leg(0.15, "r")}, pel, 30.0)
        good = legs.measure({"hind_l": self.leg(0.0, "l"), "hind_r": self.leg(0.0, "r")}, pel, 30.0)
        self.assertGreater(bad["legs"]["hind_l"]["bow_cm"], 10)
        self.assertTrue(any("bows" in v for v in legs.verdicts(bad, "Hop", False)))
        self.assertFalse(any("bows" in v for v in legs.verdicts(good, "Hop", False)))
        self.assertFalse(any("bows" in v for v in legs.verdicts(bad, "SitIdle", False)))  # posing, not moving
        self.assertFalse(any("bows" in v for v in legs.verdicts(bad, "Run_L_IP", False)))  # turning


class Reactions(unittest.TestCase):
    """The kangaroo's head, arms and tail: locked and floppy both fail."""

    N = 15

    def wave(self, amp, cycles=1, phase=0.0, mid=0.0):
        return [mid + amp * math.sin(2 * math.pi * (cycles * k / self.N) + phase) for k in range(self.N)]

    def test_turns_counts_a_clean_swing_as_two(self):
        self.assertEqual(reactions.turns(self.wave(5)), 2)
        self.assertEqual(reactions.turns(self.wave(5, cycles=2)), 4)  # wobbles
        self.assertEqual(reactions.turns(self.wave(0.3)), 0)  # noise

    def test_unwrap(self):
        self.assertEqual(reactions.unwrap([170, -175, -170]), [170, 185, 190])

    def test_steady_tucked_counterweight_passes(self):
        swing = self.wave(30)
        m = reactions.measure(
            {
                "head_world": self.wave(4),
                "head_rel": self.wave(6),
                "arm_l": self.wave(4),
                "arm_r": self.wave(4),
                "tail": [-x / 3 for x in swing],
                "legs": swing,
            },
            30,
        )
        self.assertEqual(reactions.verdicts(m), [])

    def test_floppy_locked_bobbing_and_wrong_way_tail_fail(self):
        swing = self.wave(30)
        m = reactions.measure(
            {
                "head_world": self.wave(30),
                "head_rel": self.wave(0.2),
                "arm_l": self.wave(20, cycles=2),
                "arm_r": self.wave(20),
                "tail": [x / 3 for x in swing],
                "legs": swing,
            },
            30,
        )
        v = " ".join(reactions.verdicts(m))
        for words in (
            "bobs",
            "the head moves only",
            "left arm changes direction",
            "right arm swings",
            "tail doesn't move against",
        ):
            self.assertIn(words, v)

    def test_strike_dead_stop_and_stutter(self):
        orig = [0, 0, 3.3, 6.1, 3.3, 8.9, 8.8, 0.0, 0.1, 0.8, 3.4]  # a tail kick with a dead stop
        new = [0, 0.9, 1.6, 1.3, 4.2, 2.4, 1.6, 3.1, 10.0, 3.9, 2.0, 0.5]  # the same kick reworked: no dead stop
        v = " ".join(reactions.strike_verdicts(orig))
        self.assertIn("stops dead", v)
        self.assertIn("stutters", v)
        self.assertEqual(reactions.strike_verdicts(new), [])

    def test_strike_foot_down_curled_and_folded_fail_footage_angle_passes(self):
        # side view in the shin's frame: x forward, z up, the ankle hinges about y
        def d(deg):
            a = math.radians(deg)
            return (math.cos(a), 0.0, math.sin(a))

        rest = (d(-115), d(0), d(0))  # standing: shin down and back, foot and toes flat forward
        shin = d(-31)  # a real kick on footage: shin 31 deg below level
        good_foot, good_toe = d(-10), d(-10)  # foot 21 deg up from the shin line, toes straight
        ankle, curl = reactions.foot_angles([shin] * 3, [good_foot] * 3, [good_toe] * 3, rest)
        self.assertAlmostEqual(ankle[0], 21, delta=0.5)
        self.assertAlmostEqual(curl[0], 0, delta=0.5)
        self.assertEqual(reactions.strike_foot_verdicts(ankle, curl, [0, 1, 2]), [])
        # a common fault: foot tipped down past the shin and toes curled 45 deg down
        ankle, curl = reactions.foot_angles([shin] * 3, [d(-45)] * 3, [d(-90)] * 3, rest)
        v = " ".join(reactions.strike_foot_verdicts(ankle, curl, [0, 1, 2]))
        self.assertIn("tips DOWN 14 deg", v)
        self.assertIn("curl down 45 deg", v)
        # the original's fault: the foot still folded up at the hit (the heel leads)
        ankle, curl = reactions.foot_angles([shin] * 3, [d(60)] * 3, [d(60)] * 3, rest)
        self.assertIn("folds up 91 deg", " ".join(reactions.strike_foot_verdicts(ankle, curl, [1])))
        self.assertEqual(reactions.strike_foot_verdicts(ankle, curl, []), [])  # no hit, nothing to judge

    def test_path_corners_catch_a_sharp_turn_at_speed_not_an_arc_or_a_slow_turn(self):
        fps = 30.0
        arc = [(1.2 * math.cos(k * 0.3), 0.0, 1.2 * math.sin(k * 0.3)) for k in range(12)]  # 11 m/s, 17 deg a frame
        self.assertEqual(reactions.path_corners(arc, fps), [])
        corner = [(0.4 * k, 0.0, 0.0) for k in range(5)] + [(1.6, 0.0, 0.4 * k) for k in range(1, 5)]  # 12 m/s, 90 deg
        self.assertEqual(reactions.path_corners(corner, fps), [4])
        self.assertIn("sharp corner", reactions.arc_verdicts([4], "the foot")[0])
        # a toe peeling off the ground: a sharp turn, but slow (3 m/s), as in a good hop or run
        peel = [(0.1 * k, 0.0, 0.0) for k in range(5)] + [(0.4, 0.0, 0.1 * k) for k in range(1, 5)]
        self.assertEqual(reactions.path_corners(peel, fps), [])

    def test_linear_spacing_caught_eased_motion_and_planted_feet_pass(self):
        fps = 30.0
        glide = [(0.03 * k, 0.0, 0.5) for k in range(12)]  # 0.9 m/s, one steady velocity for 12 frames
        self.assertEqual(reactions.linear_run(glide, fps)[0], 11)  # 11 steps between 12 frames
        self.assertIn(
            "one steady speed for 11 frames",
            reactions.linear_verdicts({"hand": reactions.linear_run(glide, fps)}, fps)[0],
        )
        eased = [(0.4 * (1 - math.cos(math.pi * k / 11)) / 2, 0.0, 0.5) for k in range(12)]  # slow, fast, slow
        self.assertLess(reactions.linear_run(eased, fps)[0], 0.25 * fps)
        self.assertEqual(reactions.linear_verdicts({"hand": reactions.linear_run(eased, fps)}, fps), [])
        planted = [(-0.03 * k, 0.0, 0.0) for k in range(12)]  # an in-place clip's planted foot: steady by design
        self.assertEqual(reactions.linear_run(planted, fps, [True] * 12), (0, 0))

    def test_block_bob_caught_and_overlapping_idle_passes(self):
        fps = 24.0
        hips = [0.01 * math.sin(2 * math.pi * k / 48) for k in range(48)]
        locked = {"head": [1.6 + z for z in hips], "hands": [1.0 + z for z in hips]}
        self.assertIn("one block", reactions.block_verdicts(hips, locked, fps)[0])
        ripple = {
            "head": [1.6 + 0.01 * math.sin(2 * math.pi * (k - 3) / 48) for k in range(48)],
            "hands": [1.0 + z for z in hips],
        }
        self.assertEqual(reactions.lag_frames(hips, ripple["head"], 6)[0], 3)
        self.assertEqual(reactions.block_verdicts(hips, ripple, fps), [])
        self.assertEqual(reactions.block_verdicts([0.0] * 48, locked, fps), [])  # no bob, nothing to judge

    def test_root_sway_caught_straight_root_and_curved_path_pass(self):
        steps = range(49)
        hips = [(0.03 * k, 0.03 * math.sin(math.pi * k / 12), 0.9) for k in steps]  # 6 cm sway, a step every 12 frames
        straight = [(0.03 * k, 0.0, 0.0) for k in steps]
        self.assertAlmostEqual(reactions.side_sway_cm(straight, straight[0], straight[-1]), 0.0, places=6)
        hips_cm = reactions.side_sway_cm(hips, straight[0], straight[-1])
        self.assertGreater(hips_cm, 3)
        self.assertEqual(reactions.root_sway_verdicts(0.0, hips_cm), [])
        copied = [(x, y, 0.0) for x, y, _ in hips]  # the root copies the hips' sway
        v = reactions.root_sway_verdicts(reactions.side_sway_cm(copied, straight[0], straight[-1]), hips_cm)
        self.assertIn("root bone sways", v[0])
        curve = [(3 * math.sin(k / 48), 3 * (1 - math.cos(k / 48)), 0.0) for k in steps]  # a gentle turn
        self.assertLess(reactions.side_sway_cm(curve, curve[0], curve[-1]), 1.0)

    def test_hang_time_real_arc_passes_steady_up_and_down_caught(self):
        fps, T = 30, 0.6
        n = int(T * fps) + 1
        arc = [1.0 + 4.9 * (k / fps) * (T - k / fps) for k in range(n)]  # a thrown body: a parabola
        triangle = [1.0 + 0.44 * (1 - abs(2 * k / (n - 1) - 1)) for k in range(n)]  # one speed up, one down
        low_land = [1.0 + 3.13 * (k / fps) - 4.905 * (k / fps) ** 2 for k in range(int(0.72 * fps) + 1)]
        self.assertGreaterEqual(reactions.hang_share(arc), 0.4)
        self.assertGreaterEqual(reactions.hang_share(low_land), reactions.HANG_MIN_SHARE)
        self.assertLess(reactions.hang_share(triangle), reactions.HANG_MIN_SHARE)
        self.assertEqual(reactions.hang_verdicts([reactions.hang_share(arc)]), [])
        self.assertIn("no hang time", reactions.hang_verdicts([reactions.hang_share(triangle)])[0])
        self.assertIsNone(reactions.hang_share([1.0, 1.01, 1.02, 1.01, 1.0, 1.0, 1.0, 1.0]))  # too small to judge

    def test_follow_through_dead_stop_caught_settling_strike_passes(self):
        fps = 30
        settles = [0.2, 0.5, 2.0, 6.0, 9.0, 7.0, 4.0, 2.5, 1.5, 0.8, 0.3, 0.1, 0.0, 0.0]
        stops = [0.2, 0.5, 2.0, 6.0, 9.0, 7.0, 0.6, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        cut = [0.2, 0.5, 2.0, 6.0, 9.0, 7.0, 4.0]  # the clip ends mid follow-through: nothing to judge
        body_still = [0.1, 0.2, 0.5, 1.0, 1.2, 0.8, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        body_moves = [0.1, 0.2, 0.5, 1.0, 1.2, 1.1, 0.9, 0.7, 0.5, 0.3, 0.1, 0.0, 0.0, 0.0]
        end = reactions.hit_end(stops)
        self.assertGreaterEqual(reactions.follow_through_s(settles, fps), reactions.FOLLOW_MIN_S)
        self.assertLess(reactions.follow_through_s(stops, fps), reactions.FOLLOW_MIN_S)
        self.assertIsNone(reactions.follow_through_s(cut, fps))
        still_s = reactions.follow_through_s(body_still, fps, end)
        moves_s = reactions.follow_through_s(body_moves, fps, end)
        self.assertEqual(reactions.follow_verdicts(reactions.follow_through_s(settles, fps), still_s), [])
        self.assertEqual(
            reactions.follow_verdicts(reactions.follow_through_s(stops, fps), moves_s), []
        )  # a held fist, body moves on
        self.assertIn(
            "follow-through", reactions.follow_verdicts(reactions.follow_through_s(stops, fps), still_s, "the hand")[0]
        )

    def test_enemy_attack_needs_time_to_react(self):
        fast = [0.0] * 10 + [0.5, 4.0, 8.0, 4.0, 0.5] + [0.0] * 10  # 30 fps: first move to hit in 1 frame
        slow = [0.0] * 5 + [0.9] * 12 + [4.0, 8.0, 4.0] + [0.0] * 8  # a 12-frame wind-up, then the hit
        self.assertLess(reactions.tell_s(fast, 30), 0.1)
        self.assertGreaterEqual(reactions.tell_s(slow, 30), 0.3)
        self.assertIn("ms from its first move to the hit", reactions.reaction_verdicts(reactions.tell_s(fast, 30))[0])
        self.assertEqual(reactions.reaction_verdicts(reactions.tell_s(slow, 30)), [])
        self.assertTrue(reactions.is_enemy("Kangaroo_Punch (enemy)"))
        self.assertTrue(reactions.is_enemy("NPC_Sword_Attack"))
        self.assertFalse(reactions.is_enemy("Sword_Attack"))

    def test_upper_strike_names(self):
        for n in ("Kangaroo_Punch", "Kangaroo_ClawSwipe", "Attack_Bite", "Kelpie_JumpAttack", "Bear_Maul"):
            self.assertTrue(reactions.is_upper_strike(n), n)
        for n in ("Kangaroo_HitBody", "Scratching", "Wolf_Death", "Hop_Loop", "Attack_Hurt"):
            self.assertFalse(reactions.is_upper_strike(n), n)

    def test_body_must_drive_the_strike(self):
        self.assertIn(
            "swings on its own", reactions.chain_verdicts([4, 4, 4, 1], "the claw")[0]
        )  # claw first, body after
        self.assertEqual(reactions.chain_verdicts([9, 9, 9, 9]), [])  # a lunge: the body brings the head (dog bites)
        self.assertEqual(reactions.chain_verdicts([3, 4, 5, 6]), [])  # body first, out to the tip
        self.assertEqual(reactions.chain_verdicts([5, 5, 4]), [])  # a frame early is within the slack

    def test_no_windup_and_windup_faster_than_strike(self):
        self.assertTrue(reactions.windup_verdicts({"reach_m": 1.0, "windup_m": 0.0, "anticipation_s": 0.03}))
        self.assertEqual(reactions.windup_verdicts({"reach_m": 1.0, "windup_m": 0.2, "anticipation_s": 0.03}), [])
        fps = 30
        # a claw lifted fast and high (12 m/s up), then a slower swipe down and forward (8 m/s)
        up = [(0.0, 0.0, 0.8 + 0.4 * k) for k in range(4)]
        down = [(0.0, -0.25 * k, 2.0 - 0.15 * k) for k in range(1, 7)]
        path = [(0.0, 0.0, 0.8)] * 3 + up + [(0.0, 0.0, 2.0)] * 2 + down + [down[-1]] * 3
        split = reactions.split_windup(path, fps)
        self.assertIsNotNone(split)
        self.assertGreater(split["windup_m_s"], split["strike_m_s"])
        self.assertIn("faster than the strike itself", reactions.windup_outruns_verdicts(split, "the claw")[0])
        # the same swipe after a slow lift: the strike is the fastest move, nothing to say
        slow_up = [(0.0, 0.0, 0.8 + 0.1 * k) for k in range(13)]
        self.assertEqual(
            reactions.windup_outruns_verdicts(reactions.split_windup([(0.0, 0.0, 0.8)] * 3 + slow_up + down, fps)), []
        )
        straight = [(0.0, 0.2 * k, 1.0) for k in range(10)]  # one push forward: no draw-back to split off
        self.assertIsNone(reactions.split_windup(straight, fps))

    def test_bite_opens_on_the_way_in(self):
        fps = 30
        opens = [0.0] * 5 + [6.0, 14.0, 20.0, 10.0, 2.0] + [0.0] * 10
        self.assertEqual(reactions.jaw_verdicts(opens, 7, fps), [])
        self.assertIn("stays shut", reactions.jaw_verdicts([1.0] * 20, 7, fps)[0])
        late = [0.0] * 14 + [10.0, 20.0, 5.0, 0.0]  # gapes 250 ms after the strike starts
        self.assertIn("too late to bite", reactions.jaw_verdicts(late, 7, fps)[0])
        again = [*opens[:12], 25.0, 30.0, 0.0]  # bites, then opens again later (a bark): fine
        self.assertEqual(reactions.jaw_verdicts(again, 7, fps), [])

    def test_lean_list_and_overlean_caught_turn_lean_allowed(self):
        fps = 30
        k = range(60)
        hips = [(0.0, 0.03 * i, 1.0) for i in k]
        left = [(-0.1, 0.03 * i, 1.0) for i in k]
        right = [(0.1, 0.03 * i, 1.0) for i in k]

        def neck(deg):
            return [(0.5 * math.sin(math.radians(deg)), 0.03 * i, 1.0 + 0.5 * math.cos(math.radians(deg))) for i in k]

        up = reactions.lean_measure(reactions.side_lean_deg(hips, neck(2), left, right))
        self.assertEqual(reactions.lean_verdicts(up, False), [])
        listing = reactions.lean_measure(reactions.side_lean_deg(hips, neck(12), left, right))
        self.assertAlmostEqual(listing["mean_deg"], 12, delta=0.5)
        self.assertIn("lists 12 degrees to the right", reactions.lean_verdicts(listing, False)[0])
        # a run round a 5 m circle at 5 m/s needs atan(25/5/9.81) = 27 degrees of lean into the turn
        r, v = 5.0, 5.0
        path = [(r * math.sin(v * i / fps / r), r * (1 - math.cos(v * i / fps / r)), 0.0) for i in k]
        need = reactions.turn_lean_deg(path, fps)
        self.assertAlmostEqual(need[30], -27, delta=2)  # the circle turns left
        self.assertEqual(reactions.lean_verdicts(reactions.lean_measure([-27.0] * 60, need), True), [])
        self.assertIn("leans", reactions.lean_verdicts(reactions.lean_measure([-50.0] * 60, need), True)[0])
