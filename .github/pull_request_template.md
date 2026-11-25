## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## How it was tested

- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `pytest` passes (with `BLENDER` set if the change touches anything that runs in Blender)
- [ ] A test covers the change (maths in `tests/`, Blender behaviour in `tests/blender/`)
- [ ] New or changed messages are in plain English (`tests/test_messages.py`)

## Safety

- [ ] Check still changes nothing in the scene, and Fix still only adds a copy (`tests/blender/safety.py` passes)
