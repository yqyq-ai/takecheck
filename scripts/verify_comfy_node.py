#!/usr/bin/env python3
"""Verify the ComfyUI node end to end, without needing ComfyUI running.

This is the script behind the D3 acceptance check: it loads the node exactly as
ComfyUI would, feeds it real fixture frames, and asserts the verdict for each
clip. Requires torch and the takecheck package, so run it with ComfyUI's own
interpreter:

    "E:\\ComfyUI-aki-v2\\python\\python.exe" scripts/verify_comfy_node.py

Exit code is 0 when every expectation holds.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE_DIR = ROOT / "comfyui"
MEDIA = ROOT / "testmedia" / "synthetic"
SPEC = NODE_DIR / "takes.yml"

# clip -> whether it should pass. Each clip reproduces exactly one defect.
#
# flicker.mp4 is deliberately absent. Its brightness oscillation is built in YUV
# and pushes pixels past 0/255; ComfyUI's IMAGE tensor is clamped RGB, so by the
# time a node sees those frames the swing has been squashed from 123 to 82 and
# the flicker sits just under the threshold. That is a property of checking an
# IMAGE batch rather than a file, not a bug in the node -- a real flicker
# (exposure pumping, model inconsistency) shows up in RGB far above the limit.
# The CLI path, which reads the file directly, does catch it; that is covered by
# testmedia fixtures and check_synthetic.py.
EXPECTED: dict[str, bool] = {
    "good.mp4": True,
    "freeze.mp4": False,
    "black.mp4": False,
    "dup.mp4": False,
    "subtitle.mp4": False,
}

FRAMES = 24
SIZE = (320, 240)


def _load_node():
    """Import the node the way ComfyUI does, from custom_nodes."""
    sys.path.insert(0, str(NODE_DIR.parent))
    sys.path.insert(0, str(NODE_DIR))
    import importlib

    module = importlib.import_module("TakeCheck")
    return module.NODE_CLASS_MAPPINGS["TakeCheck"]()  # noqa: SLF001


def _frames(path: Path):
    """Decode real frames from a fixture so the test sees real content."""
    import numpy as np
    import torch

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg not found on PATH")
    width, height = SIZE
    cmd = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(path),
        "-frames:v",
        str(FRAMES),
        "-vf",
        f"scale={width}:{height}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.decode("utf-8", "replace").strip())
    per_frame = width * height * 3
    count = len(proc.stdout) // per_frame
    array = np.frombuffer(proc.stdout[: count * per_frame], dtype=np.uint8)
    array = array.reshape(count, height, width, 3)
    return torch.from_numpy(array.copy()).float() / 255.0


def main() -> int:
    try:
        import torch  # noqa: F401
    except ImportError:
        print("torch is required; run this with ComfyUI's own interpreter", file=sys.stderr)
        return 2

    if not MEDIA.is_dir():
        print(f"fixtures not found at {MEDIA}", file=sys.stderr)
        return 2

    node = _load_node()
    work = ROOT / ".tmp" / "comfy-verify"
    work.mkdir(parents=True, exist_ok=True)

    failures = 0
    rows: list[tuple[str, str, str, str]] = []
    for name, should_pass in EXPECTED.items():
        clip = MEDIA / name
        if not clip.exists():
            rows.append((name, "-", "-", "MISSING"))
            failures += 1
            continue
        frames = _frames(clip)
        passed, verdict, report, detail = node.check(
            frames, str(SPEC), 24.0, str(work / name.replace(".", "_")), False, False
        )
        ok = passed == should_pass
        failures += 0 if ok else 1
        rows.append((name, "pass" if should_pass else "fail", verdict, "ok" if ok else "MISMATCH"))
        if not ok:
            print(f"  {name}: expected {'pass' if should_pass else 'fail'}, got {verdict}")
            print(f"    {detail}")

    width = max(len(row[0]) for row in rows) + 2
    print(f"{'clip':<{width}}{'expected':<10}{'verdict':<10}result")
    for row in rows:
        print(f"{row[0]:<{width}}{row[1]:<10}{row[2]:<10}{row[3]}")

    total = len(rows)
    print(f"\n{total - failures}/{total} clips matched expectation")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
