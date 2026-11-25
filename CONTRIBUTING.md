# Contributing to GaitKeeper

Bug reports, rigs that read wrong, and pull requests are all welcome.

## Reporting a problem

Use the bug report form on the Issues page. The most useful things to include are the rig (or where it comes from), the clip name, and the "GaitKeeper report" text from Blender's Text Editor. If GaitKeeper calls a clip broken and it looks fine to you, say what you see on screen: that is how the thresholds get better.

## Setting up

You need Python 3.11 or newer, and Blender 4.2 or newer for the Blender tests.

```sh
git clone https://github.com/connor-ignites/gaitkeeper
cd gaitkeeper
python -m pip install ruff pytest
pytest                                    # maths tests; Blender tests skip without Blender
BLENDER=/path/to/blender pytest           # everything, including install, Check, Fix and safety tests
python scripts/build.py                   # builds dist/gaitkeeper-<version>.zip
```

The Blender tests install the extension into a temporary profile, so your own Blender setup is never touched. The Undo test needs a window, so it only runs with `GAITKEEPER_WINDOW_TESTS=1` (a Blender window opens briefly).

## How the code is laid out

- `gaitkeeper/` is the extension. `operators.py`, `adapt_ops.py` and `panel.py` are the Blender UI; `runner.py` decides whether a rig is a person or an animal, runs the checks and puts the scene back afterwards.
- `gaitkeeper/core/` holds the checks. `motion_math.py`, `body_rules.py`, `body.py`, `reactions.py`, `legs.py`, `adapt_math.py` and `report.py` are plain Python and are tested without Blender. The rest read and write Blender data and receive the scene as a parameter; nothing in `core/` reads `bpy.context`.
- `tests/blender/` holds scripts that run inside Blender. They build their rigs in code, so no model files are needed.

## Rules for changes

- Keep `ruff check`, `ruff format --check` and `pytest` green.
- Add a test with every change: a unit test for the maths, a Blender test for anything that touches the scene.
- Check must never change the scene, and Fix and Pose Adapt must only ever add a new action. `tests/blender/safety.py` checks both; don't weaken it.
- Messages a user reads stay in plain English, with no maths jargon. `tests/test_messages.py` checks them.
- If a change is meant to alter Pose Adapt's output, re-pin it: run `tests/blender/adapt_pin.py` in Blender and write `tests/blender/adapt_golden.json`, and say why in the pull request.
- Never commit model, animation or texture files from paid packs or anything you aren't allowed to share.

By contributing you agree that your work is released under the project's licence, GPL-3.0-or-later.
