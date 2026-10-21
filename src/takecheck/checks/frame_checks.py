"""Frame-level checks: frozen, duplicate, blank, flicker, motion.

All five read the same decoded clip (see :mod:`takecheck.clip`), so adding them
costs no extra ffmpeg pass. Every check reports the numbers it measured, not
just a verdict -- a failing run has to explain itself.

**Localised defects are attributed to exactly one check.** ``frozen``,
``duplicate``, ``blank`` and ``flicker`` all describe an event at a specific
time, so they must not report the same event: a black stretch is ``blank``
only, a freeze is ``frozen`` only, and ``duplicate``/``flicker`` skip blank
frames and frozen stretches. Otherwise one bad moment would produce four red
lines and bury the actual diagnosis.

``motion`` is deliberately outside that rule: it is a whole-clip aggregate
("does this clip move at all over its length"), not an event with a timestamp,
so it answers a different question. A fully black clip genuinely is both blank
*and* motionless, and reporting both is accurate rather than redundant.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..clip import Clip
from ..spec import Expect
from . import FAIL, PASS, CheckResult

# Two consecutive frames count as "the same picture" at or below this pHash
# Hamming distance (0 = identical, 64 = nothing in common).
FROZEN_HASH_DISTANCE = 3
# A freeze has to last at least this many frames before it is even considered,
# so that a single skipped frame is not reported as a still stretch.
FROZEN_MIN_FRAMES = 5
# Frames closer together than this are neighbours, not duplicates: immediate
# repeats are what ``frozen`` is for.
DUPLICATE_MIN_GAP = 5
# Share of comparable frames allowed to be repeats before the clip is rejected.
DUPLICATE_MAX_RATIO = 0.01
# Mean luma below/above these is treated as a black or blown-out frame.
BLANK_DARK = 16.0
BLANK_BRIGHT = 240.0
# Sliding window (frames) used for the flicker extreme-range measurement.
FLICKER_WINDOW = 5


def _runs(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Return ``(start, end)`` index pairs for runs of ``True`` >= ``min_len``.

    ``end`` is inclusive, in the index space of ``mask``.
    """
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


def _seconds(pairs: list[tuple[int, int]], fps: float) -> list[tuple[float, float]]:
    return [(a / fps, (b + 1) / fps) for a, b in pairs]


def frozen_runs(clip: Clip, expect: Expect) -> list[tuple[int, int]]:
    """Frame index ranges that count as a freeze, inclusive.

    Indices refer to frames, not to the ``hash_delta`` array.

    Blank frames are excluded: a stretch of pure black is a *blank* defect, and
    it would otherwise be reported here as well, double-counting one problem.
    """
    if clip.count < FROZEN_MIN_FRAMES:
        return []
    # One entry per adjacent pair, so pair i compares frame i and frame i+1.
    still = clip.metrics.hash_delta <= FROZEN_HASH_DISTANCE
    luma = clip.metrics.luma
    blank = (luma < BLANK_DARK) | (luma > BLANK_BRIGHT)
    # Drop pairs where either frame is blank, so a run cannot span black frames.
    still &= ~blank[:-1] & ~blank[1:]
    allowed = int(round(clip.ms_to_frames(expect.frozen_max_ms)))
    # A run of N pairs spans N+1 frames, so require N+1 > allowed.
    min_pairs = max(FROZEN_MIN_FRAMES - 1, allowed)
    return [(start, end + 1) for start, end in _runs(still, min_pairs)]


