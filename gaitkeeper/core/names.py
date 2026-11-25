# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper: reading clip and bone names by whole words. No Blender needed.

A name is split into words first ("Soldier_Walk" -> soldier, walk; "RearLeg_L" -> rear, leg, l). has_word
matches a word that starts with one of the words looked for ("Running" counts for "run"); has_whole_word
only the word itself or its plural, for short words that start longer ones ("mob" in Mobile, "hand" in
Handle). A plain substring test would read "die" in Soldier, "roll" in Troll, "fall" in Waterfall, "sit" in
transition, "ear" in RearLeg, "ik" in Spike, "ring" in Spring and "paw" in Spawn. A word looked for may be
several words ("toe_end"): they must come one after another in the name.
"""

from __future__ import annotations

import re
from collections.abc import Callable

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
SMALL_BONES = ("leaf", "index", "middle", "ring", "pinky", "thumb", "finger", "toe_end", "twist")  # pops not judged
ENEMY_WORDS = ("enemy", "enemies", "npc", "boss", "mob", "foe")
UPPER_STRIKE = ("punch", "jab", "swipe", "claw", "slash", "maul", "box", "bite", "attack", "headbutt", "snap")
NOT_A_STRIKE = ("hit", "scratch", "react", "death", "die", "dead", "hurt", "stagger")
HAND_WORDS = ("hand", "paw", "claw", "wrist")
SHOULDER_TOPS = ("clavicle", "shoulder", "scapula", "collar")
HOP_WORDS = ("hop", "run", "bound")


def words_of(name: str) -> list[str]:
    """A name to lower-case words, split at separators, digits and camelCase:
    "Bad_SpineWrung-Loop2" -> bad, spine, wrung, loop; "RearFoot.R" -> rear, foot, r."""
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)]


def _found(name: str, words: tuple[str, ...], same: Callable[[str, str], bool]) -> bool:
    """One of `words` (each split into words itself) runs through the name's words, `same` for each pair."""
    ts = words_of(name)
    for w in map(words_of, words):
        if any(all(same(t, x) for t, x in zip(ts[i:], w)) for i in range(len(ts) - len(w) + 1)):
            return True
    return False


def has_word(name: str, words: tuple[str, ...]) -> bool:
    """A word of the name starts with one of `words` (so "Running" counts for "run", "Wrung" doesn't)."""
    return _found(name, words, str.startswith)


def _same_or_plural(t: str, w: str) -> bool:
    return t in (w, w + "s", w + "es")


def has_whole_word(name: str, words: tuple[str, ...]) -> bool:
    """A word of the name is one of `words` or its plural ("Paws" counts for "paw"; "Spawn", "Handle" and
    "Mobile" don't count for "paw", "hand" or "mob")."""
    return _found(name, words, _same_or_plural)


def not_standing(name: str) -> bool:
    """The clip's name says the body isn't standing on its own feet (sitting, lying, climbing, pushing...)."""
    return has_word(name, NOT_STANDING)


def meant_off_ground(name: str) -> bool:
    """The clip's name says the feet aren't meant to stay planted (swimming, rolling, dying, falling...)."""
    return has_word(name, OFF_GROUND)


def says_loop(name: str) -> bool:
    """The clip's name says it loops ("Walk_Loop", "IdleLoop")."""
    return has_word(name, LOOP_WORDS)


def is_enemy(name: str) -> bool:
    """The clip's name says it's for an enemy ("Mob_Attack", not "Mobile_Idle")."""
    return has_whole_word(name, ENEMY_WORDS)


def is_upper_strike(name: str) -> bool:
    """The clip's name says it's a strike with the arms, claws or jaws, not a hit reaction or a scratch
    ("Soldier_Punch" is one: the "die" inside Soldier doesn't count)."""
    return has_word(name, UPPER_STRIKE) and not has_word(name, NOT_A_STRIKE)


def says_hops(name: str) -> bool:
    """The clip's name says it hops, runs or bounds ("Hopping", not "Brunch")."""
    return has_word(name, HOP_WORDS)


def small_bone(name: str) -> bool:
    """A finger, toe tip, leaf or twist bone: too small to judge for pops ("Spring" and "String" aren't)."""
    return has_whole_word(name, SMALL_BONES)


def hand_bone(name: str, first: bool = False) -> bool:
    """A hand, paw, claw or wrist bone ("Handle" and "Spawn" aren't). first: only the name's first word
    counts ("Hand_L", not "LeftHandIndex1")."""
    if first:
        name = next(iter(words_of(name)), "")
    return has_whole_word(name, HAND_WORDS)


def shoulder_top(name: str) -> bool:
    """A collarbone or shoulder blade, at the top of a front leg ("Clavicle_L", "ShoulderBlade")."""
    return has_word(name, SHOULDER_TOPS)
