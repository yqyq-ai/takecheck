# takecheck

[![CI](https://github.com/yqyq-ai/takecheck/actions/workflows/ci.yml/badge.svg)](https://github.com/yqyq-ai/takecheck/actions/workflows/ci.yml)

**pytest for AI-generated video.** Turn “is this take usable?” into an executable spec and a CI gate.

> **Status: D1 — frame-level checks are in.**
> Spec parsing, ffprobe compliance checks, and frozen / duplicate / blank / flicker / motion are working.
> Subtitle residue, audio analysis, the HTML report and the PyPI release land in v0.1.

## Why

A 20-minute render should not be judged by scrubbing frames by hand. `takecheck` reads a `takes.yml`
spec, compares the delivered file against it, and returns **pass / fail + the reason** — in seconds,
on CPU, while the GPU is still rendering.

Generation pipelines fail in ways a thumbnail cannot show: a shot freezes for 300 ms, the camera starts
flickering, the reference clip’s burned-in subtitles survive the redraw, the audio track silently
disappears, the last frame of segment 3 does not match the first frame of segment 4. Each is cheap to
detect and expensive to discover after a 20-minute render — or after stitching the whole film.

Existing tools do not cover this layer: VMAF/DOVER/DVQA score perceptual quality against a reference
or a learned aesthetic prior, VideoGen-Eval is an LLM-API research harness, and ComfyUI QC nodes check
tensors inside a graph instead of the delivered file.

## Install

```bash
pip install takecheck
```

Requires `ffmpeg` / `ffprobe` on `PATH`. No PyTorch, no GPU — `numpy` is the only numeric dependency.

## Quick start

`takes.yml`:

```yaml
name: h3-ep12-shot03
expect:
  duration: 5.0
  fps: 24
  frames: 121
  resolution: 1280x720
  audio: required
  subtitles: forbidden
  frozen_max_ms: 200
  black_max_frames: 0
  flicker_max: 0.35
  motion_min: 0.002
```

```bash
takecheck check out/shot03.mp4 --spec takes.yml --json report.json
```

```console
FAIL  h3-ep12-shot03  (shot03.mp4)
  PASS  spec      1280x720 | 24fps | 121f | 5.04s
  FAIL  frozen    1 frozen stretch(es) over 200ms: 0.00-0.83s (longest 833ms)
  PASS  duplicate 0/120 frames replay an earlier frame (0.0%)
  PASS  blank     0 blank frame(s), luma 12-241
  PASS  flicker   worst 5-frame luma swing 9/255 (3.5% <= 35%)
  PASS  motion    mean frame-to-frame motion 0.0412 >= 0.0020
  SKIP  subtitle  not implemented yet (planned for v0.1)
  SKIP  audio     not implemented yet (planned for v0.1)
```

Exit codes: `0` pass, `1` fail, `2` bad spec / unreadable file.

### What the frame checks measure

Every check reports the numbers behind its verdict in `--json`, not just PASS/FAIL.

| Check | Signal | Fails when |
|---|---|---|
| `frozen` | pHash Hamming distance between consecutive frames | ≤ 3 for longer than `frozen_max_ms` |
| `duplicate` | repeated frame hashes, ignoring neighbours, blanks and freezes | more than 1% of frames replay an earlier one |
| `blank` | mean luma per frame | below 16 or above 240, more than `black_max_frames` |
| `flicker` | peak-to-peak luma inside a 5-frame window | above `flicker_max` (fraction of 0–255) |
| `motion` | mean absolute frame-to-frame difference | below `motion_min` |

Two design choices worth knowing:

- **One defect, one check.** A cut to black is reported by `blank` only; `duplicate` skips blank frames,
  and `flicker` skips windows containing them. A freeze is reported by `frozen`, and `duplicate` ignores
  frames a freeze already explains.
- **Thresholds are calibrated, not guessed.** `motion_min` defaults to `0.002` because a normally moving
  clip measures ≈ 0.009 and a still render ≈ 0.000 on the bundled fixtures. Real footage differs — set
  the values in `takes.yml` for your own pipeline.
- **Deliberately slow shots read as still.** A clip slowed down 8x measures `mean_motion ≈ 0.0010` and
  will fail the default `motion_min` of `0.002`. If your pipeline uses slow motion or static
  compositions on purpose, lower `motion_min` (or set it to `0`) in `takes.yml`.

## Roadmap

- [x] v0.0.1 — spec format, ffprobe compliance check, CLI, `takecheck selftest`
- [x] D1 — frozen / duplicate / blank / flicker / motion
- [ ] v0.1.0 — subtitle residue / audio checks, HTML report, PyPI release
- [ ] v0.2.0 — calibration against accepted/rejected takes, head/tail continuity
- [ ] v0.3.0 — pipeline lint (custom-node provenance, model hash pinning)
- [ ] v0.4.0 — pluggable VLM judge

## Test media

`testmedia/synthetic/` holds seven tiny clips that each reproduce exactly one defect — frozen frames,
duplicate frames, blank frames, flicker, missing audio, burned-in subtitles — plus `good.mp4` as the
control that must always pass. Rebuild them with:

```bash
python scripts/make_testmedia.py
```

The script also verifies each clip against its expected profile (duration, frame count, audio) and
runs in CI, so the fixtures cannot silently rot. Real footage never goes in the repository:
`testmedia/real/` is git-ignored.

## Development

```bash
pip install -e ".[dev]"
pytest -q
takecheck selftest   # builds synthetic clips in a temp dir; needs ffmpeg
```

## 中文简介

`takecheck` 是给 AI 生成视频用的**验收层**：用 `takes.yml` 声明一条片子该满足什么（时长、帧率、
无静帧、无字幕残影、音轨完整），一条命令返回通过与否和原因，可直接当 CI 门禁。
全程 CPU、秒级，能与渲染并行，不占显存。

## License

MIT.
