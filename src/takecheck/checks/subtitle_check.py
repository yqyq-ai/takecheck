"""Subtitle-residue check: is there burned-in text left in the bottom band?

The failure this targets is specific to image-to-video pipelines: a reference
clip is fed in, its hard subtitles are supposed to be removed or repainted,
and sometimes they survive as a ghost in the lower part of the frame.

Detection works on rows, not on regions. Inside the bottom band, a line of
text produces one or two rows whose horizontal activity is far above the rest
of that same band. So for each frame we compute::

    row contrast = (busiest row's mean |horizontal gradient|) / (band median)

Text pushes that ratio to 3x and beyond; ordinary imagery sits near 1.3. Using
a ratio *within* the band is what makes it robust: a busy scene raises both
sides and cancels out, and it does not care whether the band is dark or bright.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..frames import sample_frames
from ..probe import VideoInfo
from . import FAIL, PASS, CheckResult

# Frames are re-sampled at this size for subtitle work. 256 wide keeps a
# 30px subtitle legible after scaling while staying cheap; the 32x32 thumbnails
# used by the frame checks are far too coarse to see text at all.
SUBTITLE_WIDTH = 256
# The band that subtitles live in, as a fraction of frame height. 72%-92%
# matches the region the project spec names.
BAND_TOP = 0.72
BAND_BOTTOM = 0.92
# A row must stand this far above its own band's median to count as text.
ROW_CONTRAST_MIN = 2.0
# Fraction of sampled frames that must show the same pattern before we call it
# subtitle residue. Real subtitles persist for many frames, so a single busy
# frame is not enough.
MIN_AFFECTED_FRACTION = 0.30
# Consecutive runs shorter than this are ignored as noise.
MIN_SEGMENT_FRAMES = 3


def _band_rows(frames: np.ndarray) -> np.ndarray:
    """Horizontal-gradient energy per row, for the bottom band only.

    Returns ``(N, rows)`` in luma units per pixel.
    """
    height = frames.shape[1]
    top = int(height * BAND_TOP)
    bottom = max(top + 1, int(height * BAND_BOTTOM))
    band = frames[:, top:bottom, :]
    if band.shape[2] < 2:
        return np.zeros((len(frames), band.shape[1]), dtype=np.float32)
    return np.abs(np.diff(band, axis=2)).mean(axis=2)


def row_contrast(frames: np.ndarray) -> np.ndarray:
    """Per-frame ``busiest row / band median`` ratio inside the bottom band."""
    rows = _band_rows(frames)
    contrasts = np.zeros(len(rows), dtype=np.float32)
    for index, profile in enumerate(rows):
        median = float(np.median(profile))
        if median < 1e-6:
            # A perfectly flat band (e.g. a black letterbox) carries no text
            # signal; treat it as 0 rather than dividing by ~zero.
            contrasts[index] = 0.0
            continue
        contrasts[index] = float(np.max(profile)) / median
    return contrasts


def _runs(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Return inclusive ``(start, end)`` index pairs for runs of ``True``."""
    if mask.size == 0:
        return []
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    runs = [(int(a), int(b - 1)) for a, b in zip(edges[::2], edges[1::2], strict=False)]
    return [run for run in runs if run[1] - run[0] + 1 >= min_len]


def _fmt_ranges(ranges: list[tuple[float, float]], limit: int = 3) -> str:
    shown = ", ".join(f"{a:.2f}-{b:.2f}s" for a, b in ranges[:limit])
    if len(ranges) > limit:
        shown += f", +{len(ranges) - limit} more"
    return shown


def check_subtitle(info: VideoInfo, expect) -> CheckResult:
    """Flag a persistent bright/dark text band at the bottom of the frame."""
    if expect.subtitles != "forbidden":
        return CheckResult(
            "subtitle",
            PASS,
            "not checked: `subtitles` is not set to forbidden",
            {"checked": False, "subtitles": expect.subtitles},
        )

    height = max(16, int(round(SUBTITLE_WIDTH * info.height / max(info.width, 1))))
    frames = sample_frames(info.path, SUBTITLE_WIDTH, height)
    contrasts = row_contrast(frames)

    affected = contrasts >= ROW_CONTRAST_MIN
    segments = _runs(affected, MIN_SEGMENT_FRAMES)
    fraction = float(affected.mean()) if affected.size else 0.0
    # Only average the frames that pass the threshold: mixing in quiet frames
    # would drag the reported number below the limit that triggered the check.
    peak = float(contrasts[affected].mean()) if affected.any() else float(np.median(contrasts))

    measured: dict[str, Any] = {
        "checked": True,
        "band": [BAND_TOP, BAND_BOTTOM],
        "row_contrast": round(peak, 2),
        "row_contrast_min": ROW_CONTRAST_MIN,
        "affected_fraction": round(fraction, 3),
        "affected_min_fraction": MIN_AFFECTED_FRACTION,
        "segments": len(segments),
        "total_frames": int(len(frames)),
        "width": SUBTITLE_WIDTH,
    }

    fails = fraction >= MIN_AFFECTED_FRACTION and bool(segments)
    if not fails:
        return CheckResult(
            "subtitle",
            PASS,
            f"no persistent text band (row contrast {peak:.2f} < {ROW_CONTRAST_MIN:g} "
            f"on {fraction:.0%} of frames)",
            measured,
        )

    span = len(frames) / info.fps if info.fps else 0.0
    ranges = [(a / info.fps, (b + 1) / info.fps) for a, b in segments]
    measured["ranges"] = [[round(a, 3), round(b, 3)] for a, b in ranges]
    detail = (
        f"subtitle residue in the bottom band on {fraction:.0%} of frames "
        f"(row contrast {peak:.2f} >= {ROW_CONTRAST_MIN:g}) at {_fmt_ranges(ranges)}"
    )
    if span and not ranges:
        detail = f"subtitle residue across the clip (row contrast {peak:.2f})"
    return CheckResult("subtitle", FAIL, detail, measured)
