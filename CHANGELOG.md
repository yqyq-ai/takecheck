# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Planned for v0.1.0
- Frame-level checks: frozen, duplicate, blank, flicker, motion
- Subtitle-residue detection on the bottom band
- Audio checks: presence, silence ratio, clipping
- HTML report with a contact sheet

## [0.0.1] - 2026-10-21

### Added
- `takes.yml` spec format with validation (`name`, `expect`, optional `video` / `judges`)
- `takecheck check` — ffprobe compliance check for duration, fps, frame count, resolution, audio
- `--json` machine-readable report and CI exit codes (0 pass / 1 fail / 2 error)
- `takecheck selftest` — seven isolated cases built from synthetic ffmpeg clips
- CI on Python 3.10 / 3.12 / 3.13
