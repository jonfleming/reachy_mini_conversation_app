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
