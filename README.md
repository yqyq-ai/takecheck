# takecheck

**pytest for AI-generated video.** Turn “is this take usable?” into an executable spec and a CI gate.

> **Status: v0.0.1 — skeleton.** Spec parsing, ffprobe compliance checks, CLI and self-tests are in.
> Frame-level checks (frozen / duplicate / blank / flicker / motion / subtitle residue / audio) land in v0.1.

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

Requires `ffmpeg` / `ffprobe` on `PATH`. No PyTorch, no GPU.

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
```

```bash
takecheck check out/shot03.mp4 --spec takes.yml --json report.json
```

```console
PASS  h3-ep12-shot03  (shot03.mp4)
  PASS  spec      1280x720 · 24fps · 121f · 5.00s
  SKIP  frozen    not implemented yet (planned for v0.1)
  ...
```

Exit codes: `0` pass, `1` fail, `2` bad spec / unreadable file.

## Roadmap

- [x] v0.0.1 — spec format, ffprobe compliance check, CLI, `takecheck selftest`
- [ ] v0.1.0 — frozen / duplicate / blank / flicker / motion / subtitle residue / audio checks, HTML report
- [ ] v0.2.0 — calibration against accepted/rejected takes, head/tail continuity
- [ ] v0.3.0 — pipeline lint (custom-node provenance, model hash pinning)
- [ ] v0.4.0 — pluggable VLM judge

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
