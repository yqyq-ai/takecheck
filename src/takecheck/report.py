"""Self-contained HTML report: a contact sheet plus the numbers behind it.

The report has to survive being emailed or dropped in a PR, so it is a single
file with no external CSS, JS or images: thumbnails are embedded as base64 JPEG
data URIs. Open it by double-clicking, that is the whole install story.
"""

from __future__ import annotations

import base64
import html
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .checks import FAIL, PASS, WARN, CheckResult

# Thumbnails are rendered at this width; a contact sheet of a dozen frames then
# stays under a couple of hundred kilobytes.
THUMB_WIDTH = 192
# Beyond this many frames we sample evenly instead of rendering every one.
MAX_TILES = 24

_STATUS_COLOURS = {
    PASS: ("#1f7a3d", "#e8f5ec"),
    FAIL: ("#b3261e", "#fdeceb"),
    WARN: ("#8a5a00", "#fff7e0"),
}


@dataclass
class Frame:
    """One thumbnail on the contact sheet."""

    index: int
    time: float
    jpeg: bytes
    flagged: bool = False


def _ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("ffmpeg not found on PATH (install ffmpeg)")
    return executable


def _grab(path: Path, times: list[float]) -> list[Frame]:
    """Extract one JPEG per timestamp, in a single ffmpeg pass per frame."""
    frames: list[Frame] = []
    for index, when in enumerate(times):
        cmd = [
            _ffmpeg(),
            "-v",
            "error",
            "-ss",
            f"{when:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={THUMB_WIDTH}:-2",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-q:v",
            "5",
            "-",
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode == 0 and proc.stdout:
            frames.append(Frame(index=index, time=when, jpeg=proc.stdout))
    return frames


def _flagged_times(results: list[CheckResult]) -> list[float]:
    """Timestamps that any check reported as a problem."""
    times: list[float] = []
    for result in results:
        if result.status != FAIL:
            continue
        ranges = result.measured.get("ranges")
        if isinstance(ranges, list):
            for span in ranges:
                if isinstance(span, list) and span:
                    times.append(float(span[0]))
    return times


def _contact_sheet(path: Path, duration: float, flagged: list[float]) -> list[Frame]:
    """Even samples across the clip, plus one thumbnail per flagged moment."""
    duration = max(duration, 0.04)
    sampled = min(MAX_TILES, max(1, int(duration * 2)))
    step = duration / (sampled + 1)
    times = [round(step * (i + 1), 3) for i in range(sampled)]
    # Flagged moments are appended, deduplicated to a tenth of a second.
    for when in flagged:
        if 0 <= when < duration:
            rounded = round(when, 1)
            if all(abs(rounded - existing) > 0.15 for existing in times):
                times.append(rounded)
    times = sorted(set(times))[: MAX_TILES + 8]
    return _grab(path, times)


def _data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def _fmt_value(value: Any) -> str:
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_fmt_value(item) for item in value)
    return html.escape(str(value))


def _check_rows(results: list[CheckResult]) -> str:
    rows: list[str] = []
    for result in results:
        colour, background = _STATUS_COLOURS.get(result.status, ("#444", "#f2f2f2"))
        measured = ""
        if result.measured:
            pairs = " ".join(
                f"<span class='kv'><b>{html.escape(str(key))}</b> {_fmt_value(value)}</span>"
                for key, value in result.measured.items()
                if not isinstance(value, (dict, list)) or isinstance(value, list)
            )
            measured = f"<div class='measured'>{pairs}</div>"
        rows.append(
            f"<tr><td><span class='badge' style='color:{colour};background:{background}'>"
            f"{html.escape(result.status.upper())}</span></td>"
            f"<td class='name'>{html.escape(result.name)}</td>"
            f"<td>{html.escape(result.detail)}{measured}</td></tr>"
        )
    return "\n".join(rows)


def _tiles(frames: list[Frame], flagged: list[float]) -> str:
    out: list[str] = []
    for frame in frames:
        is_flagged = any(abs(frame.time - when) <= 0.2 for when in flagged)
        css = "tile flagged" if is_flagged else "tile"
        out.append(
            f"<figure class='{css}'>"
            f"<img src='{_data_uri(frame.jpeg)}' alt='frame at {frame.time:.2f}s'>"
            f"<figcaption>{frame.time:.2f}s</figcaption></figure>"
        )
    return "\n".join(out)


_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px; font: 14px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
       color: #1a1a1a; background: #fafafa; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 32px 0 12px; text-transform: uppercase; letter-spacing: .06em; color: #666; }
.sub { color: #666; margin: 0 0 24px; font-size: 13px; }
.verdict { display: inline-block; padding: 3px 12px; border-radius: 999px; font-weight: 700;
           letter-spacing: .04em; margin-left: 10px; vertical-align: 2px; }
.verdict.fail { color: #b3261e; background: #fdeceb; }
.verdict.pass { color: #1f7a3d; background: #e8f5ec; }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden;
        box-shadow: 0 1px 2px rgba(0,0,0,.06), 0 4px 12px rgba(0,0,0,.04); }
td { padding: 11px 14px; border-top: 1px solid #eee; vertical-align: top; }
tr:first-child td { border-top: 0; }
td.name { font-weight: 600; white-space: nowrap; font-family: ui-monospace, Consolas, monospace; }
.badge { display: inline-block; padding: 2px 9px; border-radius: 6px; font-size: 11px;
         font-weight: 700; letter-spacing: .05em; }
.measured { margin-top: 7px; display: flex; flex-wrap: wrap; gap: 6px; }
.kv { font-family: ui-monospace, Consolas, monospace; font-size: 11.5px; color: #444;
      background: #f4f4f5; border-radius: 5px; padding: 1px 7px; }
.kv b { color: #111; font-weight: 600; }
.sheet { display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 12px; }
.tile { margin: 0; background: #fff; border-radius: 8px; overflow: hidden; border: 3px solid transparent;
        box-shadow: 0 1px 2px rgba(0,0,0,.08); }
.tile img { display: block; width: 100%; height: auto; }
.tile figcaption { font-size: 11px; font-family: ui-monospace, Consolas, monospace; color: #666;
                   padding: 5px 8px; }
.tile.flagged { border-color: #b3261e; }
.tile.flagged figcaption { color: #b3261e; font-weight: 700; }
pre { background: #1e1e1e; color: #ddd; padding: 14px; border-radius: 8px; overflow: auto;
      font-size: 11.5px; line-height: 1.5; }
"""


def render_report(
    path: Path,
    *,
    spec_name: str,
    video: Path,
    duration: float,
    results: list[CheckResult],
    payload: dict | None = None,
) -> None:
    """Write a single-file HTML report to ``path``."""
    failed = [result for result in results if result.status == FAIL]
    verdict = "FAIL" if failed else "PASS"
    flagged = _flagged_times(results)
    frames = _contact_sheet(video, duration, flagged)

    raw = json.dumps(payload or {}, ensure_ascii=False, indent=2)
    document = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>takecheck — {html.escape(spec_name)}</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>{html.escape(spec_name)}<span class="verdict {verdict.lower()}">{verdict}</span></h1>
<p class="sub">{html.escape(str(video))} &middot; {duration:.2f}s &middot;
{len(frames)} thumbnails &middot; {len(failed)} of {len(results)} checks failed</p>

<h2>Checks</h2>
<table>
{_check_rows(results)}
</table>

<h2>Contact sheet</h2>
<p class="sub">Frames flagged by a failing check are outlined in red.</p>
<div class="sheet">
{_tiles(frames, flagged)}
</div>

<h2>Raw report</h2>
<pre>{html.escape(raw)}</pre>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
