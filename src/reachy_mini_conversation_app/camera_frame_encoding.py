"""Helpers for encoding camera frames."""

import logging
import tempfile
from pathlib import Path
from fractions import Fraction

import av
import numpy as np
from numpy.typing import NDArray

from .config import _env_flag


logger = logging.getLogger(__name__)

# When set, deliberate snapshots are also written to TMPDIR for inspection.
DEBUG_SNAPSHOT_ENV = "REACHY_MINI_DEBUG_SNAPSHOTS"


def save_debug_snapshot(frame: NDArray[np.uint8], label: str) -> bytes:
    """Encode a deliberate camera snapshot and return the JPEG.

    When the ``REACHY_MINI_DEBUG_SNAPSHOTS`` env flag is set, also write a copy
    to TMPDIR for inspection. Use at intentional capture points (camera tool,
    rmscript picture) — not the continuous video loop, which would write a file
    every frame.
    """
    jpeg = encode_bgr_frame_as_jpeg(frame)
    if _env_flag(DEBUG_SNAPSHOT_ENV):
        path = Path(tempfile.gettempdir()) / f"reachy_camera_{label}.jpg"
        path.write_bytes(jpeg)
        logger.info("camera snapshot '%s' (%dx%d) saved to %s", label, frame.shape[1], frame.shape[0], path)
    return jpeg


def encode_bgr_frame_as_jpeg(frame: NDArray[np.uint8]) -> bytes:
    """Encode a BGR camera frame as JPEG bytes."""
    rgb_frame = np.ascontiguousarray(frame[..., ::-1])
    video_frame = av.VideoFrame.from_ndarray(rgb_frame, format="rgb24")

    codec = av.CodecContext.create("mjpeg", "w")
    codec.width = rgb_frame.shape[1]  # type: ignore[attr-defined]
    codec.height = rgb_frame.shape[0]  # type: ignore[attr-defined]
    codec.pix_fmt = "yuvj444p"  # type: ignore[attr-defined]
    codec.time_base = Fraction(1, 1)
    codec.options = {"qscale": "3"}

    packets = codec.encode(video_frame)  # type: ignore[attr-defined]
    packets += codec.encode(None)  # type: ignore[attr-defined]
    if not packets:
        raise RuntimeError("Failed to encode frame as JPEG")

    return b"".join(bytes(packet) for packet in packets)
