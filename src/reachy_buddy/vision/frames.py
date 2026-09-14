"""Grab a BGR camera frame from the Reachy Mini media API."""

import logging

import cv2
import numpy as np
from numpy.typing import NDArray

from reachy_mini import ReachyMini


logger = logging.getLogger(__name__)


def grab_bgr_frame(robot: ReachyMini) -> NDArray[np.uint8] | None:
    """Return one BGR frame, or None when the camera has nothing ready."""
    media = robot.media
    get_frame = getattr(media, "get_frame", None)
    if callable(get_frame):
        try:
            frame = get_frame()
        except Exception as exc:
            logger.debug("get_frame failed: %s", exc)
            frame = None
        if isinstance(frame, np.ndarray) and frame.ndim == 3:
            return frame
    get_jpeg = getattr(media, "get_frame_jpeg", None)
    if not callable(get_jpeg):
        return None
    try:
        jpeg_bytes = get_jpeg()
    except Exception as exc:
        logger.debug("get_frame_jpeg failed: %s", exc)
        return None
    if not jpeg_bytes:
        return None
    decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        return None
    return np.asarray(decoded, dtype=np.uint8)
