# SPDX-License-Identifier: GPL-3.0-or-later
"""The safety promise, run inside Blender by tests/test_blender_safety.py:

    blender -b --factory-startup --python tests/blender/safety.py -- gaitkeeper-X.Y.Z.zip WORK_DIR

- Check changes nothing in the scene (it only writes its report text and the panel's stored result).
- Fix adds exactly one new action and leaves every existing action, object and bone setting as it was.
- Undo after Fix takes the new action away again.
- A file saved after Fix opens again with the original clips unchanged.
Prints one "SAFETY ..." line per step and exits 1 on the first failure.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_rig


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"SAFETY {'ok  ' if ok else 'FAIL'} {name} {detail}".rstrip())
    if not ok:
        sys.exit(1)


def rounded(values) -> tuple:
    return tuple(round(float(v), 5) for v in values)


def action_print(act: bpy.types.Action) -> str:
    """A hash of every F-curve's path, index and keyframes."""
    action_fcurves = importlib.import_module("bl_ext.user_default.gaitkeeper.runner").action_fcurves
    rows = sorted(
        (fc.data_path, fc.array_index, tuple(rounded(k.co) + rounded(k.handle_left) for k in fc.keyframe_points))
        for fc in action_fcurves(act)
    )
    return hashlib.sha1(repr(rows).encode()).hexdigest()


def scene_print() -> dict:
    """Everything a user would notice changing, except GaitKeeper's own report and stored result."""
    scene = bpy.context.scene
    bpy.context.view_layer.update()  # what the next redraw would do
    objects = {}
    for ob in bpy.data.objects:
        ad = ob.animation_data
        bones = {}
        if ob.type == "ARMATURE":
            bones = {
                pb.name: (pb.rotation_mode, rounded(v for row in pb.matrix_basis for v in row)) for pb in ob.pose.bones
            }
        objects[ob.name] = (
            rounded(v for row in ob.matrix_world for v in row),
            ad.action.name if ad and ad.action else None,
            bones,
        )
    return {
        "frame": (scene.frame_current, scene.frame_start, scene.frame_end),
        "actions": {a.name: action_print(a) for a in bpy.data.actions},
        "objects": objects,
    }


def check_writes_nothing(arm: bpy.types.Object) -> None:
    before = scene_print()
    step("check", bpy.ops.gaitkeeper.check() == {"FINISHED"})
    step("check changes nothing", scene_print() == before, differences(before, scene_print()))


def differences(before: dict, after: dict) -> str:
    """Which parts of two scene prints differ, for the failure message."""
    out = [k for k in before if k not in ("actions", "objects") and before[k] != after[k]]
    for group in ("actions", "objects"):
        keys = set(before[group]) | set(after[group])
        out += [f"{group}:{k}" for k in sorted(keys) if before[group].get(k) != after[group].get(k)]
    if "objects:Person" in out:
        b, a = before["objects"]["Person"], after["objects"]["Person"]
        out.append(f"person action {b[1]}->{a[1]}")
        out += [f"bone {n} {b[2][n]} -> {a[2].get(n)}" for n in b[2] if b[2][n] != a[2].get(n)][:2]
    return ", ".join(out)


def fix_adds_one_copy(arm: bpy.types.Object) -> dict:
    before = scene_print()
    step("fix", bpy.ops.gaitkeeper.fix() == {"FINISHED"})
    after = scene_print()
    new = sorted(set(after["actions"]) - set(before["actions"]))
    step("fix adds one action", new == ["Walk_Glide_fixed"], str(new))
    step("originals unchanged", all(after["actions"][k] == v for k, v in before["actions"].items()))
    others = {k: v for k, v in after["objects"].items() if k != arm.name}
    step("other objects unchanged", others == {k: v for k, v in before["objects"].items() if k != arm.name})
    modes = {b: m for b, (m, _) in after["objects"][arm.name][2].items()}
    step("rotation modes unchanged", modes == {b: m for b, (m, _) in before["objects"][arm.name][2].items()})
    return before


def undo_removes_copy() -> None:
    """Fix, then Edit > Undo, as a user would in the 3D View."""
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    person = bpy.data.objects["Person"]
    with bpy.context.temp_override(window=window, area=area, active_object=person, object=person):
        bpy.ops.ed.undo_push(message="before fix")
        names = set(bpy.data.actions.keys())
        step("fix with a window", bpy.ops.gaitkeeper.fix() == {"FINISHED"})
        made = set(bpy.data.actions.keys()) - names
        bpy.ops.ed.undo()
    left = made & set(bpy.data.actions.keys())
    step("undo removes the copy", bool(made) and not left, f"made {sorted(made)}, left {sorted(left)}")


def saved_file_reopens(work: Path, originals: dict) -> None:
    path = work / "after_fix.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.open_mainfile(filepath=str(path))
    now = {a.name: action_print(a) for a in bpy.data.actions}
    step("saved file reopens", all(now.get(k) == v for k, v in originals.items()), str(sorted(now)))


def run_all() -> None:
    zip_path, work = sys.argv[sys.argv.index("--") + 1 :]
    bpy.ops.extensions.package_install_files(filepath=zip_path, repo="user_default", enable_on_install=True)
    rig = demo_rig.build_rig()
    demo_rig.key_idle(rig)
    demo_rig.key_glide(rig)
    demo_rig.key_other_object()
    bpy.context.view_layer.objects.active = rig
    check_writes_nothing(rig)
    snapshot = fix_adds_one_copy(rig)
    saved_file_reopens(Path(work), snapshot["actions"])
    person = bpy.data.objects["Person"]
    bpy.context.view_layer.objects.active = person
    person.animation_data.action = bpy.data.actions["Walk_Glide"]
    if bpy.app.background:
        print("SAFETY skip undo (needs a window: run without -b)")
    else:
        undo_removes_copy()
    print("SAFETY PASSED")


def run_in_window() -> None:
    """With a window, wait for it to open (undo needs one), run, and quit."""
    try:
        run_all()
    finally:
        bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    if bpy.app.background:
        run_all()
    else:
        bpy.app.timers.register(run_in_window, first_interval=1.0)
