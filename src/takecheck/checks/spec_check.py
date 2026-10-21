"""Spec compliance: does the file match the declared duration/fps/frames/audio?"""

from __future__ import annotations

from typing import Any

from ..probe import VideoInfo
from ..spec import Expect
from . import FAIL, PASS, CheckResult

DURATION_TOL = 0.05  # seconds
FPS_TOL = 0.01


def check_spec(info: VideoInfo, expect: Expect) -> CheckResult:
    """Compare probed facts with the declared expectations."""
    problems: list[str] = []
    measured: dict[str, Any] = {
        "duration": round(info.duration, 3),
        "fps": round(info.fps, 3),
        "frames": info.frames,
        "resolution": f"{info.width}x{info.height}",
        "audio": info.has_audio,
    }

    if expect.duration is not None and abs(info.duration - expect.duration) > DURATION_TOL:
        problems.append(f"duration {info.duration:.2f}s != {expect.duration:.2f}s")

    if expect.fps is not None and abs(info.fps - expect.fps) > FPS_TOL:
        problems.append(f"fps {info.fps:g} != {expect.fps:g}")

    if expect.frames is not None and info.frames != expect.frames:
        suffix = "" if info.frames_exact else " (estimated)"
        problems.append(f"frames {info.frames}{suffix} != {expect.frames}")

    expected_size = expect.width_height()
    if expected_size is not None and (info.width, info.height) != expected_size:
        problems.append(f"resolution {info.width}x{info.height} != {expect.resolution}")

    if expect.audio == "required" and not info.has_audio:
        problems.append("audio track missing")
    if expect.audio == "forbidden" and info.has_audio:
        problems.append("audio track present but forbidden")

    if problems:
        return CheckResult("spec", FAIL, "; ".join(problems), measured)

    summary = (
        f"{info.width}x{info.height} | {info.fps:g}fps | {info.frames}f | {info.duration:.2f}s"
    )
    return CheckResult("spec", PASS, summary, measured)
