"""ComfyUI-TakeCheck: run takecheck's acceptance checks on a generated take.

The node takes an ``IMAGE`` batch straight from a ComfyUI sampler, encodes it to
a temporary lossless video, and hands that file to ``takecheck`` -- the same
code path a user would run on the command line. No check logic lives here; this
module only adapts ComfyUI's tensors to a file and its results back to values a
graph can branch on.

Everything runs on the CPU: the frames are already in RAM when this node runs,
and the checks themselves are numpy and ffmpeg only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import torch

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_SPEC = REPO_ROOT / "takes.yml"


def _ffmpeg() -> str:
    """Locate ffmpeg, raising something a ComfyUI user can act on."""
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. takecheck needs ffmpeg and ffprobe; "
            "install ffmpeg and restart ComfyUI."
        )
    return executable


def _encode_batch(images: torch.Tensor, fps: float, target: Path) -> None:
    """Write an ``IMAGE`` batch to an H.264 file.

    ComfyUI hands over a ``(B, H, W, C)`` float tensor in 0..1. The encode is
    deliberately near-lossless (crf 12) so the checks see what the sampler
    produced rather than compression noise: a heavy encode would blur frame
    differences and make ``frozen`` and ``motion`` lie.
    """
    if images.ndim == 3:
        images = images.unsqueeze(0)
    if images.ndim != 4:
        raise ValueError(f"expected an IMAGE batch of shape (B,H,W,C), got {tuple(images.shape)}")

    batch, height, width, channels = images.shape
    if channels < 3:
        raise ValueError(f"expected RGB frames, got {channels} channel(s)")
    # ffmpeg's rawvideo wants even dimensions for yuv420p.
    if width % 2 or height % 2:
        raise ValueError(
            f"frame size {width}x{height} must be even in both axes; "
            "crop or resize by one pixel before running the check"
        )

    frames = (
        images.detach()
        .to("cpu", dtype=torch.float32)
        .clamp(0.0, 1.0)
        .mul(255.0)
        .round()
        .to(torch.uint8)[..., :3]
        .contiguous()
    )
    raw = frames.numpy().tobytes()

    cmd = [
        _ffmpeg(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        f"{max(fps, 0.01):g}",
        # Tell ffmpeg the incoming bytes are full-range RGB. Without this the
        # RGB->YUV conversion adopts limited range (16-235) and compresses the
        # luma swing, which makes a visibly strobing clip measure below the
        # flicker threshold. Measured on the flicker fixture: swing 135 in gray
        # vs 80 through a naive RGB encode -- enough to hide the defect.
        "-color_range",
        "pc",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "12",
        # Preserve full range end to end so the checks see the same luma the
        # sampler produced.
        "-color_range",
        "pc",
        "-pix_fmt",
        "yuv420p",
        str(target),
    ]
    proc = subprocess.run(cmd, input=raw, capture_output=True)
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"ffmpeg failed to encode the frames: {message}")
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError("ffmpeg reported success but wrote no video")


def _run_takecheck(video: Path, spec: Path, report: Path) -> tuple[dict, int]:
    """Invoke takecheck in-process and return its report plus exit code."""
    from takecheck.cli import main as takecheck_main

    argv = [
        "check",
        str(video),
        "--spec",
        str(spec),
        "--json",
        str(report),
        "--quiet",
    ]
    code = int(takecheck_main(argv))
    # takecheck's own contract: 0 pass, 1 fail, 2 bad spec / unreadable file.
    # A 2 is a mistake in the spec or the input, not a verdict about the take,
    # so it must not be reported as "this clip failed" -- a user would go
    # re-render a perfectly good take because a threshold was misspelled.
    if code == 2:
        raise ValueError(
            f"takecheck could not read the spec at {spec}. See the message above: "
            "an unknown key, an out-of-range threshold or invalid YAML all land here. "
            "Fix the spec; the take was not judged."
        )
    payload = {}
    if report.exists():
        payload = json.loads(report.read_text(encoding="utf-8"))
    return payload, code


class TakeCheck:
    """Score an IMAGE batch against a takes.yml spec."""

    CATEGORY = "video/validation"
    FUNCTION = "check"
    RETURN_TYPES = ("BOOLEAN", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("pass", "verdict", "report", "detail")
    OUTPUT_NODE = True
    DESCRIPTION = (
        "Run takecheck's acceptance checks (frozen, duplicate, blank, flicker, "
        "motion, subtitle, audio) on an IMAGE batch and return PASS/FAIL. "
        "CPU only: the checks use numpy and ffmpeg, never the GPU."
    )

    @classmethod
    def INPUT_TYPES(cls) -> dict:
        return {
            "required": {
                "images": ("IMAGE",),
                "spec": (
                    "STRING",
                    {
                        "default": str(DEFAULT_SPEC),
                        "multiline": False,
                        "tooltip": "Path to a takes.yml describing what this take must satisfy.",
                    },
                ),
                "fps": (
                    "FLOAT",
                    {"default": 24.0, "min": 1.0, "max": 240.0, "step": 1.0},
                ),
            },
            "optional": {
                "report_dir": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "tooltip": (
                            "Where to keep the JSON and HTML report. "
                            "Empty means a temp dir."
                        ),
                    },
                ),
                "html": (
                    "BOOLEAN",
                    {"default": True, "label_on": "write html", "label_off": "json only"},
                ),
                "keep_video": (
                    "BOOLEAN",
                    {"default": False, "label_on": "keep", "label_off": "delete"},
                ),
            },
        }

    def check(
        self,
        images: torch.Tensor,
        spec: str,
        fps: float,
        report_dir: str = "",
        html: bool = True,
        keep_video: bool = False,
    ) -> tuple[bool, str, str, str]:
        spec_path = Path(spec).expanduser()
        if not spec_path.is_file():
            raise FileNotFoundError(
                f"takes.yml not found at {spec_path}. Point the `spec` widget at an "
                "existing spec file."
            )

        out_dir = Path(report_dir).expanduser() if report_dir.strip() else None
        if out_dir is None:
            out_dir = Path(tempfile.mkdtemp(prefix="takecheck-"))
        out_dir.mkdir(parents=True, exist_ok=True)

        video = out_dir / "take.mp4"
        _encode_batch(images, fps, video)
        try:
            report = out_dir / "takecheck.json"
            payload, code = _run_takecheck(video, spec_path, report)
            if html:
                self._write_html(payload, video, out_dir / "takecheck.html")
        finally:
            if not keep_video:
                video.unlink(missing_ok=True)

        passed = code == 0
        verdict = "pass" if passed else "fail"
        failed = [c for c in payload.get("checks", []) if c.get("status") == "fail"]
        if failed:
            detail = "; ".join(f"{c['name']}: {c['detail']}" for c in failed)
        else:
            detail = f"{len(payload.get('checks', []))} checks passed"
        return (passed, verdict, str(report), detail)

    @staticmethod
    def _write_html(payload: dict, video: Path, target: Path) -> None:
        """Reuse takecheck's renderer so the node and the CLI agree."""
        from takecheck.checks import CheckResult
        from takecheck.report import render_report

        results = [CheckResult(**check) for check in payload.get("checks", [])]
        render_report(
            target,
            spec_name=str(payload.get("spec", "take")),
            video=video,
            duration=0.0,
            results=results,
            payload=payload,
        )


