# GaitKeeper

[![CI](https://github.com/connor-ignites/gaitkeeper/actions/workflows/ci.yml/badge.svg)](https://github.com/connor-ignites/gaitkeeper/actions/workflows/ci.yml)
[![Licence: GPL-3.0-or-later](https://img.shields.io/badge/licence-GPL--3.0--or--later-blue)](LICENSE)
[![Blender 4.2+](https://img.shields.io/badge/Blender-4.2%2B-orange?logo=blender&logoColor=white)](https://www.blender.org/download/)

A free Blender add-on that checks your animation clips for the faults players notice: feet that slide or sink, knees that bend the wrong way, loops that hitch, one-frame pops. Each clip gets PASS, WARN or FAIL with a plain-English reason.

**Beta.** Check only reads your clips. Fix and Pose Adapt write a new copy of a clip and never change the original, and both can be undone. Still, save your work (or use version control) before trying any new tool on a project you care about.

![A walk with pops and sliding feet, before and after GaitKeeper's fix](docs/media/hero-walk-pops-and-skating.gif)

*A clean walk with faults added on purpose (top), and the same clip after Fix (bottom). Test clip: Quaternius Universal Animation Library, CC0.*

## What it checks

It works on people (two legs, two arms, any common bone naming) and on animals (four legs, or a hopper with a tail).

| Check | What it means |
| --- | --- |
| Skating | A foot that should be planted slides along the floor. |
| Sinking and floating | A planted foot goes through the floor, or hovers above it. |
| Backward and sideways joints | A knee or elbow bends past what a body can do, or off its hinge. |
| Pops | A bone snaps to a new angle in one frame instead of turning over a few. |
| Loop seam | The last frame of a loop doesn't meet the first, so it hitches every cycle. |
| Balance | The body's weight sits outside the feet while it stands still. |
| Runs that never leave the ground | A run or sprint with no moment where both feet are off the floor. |
| Walk speed and cadence | Steps per minute far outside what a walk looks like. |
| Attacks with no wind-up | A punch, kick or bite that starts at full speed with no coil, or stops dead at the hit. |
| Enemy tells | With "Attacks are for: Enemies", every attack must give the player about 300 ms to react. |
| Animal legs | Legs that bow out sideways, feet set too wide in the rest pose, hops that hang wrong. |
| Skin | Mesh that collapses or stretches badly when a joint bends (people, when a skinned mesh is found). |

Checking changes nothing in your scene. The clip and frame you were on are put back afterwards.

## Install

1. Download `gaitkeeper-0.9.0.zip` from the [Releases](https://github.com/connor-ignites/gaitkeeper/releases) page.
2. In Blender 4.2 or newer: **Edit > Preferences > Get Extensions**, open the arrow menu at the top right, choose **Install from Disk**, and pick the zip. (Dragging the zip onto Blender works too.)

## A first check, in about a minute

1. Select an armature that has some clips (actions) on it.
2. In the 3D View press **N** to open the sidebar and click the **GaitKeeper** tab.
3. Press **Check clips**.

The panel lists every clip, worst first. Click a clip's name to play it. The full report goes to the Text Editor as "GaitKeeper report". Here is part of one for the free Quaternius UAL 2 pack:

```text
GaitKeeper: Armature (checked as: person)
42 clips: 16 pass, 26 warn, 0 fail

WARN  Farm_PlantSeed
      - r foot slides 0.25 m/s while planted (skating).
      - off balance: the body's weight sits 20 cm outside the feet while it stands, so it would tip over. Move the hips back over the feet.
WARN  Hit_Knockback
      - sudden jumps between two frames (pops) in: thigh_l (frame 5). A bone snaps to a new angle instead of turning over a few frames; smooth the keys there.
```

Treat a WARN as a place to look. Some are deliberate: a knockback is meant to be violent. FAIL is kept for things a body can't do.

## Fixing a clip

**Fix current clip** makes a copy called `<clip>_fixed` and leaves the original alone. On people it re-plants sliding feet (moving them 8 cm at most), closes the loop seam, smooths pops, and can move the body's travel onto the root bone or remove it ("Walk on the spot"). On animals it brings legs that bow out sideways back into line. The copy is checked again, and if the fix made anything worse it is thrown away.

![A crouch walk whose left foot skates, before and after Fix](docs/media/crouch-walk-foot-slide.gif)

![A punch where the forearm and hand snap in one frame, before and after](docs/media/punch-pop.gif)

![A kangaroo hop with one hind knee bowed out, before and after Fix](docs/media/kangaroo-leg-bow.gif)

*Animals: a kangaroo landing with one hind knee bowed 25 degrees out on purpose. Check measured the knee 18 cm off the hip-to-foot line; after Fix it is 1.2 cm. The kangaroo model was made with Meshy (AI) and rigged by hand.*

## Pose Adapt

Pose some bones on one frame (without keying them) and press **Adapt clip to this pose**. The change is baked into a copy, spread over the whole clip, over the same moment of every step (mirrored on the other foot), or only around that frame. Feet you didn't touch stay planted. To change several frames, pose one and press **Keep this pose**, then the next, then Adapt.

## Settings

| Setting | What it does |
| --- | --- |
| Body | Auto tells people from animals by the skeleton. Set it by hand if it guesses wrong. |
| Hopper | For two-legged animals with a tail, such as a kangaroo. |
| Every clip is a leg strike | Judge every clip as a kick, whatever its name. |
| Attacks are for | Player attacks can be as fast as you like; enemy attacks must be readable. |
| Current clip only | Check just the clip that is playing. |
| Root motion | What Fix does with the body's travel. |

## Rigs it has been run on

Before this release, Check ran on every clip of each rig below, and Fix on up to three flagged clips per rig. Nothing crashed, and no original clip changed.

| Rig | Clips | Read as | Result |
| --- | --- | --- | --- |
| Quaternius UAL 1 (CC0) | 119 | person | 63 pass, 50 warn, 6 fail |
| Quaternius UAL 2 (CC0) | 42 | person | 16 pass, 26 warn, 0 fail |
| Quaternius UAL 2, root-motion version | 42 | person | 19 pass, 23 warn, 0 fail |
| A commercial Border Collie pack | 112 | animal | 110 pass, 2 warn, 0 fail |
| A hand-rigged kangaroo | 4 | hopper | 4 warn |
| A code-built emu (two legs and a tail, walks) | 11 | animal | 10 pass, 1 warn |
| A huntsman spider (eight legs) | 7 | animal | 5 pass, 2 warn |
| A commercial humanoid pack exported from Unity, with a held root bone (2 clips sampled) | 2 | person | 2 warn |

The tests also run on small rigs built in code, including the odd cases: empty and one-frame clips, NLA-only animation, shape-key clips, scaled and rotated rigs, Japanese bone names, linked rigs with a library override, and an armature with no bones.

Clip names matter. GaitKeeper reads words like `walk`, `run`, `loop`, `punch` and `kick` in a clip's name to decide which checks apply, so `Run_Loop` is judged as a looping run and `Attack_02` as an attack.

## Known limits

- It finds bones by name (Mixamo-style, Unreal-style, `.L`/`.R` and similar). An unusual naming scheme may need the Body setting set by hand, and a rig with a bone named "tail" is treated as an animal on Auto.
- On Auto, a two-legged animal with a tail counts as a hopper only when its feet move together in its walk, run or hop clips. A rig with no clips named like that falls back to the skeleton and may need the Hopper setting.
- Check clips takes every action in the file that keys this armature's bones. Two characters with the same bone names in one file will pick up each other's clips; tick **Current clip only** there.
- Feet are judged against a flat floor. A clip authored on a slope or on stairs will read as sinking or floating.
- Each clip is played frame by frame through Blender, so a heavy scene with high-poly meshes is slow to check. On a light rig, Check and Fix together take about 11 seconds for a 1000-frame clip; the progress bar and status bar show which clip it's on.
- Fix refuses rather than guesses: on a rig whose bones it can't name, on a clip with no keys on the rig, or when its result checks worse than the original. A refusal leaves nothing behind.
- The thresholds come from motion-capture data and real footage of people, dogs and kangaroos. They suit realistic and semi-realistic motion. Cartoon timing and squash will get more WARNs, because exaggerated motion breaks the same rules a broken clip does.
- Fix handles feet, seams, pops and root motion. It won't repair a bad pose or bad timing; it tells you where they are.

## Building and testing

```sh
python -m pip install ruff pytest
ruff check . && ruff format --check .
BLENDER=/path/to/blender pytest     # without BLENDER (or blender on PATH) only the maths tests run
python scripts/build.py             # builds and validates dist/gaitkeeper-<version>.zip
```

The Blender tests build the zip, install it into a temporary Blender profile (yours isn't touched) and run on rigs built in code: install and smoke test, the safety checks, the odd cases above, held-root and hopper rigs, progress reporting, and a pinned Pose Adapt result. CI runs all of them on Blender 4.2 LTS and 5.2 LTS.

## Contributing

Bug reports with the rig attached help the most. See [CONTRIBUTING.md](CONTRIBUTING.md) for the setup, how the code is laid out and the rules for changes.

## Licence

GPL-3.0-or-later, like Blender. See [LICENSE](LICENSE). As the licence says, GaitKeeper comes with no warranty: it is provided "as is", and you use it at your own risk.

The humanoid demo clips use the Quaternius Universal Animation Library, which is CC0. No model or animation files are included in this repository.