def check_frozen(clip: Clip, expect: Expect) -> CheckResult:
    """Flag stretches where nothing moves for longer than ``frozen_max_ms``."""
    runs = frozen_runs(clip, expect)
    longest_frames = max((end - start + 1 for start, end in runs), default=0)

    measured: dict[str, Any] = {
        "longest_run_ms": round(clip.ms(longest_frames), 1),
        "frozen_runs": len(runs),
        "allowed_ms": expect.frozen_max_ms,
        "hash_distance": FROZEN_HASH_DISTANCE,
        "total_frames": clip.count,
    }
    if not runs:
        return CheckResult(
            "frozen",
            PASS,
            f"longest still stretch {measured['longest_run_ms']:.0f}ms "
            f"(limit {expect.frozen_max_ms}ms)",
            measured,
        )

    ranges = _seconds(runs, clip.fps)
    measured["ranges"] = [[round(a, 3), round(b, 3)] for a, b in ranges]
    detail = (
        f"{len(runs)} frozen stretch(es) over {expect.frozen_max_ms}ms: "
        f"{_fmt_ranges(ranges)} (longest {measured['longest_run_ms']:.0f}ms)"
    )
    return CheckResult("frozen", FAIL, detail, measured)


def check_duplicate(clip: Clip, expect: Expect) -> CheckResult:
    """Flag frames that replay an earlier frame after the picture has moved on.

    Blank frames and frames inside a freeze are skipped: those are reported by
    ``blank`` and ``frozen``, and counting them here would report one defect
    three times over.
    """
    hashes = clip.metrics.hashes
    luma = clip.metrics.luma
    total = len(hashes)
    if total == 0:
        return CheckResult("duplicate", FAIL, "no frames decoded", {"total_frames": 0})

    usable = (luma >= BLANK_DARK) & (luma <= BLANK_BRIGHT)
    for start, end in frozen_runs(clip, expect):
        usable[start : end + 1] = False

    repeats: list[int] = []
    seen: dict[int, int] = {}
    for index in range(total):
        if not usable[index]:
            continue
        key = int(hashes[index])
        first = seen.get(key)
        if first is None:
            seen[key] = index
        elif index - first >= DUPLICATE_MIN_GAP:
            repeats.append(index)

    counted = int(usable.sum())
    ratio = len(repeats) / counted if counted else 0.0
    measured: dict[str, Any] = {
        "duplicate_frames": len(repeats),
        "duplicate_ratio": round(ratio, 4),
        "allowed_ratio": DUPLICATE_MAX_RATIO,
        "min_gap_frames": DUPLICATE_MIN_GAP,
        "compared_frames": counted,
        "total_frames": total,
    }
    if ratio <= DUPLICATE_MAX_RATIO:
        return CheckResult(
            "duplicate",
            PASS,
            f"{len(repeats)}/{counted} frames replay an earlier frame ({ratio:.1%})",
            measured,
        )

    times = [index / clip.fps for index in repeats[:5]]
    measured["first_repeats_s"] = [round(t, 3) for t in times]
    detail = (
        f"{len(repeats)}/{counted} frames replay an earlier frame ({ratio:.1%} > "
        f"{DUPLICATE_MAX_RATIO:.0%}), first at {times[0]:.2f}s"
    )
    return CheckResult("duplicate", FAIL, detail, measured)


def check_blank(clip: Clip, expect: Expect) -> CheckResult:
    """Count frames that are essentially black or blown out to white."""
    luma = clip.metrics.luma
    dark = luma < BLANK_DARK
    bright = luma > BLANK_BRIGHT
    bad = dark | bright

    measured: dict[str, Any] = {
        "blank_frames": int(bad.sum()),
        "dark_frames": int(dark.sum()),
        "bright_frames": int(bright.sum()),
        "allowed_frames": expect.black_max_frames,
        "min_luma": round(float(luma.min()), 2) if luma.size else 0.0,
        "max_luma": round(float(luma.max()), 2) if luma.size else 0.0,
        "mean_luma": round(float(luma.mean()), 2) if luma.size else 0.0,
        "total_frames": clip.count,
    }
    if measured["blank_frames"] <= expect.black_max_frames:
        return CheckResult(
            "blank",
            PASS,
            f"{measured['blank_frames']} blank frame(s), "
            f"luma {measured['min_luma']:.0f}-{measured['max_luma']:.0f}",
            measured,
        )

    ranges = _seconds(_runs(bad, 1), clip.fps)
    measured["ranges"] = [[round(a, 3), round(b, 3)] for a, b in ranges]
    detail = (
        f"{measured['blank_frames']} blank frame(s) (allowed {expect.black_max_frames}) "
        f"at {_fmt_ranges(ranges)}: "
        f"{measured['dark_frames']} dark, {measured['bright_frames']} bright"
    )
    return CheckResult("blank", FAIL, detail, measured)


