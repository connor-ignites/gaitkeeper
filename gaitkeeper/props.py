# SPDX-License-Identifier: GPL-3.0-or-later
"""The panel's settings, stored on the scene as ``scene.gaitkeeper``."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty


class GaitKeeperSettings(bpy.types.PropertyGroup):
    """Options for checking, fixing and adapting clips, plus the last check's result."""

    body: EnumProperty(  # type: ignore[valid-type]
        name="Body",
        items=[
            ("AUTO", "Auto", "Tell people from animals by the skeleton"),
            ("HUMAN", "Person", "Two legs, two arms"),
            ("CREATURE", "Animal", "Four legs, or a hopper with a tail"),
        ],
    )
    hopper: EnumProperty(  # type: ignore[valid-type]
        name="Hopper",
        items=[
            ("AUTO", "Auto", "Two legs and a tail hop"),
            ("YES", "Yes", "Judge as a hopper (kangaroo)"),
            ("NO", "No", "Not a hopper"),
        ],
    )
    every_clip_strikes: BoolProperty(  # type: ignore[valid-type]
        name="Every clip is a leg strike",
        description="Check every clip as a kick, even if its name doesn't say so",
    )
    current_only: BoolProperty(name="Current clip only")  # type: ignore[valid-type]
    attacks_for: EnumProperty(  # type: ignore[valid-type]
        name="Attacks are for",
        items=[
            (
                "PLAYER",
                "Player",
                "Attacks can be as fast as you like (clips named enemy, npc or boss are still checked as an enemy's)",
            ),
            (
                "ENEMY",
                "Enemies",
                "Every attack must give the player about 300 ms from its first move to the hit, time to react",
            ),
        ],
    )
    root_motion: EnumProperty(  # type: ignore[valid-type]
        name="Root motion",
        items=[
            ("LEAVE", "Leave as is", "Don't change how the clip travels"),
            ("EXTRACT", "Move onto root", "The body's travel moves onto the root bone (the game moves the character)"),
            ("IN_PLACE", "Walk on the spot", "Remove the travel so the clip plays in place"),
        ],
    )
    adapt_mode: EnumProperty(  # type: ignore[valid-type]
        name="Spread",
        items=[
            ("WHOLE", "Whole clip", "Posture and stance: the same change on every frame"),
            ("STEPS", "Every matching step", "The same moment of every step, mirrored on the other foot's step"),
            ("HERE", "Just here", "Only around this frame, fading in and out"),
        ],
    )
    adapt_fade: IntProperty(  # type: ignore[valid-type]
        name="Fade (frames)",
        default=6,
        min=1,
        max=120,
        description="How many frames the change takes to fade in and out",
    )
    adapt_mirror: BoolProperty(  # type: ignore[valid-type]
        name="Mirror to the other side",
        default=True,
        description="Give the other arm or leg the same change, mirrored",
    )
    adapt_feet: BoolProperty(  # type: ignore[valid-type]
        name="Keep feet planted",
        default=True,
        description="Feet you didn't touch stay where they were; touched feet don't skate",
    )
    adapt_kept: StringProperty(options={"HIDDEN"})  # type: ignore[valid-type]  # JSON: poses kept for Adapt
    result: StringProperty(options={"HIDDEN"})  # type: ignore[valid-type]  # JSON: the last check, for the panel


def register() -> None:
    bpy.utils.register_class(GaitKeeperSettings)
    bpy.types.Scene.gaitkeeper = bpy.props.PointerProperty(type=GaitKeeperSettings)


def unregister() -> None:
    del bpy.types.Scene.gaitkeeper
    bpy.utils.unregister_class(GaitKeeperSettings)
