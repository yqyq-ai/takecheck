"""Thin ``ffprobe`` wrapper returning the facts the checks need."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ProbeError(RuntimeError):
    """Raised when a file cannot be probed as video."""


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    duration: float
    fps: float
    frames: int
    frames_exact: bool
    width: int
    height: int
    codec: str
    pix_fmt: str
    has_audio: bool


def _ratio(value: str) -> float:
    numerator, _, denominator = str(value).partition("/")
    try:
        num = float(numerator)
        den = float(denominator or 1)
    except ValueError:
        return 0.0
    return num / den if den else 0.0


def probe(path: Path, ffprobe: str = "ffprobe") -> VideoInfo:
    """Read stream facts from ``path`` with ffprobe."""
    executable = shutil.which(ffprobe)
    if executable is None:
        raise ProbeError("ffprobe not found on PATH (install ffmpeg)")

    cmd = [
        executable,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ProbeError(proc.stderr.strip() or f"ffprobe failed on {path}")

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned unparsable JSON: {exc}") from exc

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError(f"no video stream in {path}")

    fps = _ratio(video.get("r_frame_rate", "0/1")) or _ratio(video.get("avg_frame_rate", "0/1"))
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)

    duration = 0.0
    for candidate in (video.get("duration"), (data.get("format") or {}).get("duration")):
        try:
            duration = float(candidate)
            break
        except (TypeError, ValueError):
            continue

    nb_frames = video.get("nb_frames")
    frames_exact = isinstance(nb_frames, str) and nb_frames.isdigit()
    if frames_exact:
        frames = int(nb_frames)
    else:
        frames = round(duration * fps) if duration and fps else 0

    return VideoInfo(
        path=path,
        duration=duration,
        fps=fps,
        frames=frames,
        frames_exact=frames_exact,
        width=width,
        height=height,
        codec=str(video.get("codec_name") or ""),
        pix_fmt=str(video.get("pix_fmt") or ""),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )
