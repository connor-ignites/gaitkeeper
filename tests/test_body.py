# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-clip body verdicts (core.body)."""

import unittest

from core import body


class BodyVerdicts(unittest.TestCase):
    def test_clip_name_words(self):
        self.assertEqual(body.words_of("Bad_SpineWrung-Loop2"), ["bad", "spine", "wrung", "loop"])
        self.assertTrue(body.has_word("Running_Fast", body.RUNNING))
        self.assertFalse(body.has_word("SpineWrung", body.RUNNING))

    def test_a_clip_named_root_scene_is_judged_by_its_file_name(self):
        # Blender exports name every clip "root|Scene": the file's name says what the move is
        name = body.judged_name("root|Scene", r"E:\clips\build9\Hero_Punch.fbx")
        self.assertEqual(name, "Hero_Punch root|Scene")
        self.assertTrue(body.has_word(name, body.ATTACK))
        self.assertTrue(body.has_word(body.judged_name("Take 001", "C:/x/Kick_Fast.glb"), body.ATTACK))
        # before the "|" is the rig's name, not the move's
        self.assertEqual(body.judged_name("SK_Mannequin|Scene", "Hero_Punch.fbx"), "Hero_Punch SK_Mannequin|Scene")
        self.assertEqual(body.judged_name("Armature|Idle", "Hero_Punch.fbx"), "Armature|Idle")
        self.assertEqual(body.judged_name("Punch_Jab", "Walk.fbx"), "Punch_Jab")  # a clip's own name wins
        self.assertEqual(body.judged_name("root|Scene", "Armature.001"), "root|Scene")  # nothing better to read
        self.assertEqual(body.judged_name("root|Scene", ""), "root|Scene")

    def test_impossible_joints_fail_and_style_warns(self):
        b = {
            "knee_l": {
                "max_bend_deg": 40,
                "backward_frames": [3, 4],
                "worst_backward_deg": 30,
                "worst_sideways_deg": 0.0,
            },
            "neck": {"bend_deg": 10, "twist_deg": 120},
            "longest_airborne": 4,
        }
        v = body.body_verdicts(b, None, "Idle_Loop", False, 30.0)
        self.assertTrue(any(x.startswith("FAIL left knee bends backwards") for x in v), v)
        self.assertTrue(any(x.startswith("FAIL head turns 120") for x in v), v)
        self.assertTrue(any(x.startswith("WARN both feet leave the ground") for x in v), v)
        jump = body.body_verdicts(b, None, "Jump_Start", False, 30.0)
        self.assertFalse(any("both feet leave" in x for x in jump), jump)  # a jump may leave the ground

    def test_readings_no_body_could_make(self):
        """A joint past anything a body can do keeps its FAIL (a mirrored knee is a real fault) with a note to rule
        out the tool; the same reading in most clips of a file is a rig-level TOOL?."""

        def clip(back_deg: float) -> dict:
            return {
                "knee_l": {
                    "max_bend_deg": 40,
                    "backward_frames": list(range(20)),
                    "worst_backward_deg": back_deg,
                    "worst_sideways_deg": 0.0,
                }
            }

        real = body.body_verdicts(clip(30), None, "Walk_Loop", False, 30.0)  # broken, but a body could
        mad = body.body_verdicts(clip(73), None, "Walk_Loop", False, 30.0)  # the Starter Assets misread
        self.assertTrue(real[0].startswith("FAIL left knee bends backwards (30"), real)
        self.assertNotIn("Measure the joint on the bones", real[0])
        self.assertTrue(mad[0].startswith("FAIL left knee bends backwards (73"), mad)
        self.assertIn("Measure the joint on the bones", mad[0])
        one_bad = {"Walk": mad, "Run": [], "Idle": [], "Jump": []}  # one broken clip: its own fault
        self.assertEqual(body.misread_verdicts(one_bad), [])
        pack = {
            n: body.body_verdicts(clip(d), None, n, False, 30.0)
            for n, d in (("Walk", 73), ("Run", 88), ("Idle", 70), ("Jump", 10))
        }
        tool = body.misread_verdicts(pack)
        self.assertEqual(len(tool), 1, tool)
        self.assertTrue(tool[0].startswith("TOOL? 3 of 4 clips read 'left knee bends backwards'"), tool)
        self.assertEqual(body.misread_verdicts({"Walk": mad, "Run": mad}), [])  # two clips: too few to say

    def test_a_persons_windup_faster_than_the_punch_warns(self):
        """People get the animals' wind-up split: a hand that draws back faster than it punches."""
        from types import SimpleNamespace

        def punch(back_step: float, hit_step: float) -> list[str]:
            back = round(0.6 / back_step)
            xs = (
                [0.0] * 4
                + [-back_step * i for i in range(1, back + 1)]
                + [-0.6] * 4
                + [-0.6 + hit_step * i for i in range(1, round(1.26 / hit_step) + 1)]
                + [0.66] * 6
            )
            world = [{"hips": (0.0, 0.0, 1.0), "tip:hand_r": (x, 0.3, 1.4)} for x in xs]
            s = SimpleNamespace(world=world, world_q=[{} for _ in world], rest_q={}, rest_axis={})
            b = body.measure_body(s, 30.0, {}, {}, {}, "Punch_Haymaker", False, False, False)
            return [v for v in body.body_verdicts(b, None, "Punch_Haymaker", False, 30.0) if "wind-up (" in v]

        fast = punch(0.12, 0.09)  # draws back at 3.6 m/s, punches at 2.7
        self.assertEqual(len(fast), 1, fast)
        self.assertIn("the right hand's strike: the wind-up (3.6 m/s) is faster than the strike itself", fast[0])
        self.assertEqual(punch(0.04, 0.21), [])  # a slow coil, then a fast punch: as it should be

    def test_after_an_edit_only_new_or_worse_problems_show(self):
        before = {"neck": {"bend_deg": 10, "twist_deg": 100}}
        same = {"neck": {"bend_deg": 10, "twist_deg": 101}}
        worse = {"neck": {"bend_deg": 10, "twist_deg": 130}}
        self.assertEqual(body.body_verdicts(before, same, "Idle", False, 30.0), [])
        self.assertEqual(len(body.body_verdicts(before, worse, "Idle", False, 30.0)), 1)


CONTROLLER = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!91 &9100000
AnimatorController:
  m_Name: Test
  m_AnimatorLayers:
  - serializedVersion: 5
    m_Name: Base Layer
    m_StateMachine: {fileID: 11}
    m_Mask: {fileID: 0}
    m_DefaultWeight: 1
--- !u!1107 &11
AnimatorStateMachine:
  m_ChildStates:
  - serializedVersion: 1
    m_State: {fileID: 21}
  - serializedVersion: 1
    m_State: {fileID: 22}
  m_ChildStateMachines: []
  m_AnyStateTransitions: []
  m_DefaultState: {fileID: 21}
--- !u!1102 &21
AnimatorState:
  m_Name: Idle
  m_Speed: 1
  m_Transitions:
  - {fileID: 31}
  m_Motion: {fileID: 0}
--- !u!1102 &22
AnimatorState:
  m_Name: Run
  m_Speed: 1.5
  m_Transitions: []
  m_Motion: {fileID: 0}
--- !u!1101 &31
AnimatorStateTransition:
  m_Conditions:
  - m_ConditionMode: 3
    m_ConditionEvent: Speed
    m_EventTreshold: 0.1
  m_DstState: {fileID: 22}
  m_TransitionDuration: 0.25
  m_TransitionOffset: 0.1
  m_ExitTime: 0.9
  m_HasExitTime: 0
  m_HasFixedDuration: 1
"""
