#!/usr/bin/env python3
"""Rebuild the synthetic test media used by the docs and manual checks.

Every clip is tiny (640x360, a few seconds) so it can live in the repository.
Each one reproduces exactly one generation defect; ``good.mp4`` is the control
that must always pass. Rebuilding is deterministic apart from encoder noise.

Usage:
    python scripts/make_testmedia.py                  # rebuild into testmedia/synthetic
    python scripts/make_testmedia.py --only flicker   # rebuild a single clip
    python scripts/make_testmedia.py --dest /tmp/tm   # build elsewhere (CI does this)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
WIDTH, HEIGHT, FPS, SECONDS = 640, 360, 24, 3

FONT_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)

# name -> (duration seconds, frame count, has audio); tolerance is applied below.
EXPECTED: dict[str, tuple[float, int, bool]] = {
    "good.mp4": (3.00, 72, True),
    "freeze.mp4": (3.79, 91, True),
    "flicker.mp4": (3.00, 72, True),
    "silent.mp4": (3.00, 72, False),
    "subtitle.mp4": (3.00, 72, True),
    "black.mp4": (3.25, 78, False),
    "dup.mp4": (1.00, 24, False),
}


def _run(args: list[str]) -> None:
    if shutil.which(FFMPEG) is None:
        raise SystemExit("ffmpeg not found on PATH")
    proc = subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg failed:\n{proc.stderr.strip()}")


def _font() -> str | None:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _escape(path: str) -> str:
    """Escape a Windows path for use inside an ffmpeg filter argument."""
    return path.replace("\\", "/").replace(":", "\\:")


def _probe(path: Path) -> tuple[float, int, bool]:
    proc = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffprobe failed on {path}:\n{proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise SystemExit(f"no video stream in {path}")
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    frames = int(video.get("nb_frames") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return duration, frames, has_audio


# --- builders ---------------------------------------------------------------


def build_good(dest: Path) -> Path:
    target = dest / "good.mp4"
    _run(
        [
            "-f", "lavfi",
            "-i", f"testsrc2=size={WIDTH}x{HEIGHT}:rate={FPS}:duration={SECONDS}",
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={SECONDS}",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            str(target),
        ]
    )
    return target


def build_freeze(dest: Path, good: Path) -> Path:
    target = dest / "freeze.mp4"
    _run(
        [
            "-i", str(good),
            "-vf", "tpad=start_mode=clone:start_duration=0.8",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(target),
        ]
    )
    return target


def build_flicker(dest: Path, good: Path) -> Path:
    target = dest / "flicker.mp4"
    _run(
        [
            "-i", str(good),
            "-vf", "eq=brightness=0.3*sin(2*PI*t*8):eval=frame",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(target),
        ]
    )
    return target


def build_silent(dest: Path, good: Path) -> Path:
    target = dest / "silent.mp4"
    _run(["-i", str(good), "-an", "-c:v", "copy", str(target)])
    return target


def build_subtitle(dest: Path, good: Path) -> Path:
    font = _font()
    if font is None:
        raise SystemExit("no usable font found for drawtext")
    target = dest / "subtitle.mp4"
    filt = (
        f"drawtext=fontfile='{_escape(font)}':text='SUBTITLE':fontsize=30:"
        "fontcolor=white:box=1:boxcolor=black@0.6:x=(w-text_w)/2:y=h-45"
    )
    _run(
        [
            "-i", str(good),
            "-vf", filt,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(target),
        ]
    )
    return target


def build_black(dest: Path, good: Path) -> Path:
    target = dest / "black.mp4"
    _run(
        [
            "-f", "lavfi",
            "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r={FPS}:d=0.25",
            "-i", str(good),
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map", "[v]",
            "-an",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(target),
        ]
    )
    return target


def build_dup(dest: Path, good: Path) -> Path:
    target = dest / "dup.mp4"
    _run(
        [
            "-i", str(good),
            "-filter_complex",
            "[0:v]split[a][b];[a]trim=0:0.5,setpts=PTS-STARTPTS[v1];"
            "[b]trim=0:0.5,setpts=PTS-STARTPTS[v2];[v1][v2]concat=n=2:v=1:a=0[v]",
            "-map", "[v]",
            "-an",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(target),
        ]
    )
    return target


BUILDERS = {
    "good.mp4": lambda dest, good: build_good(dest),
    "freeze.mp4": build_freeze,
    "flicker.mp4": build_flicker,
    "silent.mp4": build_silent,
    "subtitle.mp4": build_subtitle,
    "black.mp4": build_black,
    "dup.mp4": build_dup,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild synthetic test media.")
    parser.add_argument("--dest", default="testmedia/synthetic", help="output directory")
    parser.add_argument("--only", default=None, help="build only clips whose name contains this")
    args = parser.parse_args(argv)

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    good = dest / "good.mp4"

    for name, builder in BUILDERS.items():
        if args.only and args.only not in name:
            continue
        if name == "subtitle.mp4" and _font() is None:
            print(f"  SKIP  {name} (no font found)")
            continue
        builder(dest, good)
        print(f"  built {name}")

    failures = 0
    print(f"\n{'file':<14} {'duration':>9} {'frames':>7} {'audio':>6}  verdict")
    for name, (want_d, want_f, want_a) in EXPECTED.items():
        path = dest / name
        if not path.exists():
            continue
        got_d, got_f, got_a = _probe(path)
        ok = abs(got_d - want_d) <= 0.1 and abs(got_f - want_f) <= 1 and got_a == want_a
        failures += 0 if ok else 1
        print(
            f"{name:<14} {got_d:>9.2f} {got_f:>7d} {str(got_a):>6}  {'ok' if ok else 'MISMATCH'}"
        )

    if failures:
        print(f"\n{failures} clip(s) did not match the expected profile", file=sys.stderr)
        return 1
    print("\nall clips match their expected profile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
