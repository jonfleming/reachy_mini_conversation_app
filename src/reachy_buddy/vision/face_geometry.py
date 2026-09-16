"""Normalized face-landmark geometry helpers (no MediaPipe import)."""

import numpy as np
from numpy.typing import NDArray


def face_center(landmarks: NDArray[np.float64]) -> tuple[float, float]:
    """Return the bounding-box center of a face landmark array in normalized (x, y)."""
    return float((landmarks[:, 0].min() + landmarks[:, 0].max()) / 2), float(
        (landmarks[:, 1].min() + landmarks[:, 1].max()) / 2
    )


def face_size(landmarks: NDArray[np.float64]) -> float:
    """Return the bounding-box width of a face in normalized units; a rough distance proxy."""
    return float(landmarks[:, 0].max() - landmarks[:, 0].min())


def face_pixel_box(
    landmarks: NDArray[np.float64],
    width: int,
    height: int,
    *,
    pad: float = 0.4,
) -> tuple[int, int, int, int]:
    """Return a dlib-style (top, right, bottom, left) box in pixels, padded around the mesh."""
    x0 = float(landmarks[:, 0].min())
    x1 = float(landmarks[:, 0].max())
    y0 = float(landmarks[:, 1].min())
    y1 = float(landmarks[:, 1].max())
    box_width = x1 - x0
    box_height = y1 - y0
    x0 -= box_width * pad
    x1 += box_width * pad
    y0 -= box_height * pad
    y1 += box_height * pad
    left = max(0, int(x0 * width))
    right = min(width, int(x1 * width))
    top = max(0, int(y0 * height))
    bottom = min(height, int(y1 * height))
    if right <= left:
        right = min(width, left + 1)
    if bottom <= top:
        bottom = min(height, top + 1)
    return top, right, bottom, left
