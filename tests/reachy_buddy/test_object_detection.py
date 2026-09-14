"""Tests for object detector configuration."""

import numpy as np

from reachy_buddy.vision.object_detection import ObjectDetector


def test_detector_is_disabled_without_model_files() -> None:
    """With no ONNX paths, detect() is a no-op rather than a crash."""
    detector = ObjectDetector()
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    assert detector.enabled is False
    assert detector.detect(frame) == []
