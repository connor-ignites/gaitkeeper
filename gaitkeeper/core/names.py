# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: reading clip and bone names by whole words. No Blender needed.

A name is split into words first ("Soldier_Walk" -> soldier, walk; "RearLeg_L" -> rear, leg, l), and a
word matches when it starts with one of the words looked for ("Running" counts for "run"). A plain
substring test would read "die" in Soldier, "roll" in Troll, "fall" in Waterfall, "sit" in transition,
"ear" in RearLeg and "ik" in Spike.
"""

from __future__ import annotations

import re

NOT_STANDING = (
    "sit",
    "driv",
    "swim",
    "lying",
    "lie",
    "death",
    "die",
    "roll",
    "kneel",
    "fall",
    "ragdoll",
    "push",
    "pull",
    "lean",
    "climb",
    "hang",
)  # pushing or leaning: the object takes weight
OFF_GROUND = ("swim", "roll", "death", "die", "fall", "ragdoll", "climb")  # feet aren't meant to stay planted
LOOP_WORDS = ("loop",)


def words_of(name: str) -> list[str]:
    """A name to lower-case words, split at separators, digits and camelCase:
    "Bad_SpineWrung-Loop2" -> bad, spine, wrung, loop; "RearFoot.R" -> rear, foot, r."""
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)]


def has_word(name: str, words: tuple[str, ...]) -> bool:
    """A word of the name starts with one of `words` (so "Running" counts for "run", "Wrung" doesn't)."""
    return any(t.startswith(w) for t in words_of(name) for w in words)


def not_standing(name: str) -> bool:
    """The clip's name says the body isn't standing on its own feet (sitting, lying, climbing, pushing...)."""
    return has_word(name, NOT_STANDING)


def meant_off_ground(name: str) -> bool:
    """The clip's name says the feet aren't meant to stay planted (swimming, rolling, dying, falling...)."""
    return has_word(name, OFF_GROUND)


def says_loop(name: str) -> bool:
    """The clip's name says it loops ("Walk_Loop", "IdleLoop")."""
    return has_word(name, LOOP_WORDS)
