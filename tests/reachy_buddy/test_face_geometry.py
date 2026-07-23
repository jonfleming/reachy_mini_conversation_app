"""Tests for the face-landmark geometry helpers."""

import numpy as np
import pytest
from numpy.typing import NDArray

from reachy_buddy.vision.face_tracking import face_size, face_center


def _landmarks(xs: tuple[float, float], ys: tuple[float, float]) -> NDArray[np.float64]:
    return np.array(
        [
            [xs[0], ys[0], 0.0],
            [xs[1], ys[0], 0.0],
            [xs[1], ys[1], 0.0],
            [xs[0], ys[1], 0.0],
        ]
    )


def test_face_center_is_bounding_box_center() -> None:
    """Center is the midpoint of the landmark bounding box."""
    center = face_center(_landmarks((0.2, 0.6), (0.3, 0.7)))
    assert center == (pytest.approx(0.4), 0.5)


def test_face_size_is_bounding_box_width() -> None:
    """Size is the normalized bounding-box width."""
    assert face_size(_landmarks((0.2, 0.6), (0.3, 0.7))) == pytest.approx(0.4)


def test_face_center_handles_unordered_landmarks() -> None:
    """Center does not depend on landmark ordering."""
    landmarks = _landmarks((0.1, 0.9), (0.2, 0.4))
    assert face_center(landmarks[::-1]) == (0.5, pytest.approx(0.3))
