# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [0.1.0] - 2026-10-22

First release with the full mechanical check set. Still CPU-only, still no PyTorch.

### Added
- **Frame-level checks**: `frozen`, `duplicate`, `blank`, `flicker`, `motion`, each reporting the
  numbers behind its verdict under `measured` in the `--json` report.
- `takecheck.frames` — one-pass ffmpeg decode into 32x32 gray thumbnails, pHash and per-frame metrics,
  streamed over a pipe so long clips never have to fit in memory. `sample_frames()` gives checks a
  higher-resolution view when a thumbnail is too coarse.
- `takecheck.clip` — a decoded clip plus the derived signals every frame check reads.
- **`subtitle` check**: detects burned-in subtitle residue in the bottom band (72%–92% of height) by
  comparing the busiest row's horizontal activity against the median row of that same band. Measured on
  the fixtures: clean clips score ≈1.25, a clip with a subtitle bar scores ≈3.76.
- **`audio` check**: reports peak, integrated loudness (EBU R128) and silent fraction; fails on a
  clipped track or a clip that is mostly silent.
- **HTML report** (`--html report.html`): a self-contained file — contact sheet with thumbnails embedded
  as base64, failing moments outlined in red, every measured value per check, and the raw JSON inline.
  No external CSS, JS or images, so it survives being emailed or attached to a PR.
- `--html` flag on `takecheck check`; `--json` and `--html` can be used together.
- Self-tests grew from 7 to 32 cases; each check is exercised by a synthetic clip it must catch,
  and by a control it must not.
- 72 tests total, up from 12.

### Changed
- `motion_min` now defaults to `0.002` instead of `0.15`. The old value was written before any footage
  existed to measure: a normally moving clip scores ≈ 0.009 and a still render ≈ 0.000 on the bundled
  fixtures, so 0.15 would have failed every correct clip. Set it per pipeline in `takes.yml`.
  Known trade-off: a deliberately slowed clip scores ≈ 0.0010 and will fail the default — lower
  `motion_min` (or set it to `0`) when slow motion is intentional.
- A defect is now reported by exactly one check: `duplicate` skips blank frames and frames inside a
  freeze, `flicker` skips windows containing a blank frame, and `audio` leaves "track missing" to the
  spec check rather than failing a second time for the same problem.
- `numpy>=1.24` is now a runtime dependency.

### Known limitations
- The `subtitle` check has only been calibrated against synthetic fixtures. Real subtitle ghosts are
  semi-transparent and blurred, so the default threshold may need tuning; a scene that legitimately
  contains text in the lower third will also trip it.
- The audio loudness window is reported, not enforced: loudness outside −30…−10 LUFS is not a failure.
  Only clipping and excessive silence fail the check.
- Frame checks decode the whole clip; a 20-minute clip has not been benchmarked.

## [0.0.1] - 2026-10-21

### Added
- `takes.yml` spec format with validation (`name`, `expect`, optional `video` / `judges`)
- `takecheck check` — ffprobe compliance check for duration, fps, frame count, resolution, audio
- `--json` machine-readable report and CI exit codes (0 pass / 1 fail / 2 error)
- `takecheck selftest` — seven isolated cases built from synthetic ffmpeg clips
- CI on Python 3.10 / 3.12 / 3.13
