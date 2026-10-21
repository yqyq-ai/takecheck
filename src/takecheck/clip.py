"""Per-clip analysis: decode once, derive the signals every frame check needs."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .frames import FrameMetrics, decode
from .probe import VideoInfo


@dataclass
class Clip:
    """A decoded clip plus the derived arrays the checks read."""

    metrics: FrameMetrics
    info: VideoInfo

    @property
    def fps(self) -> float:
        """Frame rate, falling back to ffprobe's value and then 24."""
        return self.metrics.fps or self.info.fps or 24.0

    @property
    def count(self) -> int:
        """Number of decoded frames."""
        return self.metrics.count

    def times(self) -> np.ndarray:
        """Start time of every frame, in seconds."""
        return self.metrics.timestamps()

    def ms(self, frames: float) -> float:
        """Frames -> milliseconds at this clip's rate."""
        if self.fps <= 0:
            return 0.0
        return frames / self.fps * 1000.0

    def ms_to_frames(self, milliseconds: float) -> float:
        """Milliseconds -> frames at this clip's rate."""
        return milliseconds / 1000.0 * self.fps


def analyse(info: VideoInfo) -> Clip:
    """Decode ``info.path`` and wrap it in a :class:`Clip`."""
    return Clip(metrics=decode(info.path, info.fps), info=info)
