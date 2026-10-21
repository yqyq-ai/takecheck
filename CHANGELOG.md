# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **Frame-level checks (D1)**: `frozen`, `duplicate`, `blank`, `flicker`, `motion`, each reporting the
  numbers behind its verdict under `measured` in the `--json` report.
- `takecheck.frames` — one-pass ffmpeg decode into 32x32 gray thumbnails, pHash and per-frame metrics,
  streamed over a pipe so long clips never have to fit in memory.
- `takecheck.clip` — a decoded clip plus the derived signals every frame check reads.
- Self-tests grew from 7 to 24 cases; each new check is exercised by a synthetic clip it must catch,
  and by a control it must not.
- 39 new unit / clip-level tests (51 total, up from 12).

### Changed
- `motion_min` now defaults to `0.002` instead of `0.15`. The old value was written before any footage
  existed to measure: a normally moving clip scores ≈ 0.009 and a still render ≈ 0.000 on the bundled
  fixtures, so 0.15 would have failed every correct clip. Set it per pipeline in `takes.yml`.
  Known trade-off: a deliberately slowed clip scores ≈ 0.0010 and will fail the default — lower
  `motion_min` (or set it to `0`) when slow motion is intentional.
- A defect is now reported by exactly one check: `duplicate` skips blank frames and frames inside a
  freeze, and `flicker` skips windows containing a blank frame.
- `numpy>=1.24` is now a runtime dependency.

### Planned for v0.1.0
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
