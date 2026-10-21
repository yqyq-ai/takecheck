"""Tests for the subtitle-residue and audio checks (D2).

Like the D1 tests, this file pins the maths with synthetic arrays (no ffmpeg)
and then exercises the real decode path with clips built in a temp dir.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from takecheck.checks import FAIL, PASS
from takecheck.checks.audio_check import (
    MAX_SILENT_FRACTION,
    SILENCE_NOISE_DB,
    check_audio,
)
from takecheck.checks.subtitle_check import (
    BAND_BOTTOM,
    BAND_TOP,
    MIN_AFFECTED_FRACTION,
    ROW_CONTRAST_MIN,
    check_subtitle,
    row_contrast,
)
from takecheck.probe import VideoInfo
from takecheck.spec import Expect

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not on PATH")

WIDTH = 256
HEIGHT = 144

# ``drawtext`` needs an explicit fontfile on Windows: without one ffmpeg aborts
# with a Fontconfig error instead of drawing anything. Same search order as
# scripts/make_testmedia.py.
FONT_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def _font() -> str | None:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _escape(path: str) -> str:
    """Escape a Windows path for use inside an ffmpeg filter argument."""
    return path.replace("\\", "/").replace(":", "\\:")


needs_font = pytest.mark.skipif(_font() is None, reason="no usable font for drawtext")


def _info(path: Path, *, duration: float = 2.0, has_audio: bool = True) -> VideoInfo:
    return VideoInfo(
        path=path,
        duration=duration,
        fps=24.0,
        frames=int(duration * 24),
        frames_exact=True,
        width=640,
        height=360,
        codec="h264",
        pix_fmt="yuv420p",
        has_audio=has_audio,
    )


def _plain_frames(count: int = 12) -> np.ndarray:
    """Frames with mild, even texture everywhere -- no band of text."""
    rng = np.random.default_rng(7)
    base = rng.integers(90, 150, size=(HEIGHT, WIDTH)).astype(np.float32)
    return np.stack([base + i * 0.1 for i in range(count)])


def _with_subtitle(frames: np.ndarray, *, rows: slice | None = None) -> np.ndarray:
    """Draw a hard text bar into the bottom band of every frame."""
    out = frames.copy()
    top = int(HEIGHT * BAND_TOP)
    bottom = max(top + 1, int(HEIGHT * BAND_BOTTOM))
    band_rows = bottom - top
    target = rows or slice(top + band_rows // 2 - 2, top + band_rows // 2 + 2)
    # Alternating columns read as character strokes to a gradient measure.
    out[:, target, ::3] = 250.0
    out[:, target, 1::3] = 5.0
    return out


def _run_ffmpeg(*args: str) -> None:
    assert FFMPEG is not None
    proc = subprocess.run(
        [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:  # pragma: no cover
        raise RuntimeError(proc.stderr)


# --- subtitle: the measurement ---------------------------------------------


def test_row_contrast_is_low_for_even_texture() -> None:
    contrasts = row_contrast(_plain_frames())
    assert contrasts.size == 12
    assert contrasts.mean() < ROW_CONTRAST_MIN


def test_row_contrast_is_high_for_a_text_bar() -> None:
    contrasts = row_contrast(_with_subtitle(_plain_frames()))
    assert contrasts.mean() >= ROW_CONTRAST_MIN


def test_row_contrast_handles_a_flat_band() -> None:
    """A black letterbox must not divide by zero."""
    flat = np.zeros((6, HEIGHT, WIDTH), dtype=np.float32)
    contrasts = row_contrast(flat)
    assert np.all(contrasts == 0.0)


def test_row_contrast_ignores_detail_outside_the_band() -> None:
    """Text at the very top must not be mistaken for a subtitle."""
    frames = _plain_frames()
    top = int(HEIGHT * BAND_TOP)
    frames[:, : top - 1, ::3] = 250.0
    frames[:, : top - 1, 1::3] = 5.0
    assert row_contrast(frames).mean() < ROW_CONTRAST_MIN


# --- subtitle: the verdict --------------------------------------------------


@needs_ffmpeg
@needs_font
def test_subtitle_flags_a_clip_with_a_burned_in_bar(tmp_path: Path) -> None:
    font = _font()
    assert font is not None
    clip = tmp_path / "text.mp4"
    # A dark plate plus bright strokes in the bottom band, held for the whole
    # clip. The fontfile is explicit because drawtext cannot find a font by
    # itself on Windows.
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=0x203040:s=640x360:r=24:d=2",
        "-vf",
        "drawbox=x=80:y=280:w=480:h=40:color=black@0.8:t=fill,"
        f"drawtext=fontfile='{_escape(font)}'"
        ":text='SUBTITLE':fontsize=34:fontcolor=white:x=(w-text_w)/2:y=285",
        "-pix_fmt",
        "yuv420p",
        str(clip),
    )
    result = check_subtitle(_info(clip), Expect(subtitles="forbidden"))
    assert result.status == FAIL, result.detail
    assert result.measured["row_contrast"] >= ROW_CONTRAST_MIN
    assert result.measured["ranges"]


@needs_ffmpeg
def test_subtitle_passes_a_clean_clip(tmp_path: Path) -> None:
    clip = tmp_path / "clean.mp4"
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=24:duration=2",
        "-pix_fmt",
        "yuv420p",
        str(clip),
    )
    result = check_subtitle(_info(clip), Expect(subtitles="forbidden"))
    assert result.status == PASS, result.detail


def test_subtitle_is_skipped_when_allowed(tmp_path: Path) -> None:
    """``subtitles: allowed`` means do not look at all."""
    result = check_subtitle(_info(tmp_path / "x.mp4"), Expect(subtitles="allowed"))
    assert result.status == PASS
    assert result.measured["checked"] is False


def test_subtitle_thresholds_are_the_documented_ones() -> None:
    assert ROW_CONTRAST_MIN == 2.0
    assert MIN_AFFECTED_FRACTION == 0.30
    assert (BAND_TOP, BAND_BOTTOM) == (0.72, 0.92)


# --- audio: presence and modes ---------------------------------------------


def test_audio_missing_track_is_left_to_the_spec_check(tmp_path: Path) -> None:
    """One problem, one red line: ``spec`` already reports the missing track."""
    result = check_audio(_info(tmp_path / "x.mp4", has_audio=False), Expect(audio="required"))
    assert result.status == PASS
    assert result.measured["checked"] is False


def test_audio_forbidden_fails_when_a_track_exists(tmp_path: Path) -> None:
    result = check_audio(_info(tmp_path / "x.mp4", has_audio=True), Expect(audio="forbidden"))
    assert result.status == FAIL


def test_audio_forbidden_passes_without_a_track(tmp_path: Path) -> None:
    result = check_audio(_info(tmp_path / "x.mp4", has_audio=False), Expect(audio="forbidden"))
    assert result.status == PASS


@needs_ffmpeg
def test_audio_passes_a_normal_tone(tmp_path: Path) -> None:
    clip = tmp_path / "tone.mp4"
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x240:rate=24:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(clip),
    )
    result = check_audio(_info(clip), Expect(audio="required"))
    assert result.status == PASS, result.detail
    assert result.measured["peak_db"] is not None
    assert result.measured["loudness_lufs"] is not None


@needs_ffmpeg
def test_audio_flags_a_mostly_silent_track(tmp_path: Path) -> None:
    """A track that is silent for most of the clip is a broken track."""
    clip = tmp_path / "silence.mp4"
    # 0.4s of tone, then 2.6s of digital silence.
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x240:rate=24:duration=3",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=3",
        "-af",
        "volume=enable='gte(t,0.4)':volume=0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(clip),
    )
    result = check_audio(_info(clip, duration=3.0), Expect(audio="required"))
    assert result.status == FAIL, result.detail
    assert result.measured["silent_fraction"] > MAX_SILENT_FRACTION
    assert result.measured["silent_segments"] >= 1


@needs_ffmpeg
def test_audio_flags_clipping(tmp_path: Path) -> None:
    """A track driven past full scale must be reported as clipped.

    +20 dB is needed to actually pin the waveform to 0 dBFS; +12 dB only
    reaches about -0.4 dB after AAC encoding, which is not clipping.
    """
    clip = tmp_path / "clip.mp4"
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x240:rate=24:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-af",
        "volume=20dB",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(clip),
    )
    result = check_audio(_info(clip), Expect(audio="required"))
    assert result.status == FAIL, result.detail
    assert result.measured["peak_db"] >= -0.1


def test_audio_silence_threshold_is_the_documented_one() -> None:
    assert SILENCE_NOISE_DB == -50.0
    assert MAX_SILENT_FRACTION == 0.60


# --- measured output --------------------------------------------------------


@needs_ffmpeg
def test_both_new_checks_report_measured_values(tmp_path: Path) -> None:
    clip = tmp_path / "both.mp4"
    _run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x240:rate=24:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(clip),
    )
    info = _info(clip)
    subtitle = check_subtitle(info, Expect(subtitles="forbidden"))
    audio = check_audio(info, Expect(audio="required"))
    for result in (subtitle, audio):
        assert result.measured, f"{result.name} reported no measured values"
        assert any(
            isinstance(value, (int, float)) for value in result.measured.values()
        ), f"{result.name} reported no numeric measurement"
