# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and validate the extension zip with Blender's own tooling.

    python scripts/build.py [OUT_DIR]      (default: dist/)

Install the zip in Blender: Edit > Preferences > Get Extensions > the arrow menu > Install from Disk.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

from blender_exe import find_blender

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "gaitkeeper"


def blender_command(*args: str) -> None:
    """Run `blender --command extension ...` and stop on failure."""
    cmd = [find_blender(), "--factory-startup", "--command", "extension", *args]
    run = subprocess.run(cmd, capture_output=True, text=True, check=False)
    print(run.stdout.strip())
    if run.returncode != 0:
        print(run.stderr.strip(), file=sys.stderr)
        raise SystemExit(run.returncode)


def build(out_dir: Path) -> Path:
    """Build the zip into out_dir, validate it, and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    blender_command("validate", str(SOURCE))
    blender_command("build", "--source-dir", str(SOURCE), "--output-dir", str(out_dir))
    version = tomllib.loads((SOURCE / "blender_manifest.toml").read_text(encoding="utf-8"))["version"]
    zip_path = out_dir / f"gaitkeeper-{version}.zip"
    blender_command("validate", str(zip_path))
    return zip_path


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"))
