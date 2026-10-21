"""Decode a video into per-frame metrics with a single ffmpeg pass.

Frames are streamed over a pipe as raw grayscale and reduced to small
``numpy`` arrays on the fly, so a long clip never has to fit in memory.
Nothing here touches torch; ``numpy`` is the only numeric dependency.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Every decoded frame is box-downsampled to this size before metrics are taken.
# 32x32 keeps pHash and brightness stable while staying cheap on 20 s clips.
THUMB = 32
# pHash works on the 8x8 low-frequency block, i.e. 64 bits.
HASH_SIZE = 8


class DecodeError(RuntimeError):
    """Raised when ffmpeg cannot decode the file into frames."""


@dataclass
class FrameMetrics:
    """Per-frame numbers plus the derived signals the checks need."""

    count: int = 0
    fps: float = 0.0
    # Mean luma per frame in 0..255.
    luma: np.ndarray = field(default_factory=lambda: np.zeros(0))
    # Mean absolute difference to the previous frame, normalised to 0..1.
    motion: np.ndarray = field(default_factory=lambda: np.zeros(0))
    # Hamming distance between consecutive pHashes (0 = visually identical).
    hash_delta: np.ndarray = field(default_factory=lambda: np.zeros(0))
    # Raw pHashes, one uint64 per frame.
    hashes: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.uint64))

    def timestamps(self, start: float = 0.0) -> np.ndarray:
        """Frame start times in seconds, assuming a constant rate."""
        if self.count == 0 or self.fps <= 0:
            return np.zeros(0)
        return start + np.arange(self.count) / self.fps

    def frames_to_ms(self, frames: int) -> float:
        """Convert a frame count into milliseconds at this clip's rate."""
        if self.fps <= 0:
            return 0.0
        return frames / self.fps * 1000.0


def _ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise DecodeError("ffmpeg not found on PATH (install ffmpeg)")
    return executable


def _dct_matrix(size: int) -> np.ndarray:
    """DCT-II basis matrix, so a 2D DCT is two matrix products."""
    n = np.arange(size).reshape(1, -1)
    k = np.arange(size).reshape(-1, 1)
    return np.cos(np.pi * k * (2 * n + 1) / (2 * size))


_DCT = _dct_matrix(THUMB)


def _phash_batch(thumbs: np.ndarray) -> np.ndarray:
    """64-bit perceptual hash for each 32x32 thumbnail in ``thumbs``.

    Classic pHash: 2D DCT, keep the low-frequency 8x8 block, threshold each
    coefficient against the median of that block (DC excluded). Because only
    the sign pattern survives, the hash is insensitive to global brightness and
    contrast, which is what a frozen-frame detector needs.
    """
    coeffs = _DCT @ thumbs @ _DCT.T  # (N, 32, 32)
    low = coeffs[:, :HASH_SIZE, :HASH_SIZE].reshape(len(thumbs), -1)
    # Drop DC before taking the median: it dominates every other coefficient.
    medians = np.median(low[:, 1:], axis=1, keepdims=True)
    bits = low > medians
    weights = np.uint64(1) << np.arange(63, -1, -1).astype(np.uint64)
    return (bits.astype(np.uint64) * weights).sum(axis=1)


def _popcount(values: np.ndarray) -> np.ndarray:
    """Population count for uint64 arrays (no numpy 2.0 dependency)."""
    out = np.zeros(values.shape, dtype=np.uint8)
    v = values.copy()
    for _ in range(64):
        out += (v & np.uint64(1)).astype(np.uint8)
        v >>= np.uint64(1)
    return out


def _hamming(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return _popcount(np.bitwise_xor(a, b))


def decode(path: Path, fps: float, max_frames: int | None = None) -> FrameMetrics:
    """Decode ``path`` and return per-frame metrics.

    ``fps`` is the probed rate; it is only used for time conversion, ffmpeg
    keeps the native rate so that duplicate and frozen frames stay visible.
    """
    ffmpeg = _ffmpeg()
    frame_bytes = THUMB * THUMB
    cmd = [
        ffmpeg,
        "-v",
        "error",
        "-i",
        str(path),
        "-an",
        "-sn",
        "-dn",
        # Square thumbnail, no padding: aspect distortion is harmless here
        # because every frame gets the same treatment.
        "-vf",
        f"scale={THUMB}:{THUMB}:flags=area,format=gray",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    thumbs: list[np.ndarray] = []
    try:
        while True:
            if max_frames is not None and len(thumbs) >= max_frames:
                break
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            thumbs.append(np.frombuffer(buf, dtype=np.uint8).reshape(THUMB, THUMB))
    finally:
        proc.stdout.close()
        stderr = proc.stderr.read()
        proc.stderr.close()
        proc.wait()

    if proc.returncode != 0 and not thumbs:
        message = stderr.decode("utf-8", "replace").strip()
        raise DecodeError(message or f"ffmpeg failed to decode {path}")
    if not thumbs:
        raise DecodeError(f"no frames decoded from {path}")

    stack = np.stack(thumbs).astype(np.float32)
    luma = stack.mean(axis=(1, 2))
    if len(stack) > 1:
        motion = np.abs(np.diff(stack, axis=0)).mean(axis=(1, 2)) / 255.0
    else:
        motion = np.zeros(0, dtype=np.float32)
    hashes = _phash_batch(stack)
    if len(hashes) > 1:
        hash_delta = _hamming(hashes[1:], hashes[:-1])
    else:
        hash_delta = np.zeros(0, dtype=np.uint8)

    return FrameMetrics(
        count=len(stack),
        fps=fps,
        luma=luma,
        motion=motion,
        hash_delta=hash_delta,
        hashes=hashes,
    )
