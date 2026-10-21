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
from .probe import ProbeError, probe
from .spec import Expect, SpecError, load_spec

DEFAULT_SPEC = """\
name: selftest
expect:
  duration: {duration}
  fps: {fps}
  frames: {frames}
  resolution: {resolution}
  audio: {audio}
"""

# ``drawtext`` aborts with a Fontconfig error when it has no fontfile, so the
# self-test searches the same paths the fixture builder does.
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


def _ffmpeg(*args: str) -> None:
    """Run ffmpeg with ``args``, raising on failure."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH")
    proc = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffmpeg failed")


def _make_frozen(target: Path, *, source: Path, hold: str = "0.6") -> None:
    """Clone the first frame for ``hold`` seconds to fake a freeze."""
    _ffmpeg(
        "-i",
        str(source),
        "-vf",
        f"tpad=start_mode=clone:start_duration={hold}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(target),
    )


def _make_static(target: Path, *, seconds: float = 1.0) -> None:
    """A clip whose every frame is identical: nothing moves at all.

    ``loop`` repeats the first frame, so the result is exactly as long as the
    requested ``seconds`` rather than however many loops were asked for.
    """
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=320x240:rate=24:duration={seconds}",
        "-vf",
        "select=eq(n\\,0),loop=loop=24:size=1:start=0",
        "-t",
        f"{seconds}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(target),
    )


def _make_black(target: Path, *, seconds: float = 0.25) -> None:
    """A short clip of pure black frames."""
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=320x240:r=24:d={seconds}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(target),
    )


def _make_flicker(target: Path, *, source: Path) -> None:
    """Oscillate brightness hard enough to be an obvious strobe."""
    _ffmpeg(
        "-i",
        str(source),
        "-vf",
        "eq=brightness=0.3*sin(2*PI*t*8):eval=frame",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(target),
    )


def _make_repeat(target: Path, *, source: Path, length: str = "0.4") -> None:
    """Play the first ``length`` seconds twice: a visible loop."""
    _ffmpeg(
        "-i",
        str(source),
        "-filter_complex",
        f"[0:v]split[a][b];[a]trim=0:{length},setpts=PTS-STARTPTS[v1];"
        f"[b]trim=0:{length},setpts=PTS-STARTPTS[v2];[v1][v2]concat=n=2:v=1:a=0[v]",
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(target),
    )


def _make_subtitle_bar(target: Path, *, font: str, seconds: float = 1.0) -> None:
    """A dark plate with bright text burned into the bottom band."""
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x203040:s=320x240:r=24:d={seconds}",
        "-vf",
        "drawbox=x=20:y=182:w=280:h=30:color=black@0.8:t=fill,"
        f"drawtext=fontfile='{_escape(font)}'"
        ":text='SUBTITLE':fontsize=22:fontcolor=white:x=(w-text_w)/2:y=186",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(target),
    )


def _make_mostly_silent(target: Path, *, seconds: float = 2.0) -> None:
    """A tone that is cut to digital silence after 0.3 s."""
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=320x240:rate=24:duration={seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={seconds}",
        "-af",
        "volume=enable='gte(t,0.3)':volume=0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(target),
    )


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


def _scratch_directory() -> tempfile.TemporaryDirectory:
    """A temp dir that never lands in the user's working directory by surprise.

    ``tempfile`` falls back to the current directory when every candidate temp
    path is unwritable, which on locked-down Windows boxes leaves
    ``takecheck-selftest-*`` folders in whatever directory the user ran from.
    So the fallback is chosen explicitly here, and it is a dot-directory that
    the project's .gitignore already covers.
    """
    try:
        probe_dir = tempfile.TemporaryDirectory(prefix="takecheck-selftest-")
    except (FileNotFoundError, PermissionError, OSError):
        fallback = Path.cwd() / ".takecheck-selftest"
        fallback.mkdir(parents=True, exist_ok=True)
        print(f"takecheck selftest: no writable system temp dir, using {fallback}")
        return tempfile.TemporaryDirectory(prefix="run-", dir=fallback)
    # Confirm the system temp really is writable before committing to it.
    try:
        marker = Path(probe_dir.name) / ".writable"
        marker.write_text("", encoding="utf-8")
        marker.unlink()
    except OSError:
        probe_dir.cleanup()
        fallback = Path.cwd() / ".takecheck-selftest"
        fallback.mkdir(parents=True, exist_ok=True)
        print(f"takecheck selftest: system temp dir is not writable, using {fallback}")
        return tempfile.TemporaryDirectory(prefix="run-", dir=fallback)
    return probe_dir


def run_selftest() -> int:
    """Run every branch in isolation and report pass/fail per case."""
    if shutil.which("ffmpeg") is None:
        print("takecheck selftest: ffmpeg not found on PATH — cannot run")
        return 3

    report = _Report()
    with _scratch_directory() as tmp:
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

        # --- frame-level checks (D1) -------------------------------------
        # Every clip below is built here, from scratch, inside the temp dir.
        default = Expect()
        good = analyse(probe(video))

        # 8. a normal clip passes all five frame checks
        for check in (check_frozen, check_duplicate, check_blank, check_flicker, check_motion):
            result = check(good, default)
            report.check(
                f"{result.name} passes on a normal clip", result.status == PASS, result.detail
            )

        # 9. a cloned first frame is reported as frozen, with a time range
        frozen = work / "frozen.mp4"
        _make_frozen(frozen, source=video, hold="0.6")
        result = check_frozen(analyse(probe(frozen)), default)
        report.check(
            "frozen stretch fails",
            result.status == FAIL and "ranges" in result.measured,
            result.detail,
        )

        # 10. a shorter hold than the limit is not reported, i.e. the
        #     threshold is actually honoured rather than always firing.
        brief = work / "brief.mp4"
        _make_frozen(brief, source=video, hold="0.08")
        result = check_frozen(analyse(probe(brief)), default)
        report.check("short hold is not frozen", result.status == PASS, result.detail)

        # 11. a completely static clip is caught by motion
        still = work / "static.mp4"
        _make_static(still)
        still_clip = analyse(probe(still))
        result = check_motion(still_clip, default)
        report.check("static clip fails motion", result.status == FAIL, result.detail)

        # 12. ...and the same clip is also reported as frozen
        result = check_frozen(still_clip, default)
        report.check("static clip fails frozen", result.status == FAIL, result.detail)

        # 13. a replayed intro is caught by duplicate
        loop = work / "loop.mp4"
        _make_repeat(loop, source=video)
        result = check_duplicate(analyse(probe(loop)), default)
        report.check("replayed intro fails duplicate", result.status == FAIL, result.detail)

        # 14. black frames are counted, and reported with a time range
        black = work / "black.mp4"
        _make_black(black)
        black_clip = analyse(probe(black))
        result = check_blank(black_clip, default)
        report.check(
            "black frames fail blank",
            result.status == FAIL and result.measured["blank_frames"] > 0,
            result.detail,
        )

        # 15. a black clip is NOT reported as flicker: one defect, one check
        result = check_flicker(black_clip, default)
        report.check("black clip is not flicker", result.status == PASS, result.detail)

        # 16. ...nor as duplicate, for the same reason
        result = check_duplicate(black_clip, default)
        report.check("black clip is not duplicate", result.status == PASS, result.detail)

        # 17. a strobing clip fails flicker
        strobe = work / "flicker.mp4"
        _make_flicker(strobe, source=video)
        result = check_flicker(analyse(probe(strobe)), default)
        report.check("strobe fails flicker", result.status == FAIL, result.detail)

        # 18. spec thresholds are honoured: a stricter flicker_max rejects a
        #     normal clip that the default accepts, so the value is really read.
        strict = Expect(flicker_max=0.0001)
        normal = check_flicker(good, default)
        harsh = check_flicker(good, strict)
        report.check(
            "flicker_max is read from the spec",
            normal.status == PASS and harsh.status == FAIL,
            f"default={normal.status} strict={harsh.status}",
        )

        # 19. every frame check reports numbers, never just a verdict
        missing = [
            check.__name__
            for check, result in (
                (check_frozen, check_frozen(good, default)),
                (check_duplicate, check_duplicate(good, default)),
                (check_blank, check_blank(good, default)),
                (check_flicker, check_flicker(good, default)),
                (check_motion, check_motion(good, default)),
            )
            if not result.measured
        ]
        report.check("every frame check reports measured values", not missing, ", ".join(missing))

        # 20. a single-frame clip does not crash the window-based checks
        single = work / "single.mp4"
        _make_black(single, seconds=1 / 24)
        single_clip = analyse(probe(single))
        try:
            check_frozen(single_clip, default)
            check_blank(single_clip, default)
            check_flicker(single_clip, default)
            check_duplicate(single_clip, default)
            check_motion(single_clip, default)
            report.check(f"single-frame clip is handled ({single_clip.count} frame)", True)
        except Exception as exc:  # noqa: BLE001 - the point is that it must not raise
            report.check("single-frame clip is handled", False, repr(exc))

        # --- media checks (D2) -------------------------------------------
        # 21. a clean clip has no subtitle band
        result = check_subtitle(info, Expect(subtitles="forbidden"))
        report.check("clean clip has no subtitle band", result.status == PASS, result.detail)

        # 22. `subtitles: allowed` skips the work entirely
        result = check_subtitle(info, Expect(subtitles="allowed"))
        report.check(
            "subtitles: allowed skips the check",
            result.status == PASS and result.measured.get("checked") is False,
            result.detail,
        )

        # 23. a burned-in bar in the bottom band is caught. drawtext needs an
        #     explicit fontfile: without one ffmpeg aborts on Windows.
        font = _font()
        if font is None:
            print("  SKIP  subtitle bar is detected (no font for drawtext)")
        else:
            band = work / "subband.mp4"
            _make_subtitle_bar(band, font=font)
            result = check_subtitle(probe(band), Expect(subtitles="forbidden"))
            report.check("subtitle bar is detected", result.status == FAIL, result.detail)

        # 24. audio: a normal tone measures clean
        result = check_audio(info, Expect(audio="required"))
        report.check("audio on a normal clip passes", result.status == PASS, result.detail)

        # 25. audio measurements are actually present
        measured = result.measured
        report.check(
            "audio reports peak and loudness",
            measured.get("peak_db") is not None and measured.get("loudness_lufs") is not None,
            f"peak={measured.get('peak_db')} lufs={measured.get('loudness_lufs')}",
        )

        # 26. a missing track is left to the spec check, not double-reported
        result = check_audio(probe(silent), Expect(audio="required"))
        report.check(
            "missing audio is not double-reported",
            result.status == PASS and result.measured.get("checked") is False,
            result.detail,
        )

        # 27. audio: forbidden really means forbidden
        result = check_audio(info, Expect(audio="forbidden"))
        report.check(
            "audio forbidden fails when a track exists", result.status == FAIL, result.detail
        )

        # 28. a mostly silent track fails
        quiet = work / "mostly-silent.mp4"
        _make_mostly_silent(quiet)
        result = check_audio(probe(quiet), Expect(audio="required"))
        report.check(
            "mostly silent audio fails",
            result.status == FAIL and result.measured["silent_fraction"] > 0.5,
            result.detail,
        )

    print(f"\n{report.total - report.failures}/{report.total} cases passed")
    return 0 if report.failures == 0 else 1
