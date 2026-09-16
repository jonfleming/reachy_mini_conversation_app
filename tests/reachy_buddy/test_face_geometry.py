"""Tests for the face-landmark geometry helpers."""

import numpy as np
import pytest
from numpy.typing import NDArray

from reachy_buddy.vision.face_geometry import face_size, face_center, face_pixel_box


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


def test_face_pixel_box_is_padded_dlib_order() -> None:
    """Pixel boxes are (top, right, bottom, left) and padded around the mesh."""
    box = face_pixel_box(_landmarks((0.2, 0.6), (0.3, 0.7)), width=100, height=100, pad=0.0)
    assert box == (30, 60, 70, 20)
