"""Tests for the frame-level checks (D1).

Two layers are covered on purpose:

* unit level -- pure functions fed synthetic arrays, no ffmpeg, so the maths
  (run detection, thresholding, defect attribution) is pinned down exactly;
* clip level -- real clips built by ffmpeg in a temp dir, so the decode path
  is exercised too.

The clip-level tests are skipped when ffmpeg is missing, which keeps the suite
runnable on a bare interpreter.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from takecheck.checks import FAIL, PASS
from takecheck.checks.frame_checks import (
    BLANK_DARK,
    DUPLICATE_MAX_RATIO,
    FROZEN_HASH_DISTANCE,
    _runs,
    check_blank,
    check_duplicate,
    check_flicker,
    check_frozen,
    check_motion,
    frozen_runs,
)
from takecheck.clip import Clip
from takecheck.frames import FrameMetrics, decode
from takecheck.probe import VideoInfo
from takecheck.spec import Expect

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not on PATH")


# --- helpers ----------------------------------------------------------------


def make_clip(
    *,
    luma: list[float],
    hash_delta: list[int] | None = None,
    motion: list[float] | None = None,
    hashes: list[int] | None = None,
    fps: float = 24.0,
) -> Clip:
    """Build a :class:`Clip` straight from arrays, bypassing ffmpeg."""
    count = len(luma)
    if hash_delta is None:
        # Default to a clearly moving picture. Zero would mark every pair as
        # "still", which makes ``duplicate`` skip every frame as frozen and
        # turns the clip into a silent no-op.
        hash_delta = [9] * max(0, count - 1)
    if motion is None:
        motion = [0.01] * max(0, count - 1)
    if hashes is None:
        hashes = list(range(count))
    # A frame has exactly one fewer neighbour than there are frames; getting
    # this wrong silently shifts every reported timestamp, so check it here.
    assert len(hash_delta) == max(0, count - 1), "hash_delta must hold one value per frame pair"
    assert len(motion) == max(0, count - 1), "motion must hold one value per frame pair"
    assert len(hashes) == count, "hashes must hold one value per frame"
    metrics = FrameMetrics(
        count=count,
        fps=fps,
        luma=np.array(luma, dtype=np.float32),
        motion=np.array(motion, dtype=np.float32),
        hash_delta=np.array(hash_delta, dtype=np.uint8),
        hashes=np.array(hashes, dtype=np.uint64),
    )
    info = VideoInfo(
        path=Path("synthetic.mp4"),
        duration=count / fps,
        fps=fps,
        frames=count,
        frames_exact=True,
        width=320,
        height=240,
        codec="h264",
        pix_fmt="yuv420p",
        has_audio=True,
    )
    return Clip(metrics=metrics, info=info)


def _run_ffmpeg(*args: str) -> None:
    assert FFMPEG is not None
    proc = subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:  # pragma: no cover - only on a broken ffmpeg
        raise RuntimeError(proc.stderr)


def _build_basic(target: Path, *, seconds: float = 1.0) -> Path:
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=320x240:rate=24:duration={seconds}",
        "-pix_fmt",
        "yuv420p",
        str(target),
    )
    return target


def _decode(path: Path) -> Clip:
    info = VideoInfo(
        path=Path(path),
        duration=1.0,
        fps=24.0,
        frames=24,
        frames_exact=True,
        width=320,
        height=240,
        codec="h264",
        pix_fmt="yuv420p",
        has_audio=True,
    )
    return Clip(decode(path, 24.0), info)


# --- run detection ----------------------------------------------------------


def test_runs_finds_consecutive_blocks() -> None:
    mask = np.array([False, True, True, True, False, True, False])
    assert _runs(mask, 1) == [(1, 3), (5, 5)]
    assert _runs(mask, 3) == [(1, 3)]
    assert _runs(mask, 4) == []


def test_runs_handles_edges_and_empty() -> None:
    assert _runs(np.array([], dtype=bool), 1) == []
    assert _runs(np.array([True, True]), 1) == [(0, 1)]
    assert _runs(np.array([True, False, True]), 3) == []


# --- frozen -----------------------------------------------------------------


def test_frozen_passes_on_moving_clip() -> None:
    # Every adjacent pair differs a lot, so no pair counts as "still".
    clip = make_clip(luma=[100.0] * 30, hash_delta=[10] * 29)
    result = check_frozen(clip, Expect())
    assert result.status == PASS
    assert result.measured["longest_run_ms"] == 0.0


def test_frozen_flags_long_still_stretch() -> None:
    # 48 frames = 47 frame pairs. Pairs 10..32 are still, which spans frames
    # 10..33: 24 identical frames, exactly 1 s at 24 fps.
    hash_delta = [10] * 10 + [0] * 23 + [10] * 14
    clip = make_clip(luma=[100.0] * 48, hash_delta=hash_delta)
    result = check_frozen(clip, Expect())
    assert result.status == FAIL
    assert result.measured["frozen_runs"] == 1
    assert result.measured["longest_run_ms"] == pytest.approx(24 / 24 * 1000, abs=1.0)


def test_frozen_respects_the_spec_threshold() -> None:
    # 8 still pairs -> 9 frames -> 375 ms.
    clip = make_clip(luma=[100.0] * 20, hash_delta=[5] * 10 + [0] * 8 + [5] * 1)
    assert check_frozen(clip, Expect(frozen_max_ms=200)).status == FAIL
    assert check_frozen(clip, Expect(frozen_max_ms=1000)).status == PASS


def test_frozen_ignores_pairs_above_the_hash_distance() -> None:
    # Distance 4 is one over the limit, so nothing may be reported.
    assert FROZEN_HASH_DISTANCE == 3
    clip = make_clip(luma=[100.0] * 20, hash_delta=[4] * 19)
    assert check_frozen(clip, Expect()).status == PASS


def test_frozen_ignores_clips_shorter_than_the_minimum() -> None:
    clip = make_clip(luma=[100.0] * 3, hash_delta=[0, 0])
    assert frozen_runs(clip, Expect()) == []
    assert check_frozen(clip, Expect()).status == PASS


def test_frozen_reports_a_time_range() -> None:
    clip = make_clip(luma=[100.0] * 48, hash_delta=[10] * 10 + [0] * 23 + [10] * 14)
    measured = check_frozen(clip, Expect()).measured
    start, end = measured["ranges"][0]
    # Frames 10..33 inclusive: 10/24 s through (33+1)/24 s.
    assert start == pytest.approx(10 / 24, abs=0.01)
    assert end == pytest.approx(34 / 24, abs=0.01)


def test_frozen_ignores_a_black_stretch() -> None:
    # 12 identical black frames are a ``blank`` defect, not a freeze.
    luma = [120.0] * 10 + [0.0] * 12 + [120.0] * 10  # 32 frames, 31 pairs
    hash_delta = [9] * 9 + [0] * 12 + [9] * 10
    clip = make_clip(luma=luma, hash_delta=hash_delta)
    assert check_frozen(clip, Expect()).status == PASS
    assert check_blank(clip, Expect()).status == FAIL


# --- duplicate --------------------------------------------------------------


def test_duplicate_flags_a_replayed_segment() -> None:
    # Frames 0..9 then the same frames again: an obvious loop.
    hashes = list(range(10)) + list(range(10)) + list(range(100, 110))
    clip = make_clip(luma=[100.0] * 30, hash_delta=[9] * 29, hashes=hashes)
    result = check_duplicate(clip, Expect())
    assert result.status == FAIL
    assert result.measured["duplicate_frames"] == 10


def test_duplicate_ignores_adjacent_repeats() -> None:
    # Immediate repeats belong to ``frozen``; here they must not count.
    hashes = [7] * 20 + [1, 2, 3, 4, 5, 6]
    clip = make_clip(luma=[100.0] * 26, hash_delta=[0] * 19 + [9] * 6, hashes=hashes)
    assert check_duplicate(clip, Expect()).status == PASS


def test_duplicate_ignores_blank_frames() -> None:
    # 20 identical black frames must be reported by ``blank``, not here.
    clip = make_clip(
        luma=[5.0] * 20 + [120.0] * 10,
        hash_delta=[0] * 19 + [9] * 10,
        hashes=[42] * 20 + list(range(100, 110)),
    )
    result = check_duplicate(clip, Expect())
    assert result.status == PASS
    assert result.measured["compared_frames"] == 10


def test_duplicate_ignores_frames_inside_a_freeze() -> None:
    # A 1 s freeze of a moving picture: the still frames are not "duplicates".
    clip = make_clip(
        luma=[120.0] * 40,
        hash_delta=[9] * 5 + [0] * 30 + [9] * 4,
        hashes=list(range(5)) + [7] * 31 + list(range(100, 104)),
    )
    result = check_duplicate(clip, Expect())
    assert result.status == PASS, result.detail


def test_duplicate_threshold_is_the_documented_one() -> None:
    assert DUPLICATE_MAX_RATIO == 0.01
    # Repeats must be at least DUPLICATE_MIN_GAP frames apart to count, so the
    # head of each clip revisits hashes 1 and 2 six frames later.
    head = [1, 2, 3, 4, 5, 6]
    # One repeat in 100 comparable frames == exactly 1%, which still passes.
    at_limit = make_clip(luma=[120.0] * 100, hashes=head + [1] + list(range(1000, 1093)))
    assert check_duplicate(at_limit, Expect()).status == PASS
    # A second repeat makes it 2%, over the limit, so it must fail.
    over = make_clip(luma=[120.0] * 100, hashes=head + [1, 2] + list(range(1000, 1092)))
    assert check_duplicate(over, Expect()).status == FAIL


def test_duplicate_on_empty_clip_does_not_crash() -> None:
    clip = make_clip(luma=[], hash_delta=[], motion=[], hashes=[])
    assert check_duplicate(clip, Expect()).status == FAIL


# --- blank ------------------------------------------------------------------


def test_blank_counts_dark_and_bright_frames() -> None:
    luma = [120.0] * 10 + [3.0] * 4 + [250.0] * 2 + [120.0] * 4
    result = check_blank(make_clip(luma=luma), Expect())
    assert result.status == FAIL
    assert result.measured["blank_frames"] == 6
    assert result.measured["dark_frames"] == 4
    assert result.measured["bright_frames"] == 2


def test_blank_passes_on_a_normal_clip() -> None:
    assert check_blank(make_clip(luma=[120.0] * 20), Expect()).status == PASS


def test_blank_respects_black_max_frames() -> None:
    luma = [120.0] * 10 + [2.0] * 3 + [120.0] * 10
    clip = make_clip(luma=luma)
    assert check_blank(clip, Expect(black_max_frames=0)).status == FAIL
    assert check_blank(clip, Expect(black_max_frames=3)).status == PASS


def test_blank_boundary_is_exclusive() -> None:
    # Exactly BLANK_DARK is not dark enough to count; just below it is.
    at_limit = make_clip(luma=[BLANK_DARK] * 20)
    assert check_blank(at_limit, Expect()).status == PASS
    below = make_clip(luma=[BLANK_DARK - 1] * 20)
    assert check_blank(below, Expect()).status == FAIL
    assert below.metrics.luma.min() < BLANK_DARK


# --- flicker ----------------------------------------------------------------


def test_flicker_flags_a_brightness_oscillation() -> None:
    luma = [60.0 if i % 2 else 200.0 for i in range(40)]
    result = check_flicker(make_clip(luma=luma), Expect())
    assert result.status == FAIL
    assert result.measured["max_window_swing"] == pytest.approx(140.0, abs=1.0)


def test_flicker_passes_on_stable_luma() -> None:
    result = check_flicker(make_clip(luma=[120.0 + (i % 3) for i in range(40)]), Expect())
    assert result.status == PASS


def test_flicker_respects_the_spec_threshold() -> None:
    luma = [100.0] * 10 + [160.0] * 10 + [100.0] * 10
    clip = make_clip(luma=luma)
    # 60/255 = 0.235: below 0.35, above 0.15.
    assert check_flicker(clip, Expect(flicker_max=0.35)).status == PASS
    assert check_flicker(clip, Expect(flicker_max=0.15)).status == FAIL


def test_flicker_ignores_windows_containing_blank_frames() -> None:
    # A hard cut to black is not a flicker; ``blank`` owns that defect.
    luma = [120.0] * 10 + [0.0] * 5 + [120.0] * 10
    result = check_flicker(make_clip(luma=luma), Expect())
    assert result.status == PASS


def test_flicker_survives_a_single_frame() -> None:
    result = check_flicker(make_clip(luma=[120.0]), Expect())
    assert result.status == PASS
    assert result.measured["max_window_swing"] == 0.0


# --- motion -----------------------------------------------------------------


def test_motion_flags_a_still_clip() -> None:
    result = check_motion(make_clip(luma=[120.0] * 20, motion=[0.0] * 19), Expect())
    assert result.status == FAIL


def test_motion_passes_on_a_moving_clip() -> None:
    result = check_motion(make_clip(luma=[120.0] * 20, motion=[0.01] * 19), Expect())
    assert result.status == PASS


def test_motion_respects_the_spec_threshold() -> None:
    clip = make_clip(luma=[120.0] * 20, motion=[0.005] * 19)
    assert check_motion(clip, Expect(motion_min=0.001)).status == PASS
    assert check_motion(clip, Expect(motion_min=0.01)).status == FAIL


def test_motion_on_a_single_frame_fails() -> None:
    result = check_motion(make_clip(luma=[120.0]), Expect())
    assert result.status == FAIL
    assert "one frame" in result.detail


def test_motion_is_outside_the_single_attribution_rule() -> None:
    """``motion`` is a whole-clip aggregate, so it may co-fire with a local one.

    A fully black clip is genuinely both blank *and* motionless; reporting both
    is accurate. What must not happen is one event firing ``blank``,
    ``frozen``, ``duplicate`` *and* ``flicker`` at once -- that is what the
    other tests pin down.
    """
    clip = make_clip(luma=[0.0] * 24, hash_delta=[9] * 23, motion=[0.0] * 23)
    assert check_blank(clip, Expect()).status == FAIL
    assert check_motion(clip, Expect()).status == FAIL
    # ...but the event-shaped checks stay quiet.
    assert check_frozen(clip, Expect()).status == PASS
    assert check_duplicate(clip, Expect()).status == PASS
    assert check_flicker(clip, Expect()).status == PASS


# --- measured output --------------------------------------------------------


@pytest.mark.parametrize(
    "check",
    [check_frozen, check_duplicate, check_blank, check_flicker, check_motion],
)
def test_each_check_reports_measured_values(check) -> None:
    result = check(make_clip(luma=[120.0] * 20, motion=[0.01] * 19), Expect())
    assert result.measured, f"{result.name} reported no measured values"
    assert all(
        isinstance(value, (int, float, list, str)) for value in result.measured.values()
    ), f"{result.name} put a non-serialisable value in measured"


# --- real decode path -------------------------------------------------------


@needs_ffmpeg
def test_decode_counts_frames_from_a_real_clip(tmp_path: Path) -> None:
    path = _build_basic(tmp_path / "good.mp4", seconds=1.0)
    clip = _decode(path)
    assert clip.count == 24
    assert clip.metrics.hash_delta.shape == (23,)
    assert clip.metrics.motion.shape == (23,)


@needs_ffmpeg
def test_decode_keeps_identical_frames_identical(tmp_path: Path) -> None:
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=320x240:r=24:d=0.5",
        "-pix_fmt",
        "yuv420p",
        str(tmp_path / "black.mp4"),
    )
    clip = _decode(tmp_path / "black.mp4")
    # Every frame is the same picture, so every hash must match.
    assert len(set(int(h) for h in clip.metrics.hashes)) == 1
    assert clip.metrics.hash_delta.max() == 0


@needs_ffmpeg
def test_decode_raises_on_a_non_video(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"definitely not a video")
    with pytest.raises(Exception):  # noqa: B017 - any decode failure is fine
        decode(broken, 24.0)
