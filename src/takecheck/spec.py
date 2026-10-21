"""Parse and validate ``takes.yml`` acceptance specs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

AUDIO_MODES = ("required", "optional", "forbidden")
SUBTITLE_MODES = ("forbidden", "allowed")

_RESOLUTION_RE = re.compile(r"^(\d+)x(\d+)$")
_EXPECT_KEYS = {
    "duration",
    "fps",
    "frames",
    "resolution",
    "audio",
    "subtitles",
    "frozen_max_ms",
    "black_max_frames",
    "flicker_max",
    "motion_min",
}


class SpecError(ValueError):
    """Raised when a spec file is missing, malformed or self-contradictory."""


def _as_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"`{field}` must be a number, got {value!r}")
    return float(value)


def _as_int(value: Any, field: str) -> int:
    number = _as_number(value, field)
    if number != int(number):
        raise SpecError(f"`{field}` must be an integer, got {value!r}")
    return int(number)


@dataclass(frozen=True)
class Expect:
    """What an acceptable take must satisfy."""

    duration: float | None = None
    fps: float | None = None
    frames: int | None = None
    resolution: str | None = None
    audio: str | None = None
    subtitles: str | None = None
    frozen_max_ms: int = 200
    black_max_frames: int = 0
    flicker_max: float = 0.35
    motion_min: float = 0.15

    def width_height(self) -> tuple[int, int] | None:
        """Return ``(width, height)`` when a resolution is declared."""
        if not self.resolution:
            return None
        match = _RESOLUTION_RE.match(self.resolution)
        if match is None:
            return None
        return int(match.group(1)), int(match.group(2))


@dataclass(frozen=True)
class Spec:
    """A parsed ``takes.yml``."""

    name: str
    expect: Expect
    video: str | None = None
    judges: tuple[str, ...] = ("mechanical",)
    source: Path | None = None


def _expect_from_mapping(raw: Any) -> Expect:
    if not isinstance(raw, dict):
        raise SpecError("`expect` must be a mapping")
    unknown = set(raw) - _EXPECT_KEYS
    if unknown:
        raise SpecError(f"unknown key(s) in expect: {', '.join(sorted(unknown))}")

    values: dict[str, Any] = {}

    if "duration" in raw:
        duration = _as_number(raw["duration"], "duration")
        if duration <= 0:
            raise SpecError("`duration` must be greater than zero")
        values["duration"] = duration

    if "fps" in raw:
        fps = _as_number(raw["fps"], "fps")
        if fps <= 0:
            raise SpecError("`fps` must be greater than zero")
        values["fps"] = fps

    if "frames" in raw:
        frames = _as_int(raw["frames"], "frames")
        if frames < 1:
            raise SpecError("`frames` must be at least 1")
        values["frames"] = frames

    if "resolution" in raw:
        resolution = str(raw["resolution"])
        if _RESOLUTION_RE.match(resolution) is None:
            raise SpecError(f"`resolution` must look like 1280x720, got {resolution!r}")
        values["resolution"] = resolution

    if "audio" in raw:
        mode = str(raw["audio"])
        if mode not in AUDIO_MODES:
            raise SpecError(f"`audio` must be one of {AUDIO_MODES}, got {mode!r}")
        values["audio"] = mode

    if "subtitles" in raw:
        mode = str(raw["subtitles"])
        if mode not in SUBTITLE_MODES:
            raise SpecError(f"`subtitles` must be one of {SUBTITLE_MODES}, got {mode!r}")
        values["subtitles"] = mode

    for key, field in (
        ("frozen_max_ms", "frozen_max_ms"),
        ("black_max_frames", "black_max_frames"),
    ):
        if key in raw:
            number = _as_int(raw[key], field)
            if number < 0:
                raise SpecError(f"`{field}` must not be negative")
            values[field] = number

    for key in ("flicker_max", "motion_min"):
        if key in raw:
            number = _as_number(raw[key], key)
            if not 0 <= number <= 1:
                raise SpecError(f"`{key}` must be between 0 and 1")
            values[key] = number

    return Expect(**values)


def load_spec(path: Path) -> Spec:
    """Load and validate a ``takes.yml`` file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError(f"cannot read {path}: {exc}") from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise SpecError(f"{path} must contain a YAML mapping")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SpecError("`name` is required and must be a non-empty string")

    if "expect" not in raw:
        raise SpecError("`expect` is required")

    video = raw.get("video")
    if video is not None and not isinstance(video, str):
        raise SpecError("`video` must be a path string")

    judges_raw = raw.get("judges", ["mechanical"])
    if not isinstance(judges_raw, list) or not judges_raw:
        raise SpecError("`judges` must be a non-empty list")
    judges: list[str] = []
    for item in judges_raw:
        if isinstance(item, str):
            judges.append(item)
        elif isinstance(item, dict) and "vlm" in item:
            judges.append("vlm")
        else:
            raise SpecError(f"unsupported judge entry: {item!r}")

    return Spec(
        name=name.strip(),
        expect=_expect_from_mapping(raw["expect"]),
        video=video,
        judges=tuple(judges),
        source=path,
    )
