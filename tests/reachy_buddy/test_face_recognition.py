"""Tests for persisted face encodings without calling the native recognizer."""

from pathlib import Path

import numpy as np

from reachy_buddy.vision.face_recognition import FaceRecognizer


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """Encodings written to disk reload with the same labels."""
    path = tmp_path / "faces.npz"
    recognizer = FaceRecognizer(store_path=path)
    recognizer._encodings = [np.arange(128, dtype=np.float64)]
    recognizer._labels = ["Jon"]
    recognizer.save()

    loaded = FaceRecognizer(store_path=path)
    assert loaded._labels == ["Jon"]
    assert loaded._encodings[0].shape == (128,)
    np.testing.assert_array_equal(loaded._encodings[0], recognizer._encodings[0])


def test_identify_without_enrollments_returns_empty(tmp_path: Path) -> None:
    """An empty store does not invent identities."""
    recognizer = FaceRecognizer(store_path=tmp_path / "missing.npz")
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    assert recognizer.identify(frame) == []
