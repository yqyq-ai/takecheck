"""Spec parsing tests (no ffmpeg needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from takecheck.spec import SpecError, load_spec


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "takes.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_minimal_spec(tmp_path: Path) -> None:
    spec = load_spec(_write(tmp_path, "name: demo\nexpect:\n  duration: 5.0\n  fps: 24\n"))
    assert spec.name == "demo"
    assert spec.expect.duration == 5.0
    assert spec.expect.fps == 24
    assert spec.expect.frozen_max_ms == 200
    assert spec.judges == ("mechanical",)


def test_resolution_parsing(tmp_path: Path) -> None:
    spec = load_spec(_write(tmp_path, "name: demo\nexpect:\n  resolution: 1280x720\n"))
    assert spec.expect.width_height() == (1280, 720)


def test_rejects_unknown_expect_key(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="unknown key"):
        load_spec(_write(tmp_path, "name: demo\nexpect:\n  duratoin: 5\n"))


def test_rejects_bad_audio_mode(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="audio"):
        load_spec(_write(tmp_path, "name: demo\nexpect:\n  audio: maybe\n"))


def test_rejects_missing_name(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="name"):
        load_spec(_write(tmp_path, "expect:\n  fps: 24\n"))


def test_rejects_missing_expect(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="expect"):
        load_spec(_write(tmp_path, "name: demo\n"))


def test_rejects_bad_resolution(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="resolution"):
        load_spec(_write(tmp_path, "name: demo\nexpect:\n  resolution: 1280 by 720\n"))


def test_rejects_invalid_yaml(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="YAML"):
        load_spec(_write(tmp_path, "name: [unclosed\n"))