NODE_CLASS_MAPPINGS = {"TakeCheck": TakeCheck}
NODE_DISPLAY_NAME_MAPPINGS = {"TakeCheck": "TakeCheck (video acceptance)"}


def _selftest() -> int:
    """Exercise the node without ComfyUI, for local verification."""
    total = 0
    failures = 0

    def check(name: str, ok: bool, note: str = "") -> None:
        nonlocal total, failures
        total += 1
        failures += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{' - ' + note if note else ''}")

    print("takecheck-comfy selftest")
    work = Path(tempfile.mkdtemp(prefix="takecheck-node-"))
    spec = work / "takes.yml"
    spec.write_text(
        "name: node-test\nexpect:\n  audio: optional\n  motion_min: 0.002\n",
        encoding="utf-8",
    )

    # A moving batch must pass.
    frames = torch.rand(24, 64, 64, 3)
    node = TakeCheck()
    passed, verdict, report, detail = node.check(frames, str(spec), 24.0, str(work), False, False)
    check("moving batch passes", passed and verdict == "pass", detail[:60])

    # A frozen batch must fail.
    still = frames[:1].repeat(24, 1, 1, 1)
    passed, verdict, report, detail = node.check(still, str(spec), 24.0, str(work), False, False)
    check("frozen batch fails", (not passed) and verdict == "fail", detail[:70])

    # The report is written where we asked, and is valid JSON.
    check(
        "json report written",
        report.endswith(".json") and Path(report).is_file(),
        report,
    )

    # A single-frame batch is handled rather than crashing.
    try:
        node.check(frames[:1], str(spec), 24.0, str(work), False, False)
        check("single frame handled", True)
    except Exception as exc:  # noqa: BLE001 - the point is that it must not raise
        check("single frame handled", False, repr(exc))

    # Odd dimensions are rejected with a helpful message.
    try:
        node.check(torch.rand(4, 63, 64, 3), str(spec), 24.0, str(work), False, False)
        check("odd width rejected", False, "no error raised")
    except ValueError as exc:
        check("odd width rejected", "even" in str(exc), str(exc)[:60])

    # A missing spec is reported clearly.
    try:
        node.check(frames, str(work / "nope.yml"), 24.0, str(work), False, False)
        check("missing spec rejected", False, "no error raised")
    except FileNotFoundError:
        check("missing spec rejected", True)

    # A malformed spec must raise, not come back as "the take failed". Getting
    # this wrong sends the user off re-rendering a perfectly good take.
    bad_spec = work / "bad.yml"
    bad_spec.write_text(
        "name: bad\nexpect:\n  audio: optional\n  flicker_max: 5.0\n", encoding="utf-8"
    )
    try:
        node.check(frames, str(bad_spec), 24.0, str(work), False, False)
        check("bad spec raises instead of failing the take", False, "no error raised")
    except ValueError as exc:
        check("bad spec raises instead of failing the take", "spec" in str(exc).lower(), "")

    # ...and an unknown key must behave the same way.
    typo_spec = work / "typo.yml"
    typo_spec.write_text(
        "name: typo\nexpect:\n  audio: optional\n  motion_mim: 0.002\n", encoding="utf-8"
    )
    try:
        node.check(frames, str(typo_spec), 24.0, str(work), False, False)
        check("unknown spec key raises", False, "no error raised")
    except ValueError:
        check("unknown spec key raises", True)

    # The HTML report renders and embeds its thumbnails.
    html_dir = work / "html"
    node.check(frames, str(spec), 24.0, str(html_dir), True, False)
    html_path = html_dir / "takecheck.html"
    body = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
    check(
        "html report written",
        "<!DOCTYPE html>" in body and "data:image/jpeg;base64," in body,
        f"{len(body)} chars",
    )

    print(f"\n{total - failures}/{total} node checks passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
