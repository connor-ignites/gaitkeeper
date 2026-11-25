# Changelog

## 0.9.0 (unreleased)

First public version.

- Check clips: PASS, WARN or FAIL per clip for people and for animals (four legs, or a hopper with a tail). Checks skating, sinking and floating feet, backward and sideways joints, pops, loop seams, balance, runs that never leave the ground, walk cadence, wind-ups and follow-through on attacks, enemy attack tells, animal leg alignment and skin collapse.
- Fix current clip: re-plants sliding feet, closes the loop seam, smooths pops and moves or removes root motion, always on a copy. A fix that makes the clip worse is thrown away.
- Pose Adapt: pose a frame by hand and bake the change through a copy of the clip, keeping untouched feet planted.
- Settings live on the scene as `scene.gaitkeeper`.
- Licensed GPL-3.0-or-later.
