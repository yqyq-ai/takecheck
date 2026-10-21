"""CLI behaviour tests that do not need ffmpeg."""

from __future__ import annotations

from pathlib import Path

import pytest

from takecheck.cli import main


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