def check_flicker(clip: Clip, expect: Expect) -> CheckResult:
    """Measure the worst brightness swing inside a short sliding window.

    ``flicker_max`` is a fraction of full scale: a clip whose mean luma jumps
    by 35% of 0..255 within a handful of frames is visibly strobing. Windows
    that contain a blank frame are ignored -- a cut to black is not a flicker
    and is already reported by ``blank``.
    """
    luma = clip.metrics.luma
    if luma.size == 0:
        return CheckResult("flicker", FAIL, "no frames decoded", {"frames": 0})

    blank = (luma < BLANK_DARK) | (luma > BLANK_BRIGHT)
    window = max(2, min(FLICKER_WINDOW, luma.size))
    swings = np.zeros(luma.size, dtype=np.float32)
    for index in range(luma.size):
        lo = max(0, index - window + 1)
        if blank[lo : index + 1].any():
            continue
        swings[index] = np.ptp(luma[lo : index + 1])

    swing = float(swings.max())
    normalised = swing / 255.0

    measured: dict[str, Any] = {
        "max_window_swing": round(swing, 2),
        "normalised_swing": round(normalised, 4),
        "allowed": expect.flicker_max,
        "window_frames": window,
        "mean_abs_step": round(float(np.abs(np.diff(luma)).mean()) / 255.0, 4)
        if luma.size > 1
        else 0.0,
        "total_frames": clip.count,
    }
    if normalised <= expect.flicker_max:
        return CheckResult(
            "flicker",
            PASS,
            f"worst {window}-frame luma swing {swing:.0f}/255 "
            f"({normalised:.1%} <= {expect.flicker_max:.0%})",
            measured,
        )

    index = int(swings.argmax())
    measured["worst_at_s"] = round(index / clip.fps, 3)
    detail = (
        f"luma swings {swing:.0f}/255 ({normalised:.1%}) within {window} frames at "
        f"{measured['worst_at_s']:.2f}s, over the {expect.flicker_max:.0%} limit"
    )
    return CheckResult("flicker", FAIL, detail, measured)


def check_motion(clip: Clip, expect: Expect) -> CheckResult:
    """Reject a clip whose frames barely differ, i.e. a near-static render."""
    motion = clip.metrics.motion
    if motion.size == 0:
        measured = {
            "mean_motion": 0.0,
            "min_motion": 0.0,
            "allowed_min": expect.motion_min,
            "total_frames": clip.count,
        }
        return CheckResult("motion", FAIL, "only one frame, cannot measure motion", measured)

    mean_motion = float(motion.mean())
    measured: dict[str, Any] = {
        "mean_motion": round(mean_motion, 5),
        "min_motion": round(float(motion.min()), 5),
        "max_motion": round(float(motion.max()), 5),
        "allowed_min": expect.motion_min,
        "still_frames": int((motion < expect.motion_min).sum()),
        "total_frames": clip.count,
    }
    if mean_motion >= expect.motion_min:
        return CheckResult(
            "motion",
            PASS,
            f"mean frame-to-frame motion {mean_motion:.4f} >= {expect.motion_min:.4f}",
            measured,
        )
    return CheckResult(
        "motion",
        FAIL,
        f"mean frame-to-frame motion {mean_motion:.4f} is below the required "
        f"{expect.motion_min:.4f} (near-static output)",
        measured,
    )
