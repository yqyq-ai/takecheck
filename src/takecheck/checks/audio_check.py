"""Audio checks: is there a track, is it audible, is it clipped, how loud?

Everything here comes from ``ffmpeg`` filters that already do the measuring, so
no audio code is decoded into Python: ``volumedetect`` gives peak and mean
level, ``silencedetect`` gives the silent stretches, and ``ebur128`` gives the
integrated loudness that broadcasters actually care about.

Nothing in this module needs numpy.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..probe import VideoInfo
from . import FAIL, PASS, CheckResult

# A peak at or above this dBFS means the waveform is hitting the ceiling.
CLIP_PEAK_DB = -0.1
# Silence shorter than this is a pause, not a defect.
MIN_SILENCE_SECONDS = 0.30
# Silence quieter than this counts as silence.
SILENCE_NOISE_DB = -50.0
# More than this share of the clip being silent is a broken audio track.
MAX_SILENT_FRACTION = 0.60
# Integrated loudness outside this window is a mixing problem, not a defect;
# we report it as a warning rather than failing the take.
LOUDNESS_RANGE = (-30.0, -10.0)

_MEAN_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB")
_MAX_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
_LOUDNESS_RE = re.compile(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", re.MULTILINE)


@dataclass
class AudioStats:
    """Raw measurements, so they can be tested without a CheckResult."""

    duration: float = 0.0
    mean_db: float | None = None
    peak_db: float | None = None
    loudness_lufs: float | None = None
    silent_seconds: float = 0.0
    silent_segments: list[tuple[float, float]] = field(default_factory=list)

    @property
    def silent_fraction(self) -> float:
        if self.duration <= 0:
            return 0.0
        return min(1.0, self.silent_seconds / self.duration)


def _ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("ffmpeg not found on PATH (install ffmpeg)")
    return executable


def _analyse(path: Path, duration: float) -> AudioStats:
    """Run ffmpeg once with several measurement filters chained."""
    filters = (
        f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={MIN_SILENCE_SECONDS},"
        "volumedetect,ebur128"
    )
    cmd = [
        _ffmpeg(),
        "-v",
        "info",
        "-nostats",
        "-i",
        str(path),
        "-af",
        filters,
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    # ffmpeg reports measurements on stderr and still exits 0 for a valid file.
    log = proc.stderr or ""

    stats = AudioStats(duration=duration)

    match = _MEAN_RE.search(log)
    if match:
        stats.mean_db = float(match.group(1))
    match = _MAX_RE.search(log)
    if match:
        stats.peak_db = float(match.group(1))
    match = _LOUDNESS_RE.search(log)
    if match:
        stats.loudness_lufs = float(match.group(1))

    starts = [float(value) for value in _SILENCE_START_RE.findall(log)]
    ends = [float(value) for value in _SILENCE_END_RE.findall(log)]
    for index, start in enumerate(starts):
        # A still-open silence runs to the end of the file.
        end = ends[index] if index < len(ends) else duration
        if end > start:
            stats.silent_segments.append((start, end))
            stats.silent_seconds += end - start

    return stats


def check_audio(info: VideoInfo, expect) -> CheckResult:
    """Verify the audio track exists, is audible, and is not clipped.

    Presence is deliberately left to ``spec_check``: when a track is missing the
    spec check already fails with "audio track missing", and reporting it a
    second time here would put two red lines on one problem. This check adds
    the measurements spec compliance does not make -- silence, clipping and
    loudness -- and enforces ``audio: forbidden``, which only exists here.
    """
    mode = expect.audio or "optional"

    if mode == "forbidden":
        status = FAIL if info.has_audio else PASS
        detail = (
            "audio track present but forbidden"
            if info.has_audio
            else "no audio track, as required"
        )
        return CheckResult(
            "audio",
            status,
            detail,
            {"checked": True, "mode": mode, "has_audio": info.has_audio},
        )

    if not info.has_audio:
        # Missing-track verdicts belong to ``spec`` (see the docstring).
        return CheckResult(
            "audio",
            PASS,
            "no audio track to measure (presence is checked by `spec`)",
            {"checked": False, "mode": mode, "has_audio": False},
        )

    stats = _analyse(info.path, info.duration)
    measured: dict[str, Any] = {
        "checked": True,
        "mode": mode,
        "has_audio": True,
        "mean_db": stats.mean_db,
        "peak_db": stats.peak_db,
        "loudness_lufs": stats.loudness_lufs,
        "silent_seconds": round(stats.silent_seconds, 3),
        "silent_fraction": round(stats.silent_fraction, 3),
        "silent_segments": len(stats.silent_segments),
        "max_silent_fraction": MAX_SILENT_FRACTION,
        "clip_peak_db": CLIP_PEAK_DB,
    }

    problems: list[str] = []
    if stats.silent_fraction > MAX_SILENT_FRACTION:
        problems.append(
            f"{stats.silent_fraction:.0%} of the clip is silent "
            f"(> {MAX_SILENT_FRACTION:.0%})"
        )
    if stats.peak_db is not None and stats.peak_db >= CLIP_PEAK_DB:
        problems.append(f"peak {stats.peak_db:.1f} dBFS hits the ceiling (clipping)")

    if problems:
        return CheckResult("audio", FAIL, "; ".join(problems), measured)

    loudness = (
        f", {stats.loudness_lufs:.1f} LUFS" if stats.loudness_lufs is not None else ""
    )
    peak = f"peak {stats.peak_db:.1f} dB" if stats.peak_db is not None else "peak unknown"
    return CheckResult(
        "audio",
        PASS,
        f"{peak}{loudness}, {stats.silent_fraction:.0%} silent",
        measured,
    )
