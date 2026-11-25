# Changelog

## 0.9.0 (unreleased)

First public version.

- Check clips: PASS, WARN or FAIL per clip for people and for animals (four legs, or a hopper with a tail). Checks skating, sinking and floating feet, backward and sideways joints, pops, loop seams, balance, runs that never leave the ground, walk cadence, wind-ups and follow-through on attacks, enemy attack tells, animal leg alignment and skin collapse.
- Fix current clip: re-plants sliding feet, closes the loop seam, smooths pops and moves or removes root motion, always on a copy. A fix that makes the clip worse is thrown away.
- Pose Adapt: pose a frame by hand and bake the change through a copy of the clip, keeping untouched feet planted.
- Reads rigs exported from Unity with a held root bone (a fixed turn and 100x scale above the hips) without changing the rig.
- Tells hoppers from walking two-legged animals by how the feet move.
- Shows progress per clip in the progress bar and status bar.
- Refuses clearly instead of guessing: rigs whose bones it can't name, clips with no keys on the rig, armatures with no bones.
- Check leaves the scene exactly as it was, including a pose you set but haven't keyed.
- Settings live on the scene as `scene.gaitkeeper`.
- Licensed GPL-3.0-or-later.
