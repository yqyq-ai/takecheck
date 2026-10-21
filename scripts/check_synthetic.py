#!/usr/bin/env python3
"""Check every clip in ``testmedia/synthetic`` and assert the expected verdict.

This is the D1 acceptance gate, kept as a script so it can be re-run after any
threshold change. Each fixture declares exactly one defect, so the expectation
is precise: the named clip must be caught by the named check, and ``good.mp4``
must pass everything.

Usage:
    python scripts/check_synthetic.py            # human-readable summary
    python scripts/check_synthetic.py --verbose  # also print each check line

Exit code is 0 when every expectation holds, 1 otherwise.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

MEDIA = Path(__file__).resolve().parent.parent / "testmedia" / "synthetic"

SPEC = """\
name: synthetic
expect:
  audio: required
  frozen_max_ms: 200
  black_max_frames: 0
  flicker_max: 0.35
  motion_min: 0.002
"""

# clip -> the check that must fail on it. ``None`` means "must pass cleanly".
EXPECTED: dict[str, str | None] = {
    "good.mp4": None,
    "freeze.mp4": "frozen",
    "dup.mp4": "duplicate",
    "black.mp4": "blank",
    "flicker.mp4": "flicker",
    # No audio track at all: caught by the spec check.
    "silent.mp4": "spec",
    # Burned-in subtitles are D2 work; D1 must neither catch nor false-positive on it.
    "subtitle.mp4": None,
}


def _run(video: Path, spec: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "takecheck", "check", str(video), "--spec", str(spec)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout + proc.stderr


def _failed_checks(report: str) -> list[str]:
    """Check names that failed, read from the indented check lines only.

    The verdict header (``FAIL  spec-name  (file.mp4)``) is unindented, so
    requiring leading whitespace keeps it out of the list.
    """
    names: list[str] = []
    for line in report.splitlines():
        if not line.startswith(" "):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "FAIL":
            names.append(parts[1])
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the synthetic fixtures.")
    parser.add_argument("--verbose", action="store_true", help="print every check line")
    parser.add_argument("--media", default=str(MEDIA), help="fixture directory")
    args = parser.parse_args(argv)

    media = Path(args.media)
    if not media.is_dir():
        print(f"no such directory: {media}", file=sys.stderr)
        return 2

    failures = 0
    rows: list[tuple[str, str, str, str]] = []

    with tempfile.TemporaryDirectory(prefix="takecheck-fixtures-") as tmp:
        spec = Path(tmp) / "takes.yml"
        spec.write_text(SPEC, encoding="utf-8")

        for name, expected_check in EXPECTED.items():
            video = media / name
            if not video.exists():
                rows.append((name, "-", "-", "MISSING"))
                failures += 1
                continue

            code, report = _run(video, spec)
            failed = _failed_checks(report)

            if expected_check is None:
                ok = code == 0 and not failed
                verdict = "PASS" if ok else "FALSE POSITIVE"
            else:
                ok = code == 1 and expected_check in failed
                verdict = "PASS" if ok else f"MISSED ({expected_check})"

            failures += 0 if ok else 1
            rows.append((name, expected_check or "(clean)", ",".join(failed) or "-", verdict))
            if args.verbose or not ok:
                print(f"--- {name} (exit {code}) ---")
                print(report.rstrip())

    width = max(len(row[0]) for row in rows) + 2
    fail_width = max(len(row[2]) for row in rows) + 2
    print(f"{'file':<{width}}{'must fail':<14}{'did fail':<{fail_width}}verdict")
    for name, expected, actual, verdict in rows:
        print(f"{name:<{width}}{expected:<14}{actual:<{fail_width}}{verdict}")

    bad = sum(1 for row in rows if row[3] != "PASS")
    print(f"\n{len(rows) - bad}/{len(rows)} fixtures behaved as expected")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
