# SPDX-License-Identifier: GPL-3.0-or-later
"""Clip and bone names read by whole words (core.names), and the shared loop rule (core.cycle)."""

import unittest

from conftest import axis_q
from core import cycle, names

STILL = (1.0, 0.0, 0.0, 0.0)


class Names(unittest.TestCase):
    def test_a_word_hidden_inside_another_word_is_not_read(self):
        # "die" in Soldier, "roll" in Troll, "fall" in Waterfall, "sit" in transition, "lean" in clean
        for walk in ("Soldier_Walk", "Troll_Run", "Waterfall_Walk", "Walk_Transition", "Clean_Run"):
            with self.subTest(walk):
                self.assertFalse(names.not_standing(walk))
                self.assertFalse(names.meant_off_ground(walk))

    def test_the_words_themselves_are_read(self):
        for clip in ("Sit_Idle", "Death_01", "Fall_Loop", "LeanOnWall", "Rolling", "lie_down", "Climb.Ladder"):
            with self.subTest(clip):
                self.assertTrue(names.not_standing(clip))
        for clip in ("Swim_Fast", "DieForward", "FallingLoop", "Ragdoll"):
            with self.subTest(clip):
                self.assertTrue(names.meant_off_ground(clip))

    def test_bone_names_split_at_separators_camel_case_and_sides(self):
        self.assertEqual(names.words_of("RearFoot.R"), ["rear", "foot", "r"])
        self.assertEqual(names.words_of("IKLeg_L"), ["ik", "leg", "l"])
        self.assertFalse(names.has_word("RearLeg_L", ("ear",)))
        self.assertFalse(names.has_word("Spike", ("ik",)))
        self.assertTrue(names.has_word("foot_ik.L", ("ik",)))
        self.assertTrue(names.has_word("Ear.L", ("ear",)))

    def test_loop_by_name(self):
        self.assertTrue(names.says_loop("Walk_Loop"))
        self.assertTrue(names.says_loop("IdleLoop2"))
        self.assertFalse(names.says_loop("Walk"))

    def test_strike_and_enemy_words_hidden_inside_other_words_are_not_read(self):
        # "die" in Soldier and "hit" in White used to stop a punch being judged; "mob" in Mobile made an enemy
        for strike in ("Soldier_Punch", "White_Bear_Maul", "Wolf_Bite"):
            with self.subTest(strike):
                self.assertTrue(names.is_upper_strike(strike))
        for clip in ("Mobile_Idle", "Bossa_Dance", "Phoenix_Fly"):
            with self.subTest(clip):
                self.assertFalse(names.is_enemy(clip))
        for clip in ("Mob_Attack", "Enemies_Charge", "Bosses_Slam"):
            with self.subTest(clip):
                self.assertTrue(names.is_enemy(clip))
        self.assertFalse(names.says_hops("Brunch_Idle"))
        self.assertTrue(names.says_hops("Hopping_Loop"))

    def test_bone_words_hidden_inside_other_words_are_not_read(self):
        # "ring" in Spring skipped its pops; "hand" in Handle and "paw" in Spawn made arms of props
        for bone in ("Spring", "String_01", "Middleware", "Pinkyring"):
            with self.subTest(bone):
                self.assertFalse(names.small_bone(bone))
        for bone in ("LeftHandRing1", "ring_01_l", "Thumb.L", "LeftToe_End", "Fingers"):
            with self.subTest(bone):
                self.assertTrue(names.small_bone(bone))
        for bone in ("Handle", "Spawn_Point", "Clawhammer", "Wristband"):
            with self.subTest(bone):
                self.assertFalse(names.hand_bone(bone))
        for bone in ("Hand_L", "mixamorig:LeftHand", "FrontPaw.R", "Claws", "wrist.L"):
            with self.subTest(bone):
                self.assertTrue(names.hand_bone(bone))
        self.assertTrue(names.hand_bone("Hand_L", first=True))
        self.assertFalse(names.hand_bone("LeftHandIndex1", first=True))
        self.assertTrue(names.shoulder_top("Clavicle_L") and names.shoulder_top("ShoulderBlade.R"))
        self.assertFalse(names.shoulder_top("Overshoulder"))

    def test_a_word_looked_for_may_be_several_words_in_a_row(self):
        self.assertTrue(names.has_word("LeftToe_End", ("toe_end",)))
        self.assertFalse(names.has_word("Toe_Tip_End", ("toe_end",)))


class LoopRule(unittest.TestCase):
    def test_a_clip_ending_in_its_first_pose_loops_whatever_its_name(self):
        first = {"thigh": axis_q((1, 0, 0), 20), "calf": STILL}
        last = {"thigh": axis_q((1, 0, 0), 22), "calf": STILL}
        self.assertTrue(cycle.loops("Walk", first, last, 25))
        self.assertTrue(cycle.loops("Deer_Idle", first, first, 25))

    def test_a_clip_ending_in_another_pose_loops_only_if_its_name_says_so(self):
        first = {"thigh": STILL}
        last = {"thigh": axis_q((1, 0, 0), 30)}
        self.assertFalse(cycle.loops("Walk_Start", first, last, 25))
        self.assertFalse(cycle.loops("Run", first, last, 25))
        self.assertTrue(cycle.loops("Run_Loop", first, last, 25))
        self.assertAlmostEqual(cycle.seam_deg(first, last), 30.0, places=4)

    def test_too_short_to_tell_by_poses(self):
        self.assertFalse(cycle.loops("Pose_Hold", {"hips": STILL}, {"hips": STILL}, 1))
        self.assertTrue(cycle.loops("Hold_Loop", {"hips": STILL}, {"hips": STILL}, 1))


if __name__ == "__main__":
    unittest.main()
