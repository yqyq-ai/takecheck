"""Isolated self-tests.

Every branch builds a synthetic clip with ffmpeg inside a temporary directory,
so the tests never touch user footage. Run with ``takecheck selftest``.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .checks import FAIL, PASS
from .checks.spec_check import check_spec
from .probe import ProbeError, probe
from .spec import SpecError, load_spec

DEFAULT_SPEC = """\
name: selftest
expect:
  duration: {duration}
  fps: {fps}
  frames: {frames}
  resolution: {resolution}
  audio: {audio}
"""


class _Report:
    def __init__(self) -> None:
        self.total = 0
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.total += 1
        if not ok:
            self.failures += 1
        suffix = f" - {detail}" if detail else ""
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{suffix}")


def _make_clip(
    target: Path,
    *,
    seconds: float = 1.0,
    rate: int = 24,
    size: str = "320x240",
    audio: bool = True,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH")
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={size}:rate={rate}:duration={seconds}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(target))
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffmpeg failed to build a test clip")


def _write_spec(
    directory: Path,
    *,
    duration: float = 1.0,
    fps: float = 24,
    frames: int = 24,
    resolution: str = "320x240",
    audio: str = "required",
) -> Path:
    path = directory / "takes.yml"
    path.write_text(
        DEFAULT_SPEC.format(
            duration=duration,
            fps=fps,
            frames=frames,
            resolution=resolution,
            audio=audio,
        ),
        encoding="utf-8",
    )
    return path


def run_selftest() -> int:
    """Run every branch in isolation and report pass/fail per case."""
    if shutil.which("ffmpeg") is None:
        print("takecheck selftest: ffmpeg not found on PATH — cannot run")
        return 3

    report = _Report()
    with tempfile.TemporaryDirectory(prefix="takecheck-selftest-") as tmp:
        work = Path(tmp)
        video = work / "good.mp4"
        _make_clip(video)
        info = probe(video)

        # 1. a matching spec passes
        spec = load_spec(_write_spec(work))
        result = check_spec(info, spec.expect)
        report.check("matching spec passes", result.status == PASS, result.detail)

        # 2. wrong fps fails
        spec = load_spec(_write_spec(work, fps=30))
        result = check_spec(info, spec.expect)
        report.check("wrong fps fails", result.status == FAIL, result.detail)

        # 3. wrong resolution fails
        spec = load_spec(_write_spec(work, resolution="640x480"))
        result = check_spec(info, spec.expect)
        report.check("wrong resolution fails", result.status == FAIL, result.detail)

        # 4. forbidden audio fails when a track is present
        spec = load_spec(_write_spec(work, audio="forbidden"))
        result = check_spec(info, spec.expect)
        report.check("forbidden audio fails", result.status == FAIL, result.detail)

        # 5. required audio fails on a silent clip
        silent = work / "silent.mp4"
        _make_clip(silent, audio=False)
        spec = load_spec(_write_spec(work, audio="required"))
        result = check_spec(probe(silent), spec.expect)
        report.check("missing audio fails", result.status == FAIL, result.detail)

        # 6. unknown spec key is rejected
        broken = work / "unknown-key.yml"
        broken.write_text("name: x\nexpect:\n  duratoin: 1\n", encoding="utf-8")
        try:
            load_spec(broken)
            report.check("unknown key rejected", False, "no error raised")
        except SpecError:
            report.check("unknown key rejected", True)

        # 7. probing a missing file raises
        try:
            probe(work / "nope.mp4")
            report.check("missing file rejected", False, "no error raised")
        except ProbeError:
            report.check("missing file rejected", True)

    print(f"\n{report.total - report.failures}/{report.total} cases passed")
    return 0 if report.failures == 0 else 1
