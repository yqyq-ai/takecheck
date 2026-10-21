"""CLI behaviour tests.

The first block needs no ffmpeg (argument handling, error codes). The second
block builds real clips and is skipped when ffmpeg is missing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from takecheck.cli import main

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not on PATH")

SPEC = """\
name: cli-test
expect:
  fps: 24
  resolution: 320x240
  audio: optional
"""


def _build(target: Path) -> Path:
    assert FFMPEG is not None
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=24:duration=1",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target


def _write_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "takes.yml"
    spec.write_text(SPEC, encoding="utf-8")
    return spec


def test_version_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "takecheck" in capsys.readouterr().out


def test_missing_video_returns_2(tmp_path: Path) -> None:
    spec = tmp_path / "takes.yml"
    spec.write_text("name: demo\nexpect:\n  fps: 24\n", encoding="utf-8")
    code = main(["check", str(tmp_path / "missing.mp4"), "--spec", str(spec)])
    assert code == 2


def test_invalid_spec_returns_2(tmp_path: Path) -> None:
    spec = tmp_path / "takes.yml"
    spec.write_text("name: demo\n", encoding="utf-8")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"not a video")
    code = main(["check", str(video), "--spec", str(spec)])
    assert code == 2


def test_non_video_returns_2(tmp_path: Path) -> None:
    spec = tmp_path / "takes.yml"
    spec.write_text("name: demo\nexpect:\n  fps: 24\n", encoding="utf-8")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"definitely not a video")
    code = main(["check", str(video), "--spec", str(spec)])
    assert code == 2


# --- end-to-end with real clips --------------------------------------------


@needs_ffmpeg
def test_good_clip_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    video = _build(tmp_path / "good.mp4")
    code = main(["check", str(video), "--spec", str(_write_spec(tmp_path))])
    assert code == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    for name in ("frozen", "duplicate", "blank", "flicker", "motion"):
        assert name in out, f"{name} missing from the report"


@needs_ffmpeg
def test_json_report_carries_measured_values(tmp_path: Path) -> None:
    video = _build(tmp_path / "good.mp4")
    report = tmp_path / "report.json"
    code = main(
        [
            "check",
            str(video),
            "--spec",
            str(_write_spec(tmp_path)),
            "--json",
            str(report),
            "--quiet",
        ]
    )
    assert code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["verdict"] == "pass"
    by_name = {check["name"]: check for check in payload["checks"]}
    for name in ("frozen", "duplicate", "blank", "flicker", "motion"):
        assert by_name[name]["measured"], f"{name} has no measured values"
        # A number, not just a verdict string.
        assert any(
            isinstance(value, (int, float)) for value in by_name[name]["measured"].values()
        ), f"{name} reported no numeric measurement"


@needs_ffmpeg
def test_frozen_clip_exits_one(tmp_path: Path) -> None:
    source = _build(tmp_path / "source.mp4")
    frozen = tmp_path / "frozen.mp4"
    assert FFMPEG is not None
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            "tpad=start_mode=clone:start_duration=0.6",
            "-pix_fmt",
            "yuv420p",
            str(frozen),
        ],
        check=True,
        capture_output=True,
    )
    code = main(["check", str(frozen), "--spec", str(_write_spec(tmp_path)), "--quiet"])
    assert code == 1


@needs_ffmpeg
def test_json_report_records_the_failed_check(tmp_path: Path) -> None:
    video = tmp_path / "black.mp4"
    assert FFMPEG is not None
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=24:d=1",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    report = tmp_path / "report.json"
    code = main(
        [
            "check",
            str(video),
            "--spec",
            str(_write_spec(tmp_path)),
            "--json",
            str(report),
        ]
    )
    assert code == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["verdict"] == "fail"
    blank = next(check for check in payload["checks"] if check["name"] == "blank")
    assert blank["status"] == "fail"
    assert blank["measured"]["blank_frames"] > 0
# --- HTML report ------------------------------------------------------------


@needs_ffmpeg
def test_html_report_is_written_and_self_contained(tmp_path: Path) -> None:
    video = _build(tmp_path / "good.mp4")
    report = tmp_path / "report.html"
    code = main(
        [
            "check",
            str(video),
            "--spec",
            str(_write_spec(tmp_path)),
            "--html",
            str(report),
            "--quiet",
        ]
    )
    assert code == 0
    assert report.exists()
    document = report.read_text(encoding="utf-8")
    assert document.startswith("<!DOCTYPE html>")
    # Thumbnails are embedded, so the file works after being moved or emailed.
    assert "data:image/jpeg;base64," in document
    assert "http://" not in document and "https://" not in document


@needs_ffmpeg
def test_html_report_marks_failing_frames(tmp_path: Path) -> None:
    """A failing check must put a red outline on the contact sheet."""
    video = tmp_path / "black.mp4"
    assert FFMPEG is not None
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=24:d=1",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    report = tmp_path / "report.html"
    code = main(
        ["check", str(video), "--spec", str(_write_spec(tmp_path)), "--html", str(report),
         "--quiet"]
    )
    assert code == 1
    document = report.read_text(encoding="utf-8")
    assert "tile flagged" in document
    assert "FAIL" in document


@needs_ffmpeg
def test_html_and_json_together(tmp_path: Path) -> None:
    """Both report formats can be requested in one run."""
    video = _build(tmp_path / "good.mp4")
    html_path = tmp_path / "report.html"
    json_path = tmp_path / "report.json"
    code = main(
        [
            "check",
            str(video),
            "--spec",
            str(_write_spec(tmp_path)),
            "--html",
            str(html_path),
            "--json",
            str(json_path),
            "--quiet",
        ]
    )
    assert code == 0
    assert html_path.exists() and json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "pass"
    # The HTML embeds the same payload, so the two cannot disagree.
    assert payload["spec"] in html_path.read_text(encoding="utf-8")
