"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .checks import FAIL, CheckResult
from .checks.audio_check import check_audio
from .checks.frame_checks import (
    check_blank,
    check_duplicate,
    check_flicker,
    check_frozen,
    check_motion,
)
from .checks.spec_check import check_spec
from .checks.subtitle_check import check_subtitle
from .clip import analyse
from .frames import DecodeError
from .probe import ProbeError, probe
from .report import render_report
from .spec import SpecError, load_spec

# Name -> function, in the order they are reported. Checks that work on the
# decoded clip take (clip, expect); the rest take (info, expect).
FRAME_CHECKS = (
    ("frozen", check_frozen),
    ("duplicate", check_duplicate),
    ("blank", check_blank),
    ("flicker", check_flicker),
    ("motion", check_motion),
)

VIDEO_CHECKS = (
    ("subtitle", check_subtitle),
    ("audio", check_audio),
)

_TAGS = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}


def _format(result: CheckResult) -> str:
    return f"  {_TAGS[result.status]:<4}  {result.name:<9} {result.detail}"


def _payload(spec_name: str, video: Path, results: list[CheckResult]) -> dict:
    verdict = "fail" if any(r.status == FAIL for r in results) else "pass"
    return {
        "spec": spec_name,
        "video": str(video),
        "verdict": verdict,
        "checks": [asdict(r) for r in results],
    }


def cmd_check(args: argparse.Namespace) -> int:
    video = Path(args.video)
    spec_path = Path(args.spec)

    try:
        spec = load_spec(spec_path)
    except SpecError as exc:
        print(f"takecheck: error: {exc}", file=sys.stderr)
        return 2

    if not video.exists():
        print(f"takecheck: error: file not found: {video}", file=sys.stderr)
        return 2

    try:
        info = probe(video)
    except ProbeError as exc:
        print(f"takecheck: error: {exc}", file=sys.stderr)
        return 2

    results = [check_spec(info, spec.expect)]

    try:
        clip = analyse(info)
    except DecodeError as exc:
        print(f"takecheck: error: {exc}", file=sys.stderr)
        return 2

    for _name, func in FRAME_CHECKS:
        results.append(func(clip, spec.expect))

    for name, func in VIDEO_CHECKS:
        try:
            results.append(func(info, spec.expect))
        except (DecodeError, RuntimeError) as exc:
            # A check that cannot measure is reported, not crashed on: the user
            # still gets the verdict for everything else.
            results.append(CheckResult(name, FAIL, f"could not measure: {exc}", {}))

    failed = [r for r in results if r.status == FAIL]
    verdict = "FAIL" if failed else "PASS"

    payload = _payload(spec.name, video, results)

    if not args.quiet:
        print(f"{verdict}  {spec.name}  ({video.name})")
        for result in results:
            print(_format(result))
        print(f"  frames decoded: {clip.count} @ {clip.fps:g}fps")
        if failed:
            print(f"\n{len(failed)} check(s) failed")

    if args.json_out:
        target = Path(args.json_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.html_out:
        target = Path(args.html_out)
        render_report(
            target,
            spec_name=spec.name,
            video=video,
            duration=info.duration,
            results=results,
            payload=payload,
        )
        if not args.quiet:
            print(f"  report written to {target}")

    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="takecheck",
        description="Acceptance checks for AI-generated video.",
    )
    parser.add_argument("--version", action="version", version=f"takecheck {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="check a video file against a takes.yml spec")
    check.add_argument("video", help="path to the video file")
    check.add_argument(
        "--spec", default="takes.yml", help="path to takes.yml (default: %(default)s)"
    )
    check.add_argument(
        "--json", dest="json_out", help="write a machine-readable report to this path"
    )
    check.add_argument(
        "--html", dest="html_out", help="write a self-contained HTML report to this path"
    )
    check.add_argument("--quiet", action="store_true", help="only print errors")
    check.set_defaults(func=cmd_check)

    selftest = subparsers.add_parser("selftest", help="run isolated self-tests (requires ffmpeg)")
    selftest.set_defaults(func=lambda _args: _run_selftest())

    return parser


def _run_selftest() -> int:
    from .selftest import run_selftest

    return run_selftest()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
