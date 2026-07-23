"""Tests for continuous presence tracking and the polling loop."""

import threading

import numpy as np
import pytest
from numpy.typing import NDArray

from reachy_buddy.vision.presence import PresenceLoop, PresenceTracker


def _make_face(x0: float, y0: float, x1: float, y1: float) -> NDArray[np.float64]:
    return np.array([[x0, y0, 0.0], [x1, y0, 0.0], [x1, y1, 0.0], [x0, y1, 0.0]])


class _ScriptedDetector:
    """Landmark detector returning scripted results, one entry per detect() call."""

    def __init__(self, script: list[list[NDArray[np.float64]]]) -> None:
        """Initialize with the per-call results; the last entry repeats when exhausted."""
        self._script = script
        self.calls = 0

    def detect(self, frame_bgr: NDArray[np.uint8]) -> list[NDArray[np.float64]]:
        """Return the next scripted result."""
        result = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        return result


_FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


def test_presence_detects_primary_face() -> None:
    """The largest face becomes the tracked primary."""
    tracker = PresenceTracker(_ScriptedDetector([[_make_face(0.1, 0.1, 0.2, 0.2), _make_face(0.4, 0.3, 0.8, 0.7)]]))
    primary = tracker.observe(_FRAME, now=1.0)
    assert tracker.present
    assert tracker.face_count == 2
    assert primary is not None
    assert primary.center == (pytest.approx(0.6), 0.5)
    assert primary.size == pytest.approx(0.4)


def test_presence_survives_brief_detection_gaps() -> None:
    """A face lost for less than the debounce window still counts as present."""
    tracker = PresenceTracker(_ScriptedDetector([[_make_face(0.4, 0.3, 0.8, 0.7)], []]), lost_after_seconds=0.8)
    tracker.observe(_FRAME, now=1.0)
    primary = tracker.observe(_FRAME, now=1.7)
    assert tracker.present
    assert primary is not None


def test_presence_lapses_after_debounce_window() -> None:
    """After the debounce window without a detection, presence is gone."""
    tracker = PresenceTracker(_ScriptedDetector([[_make_face(0.4, 0.3, 0.8, 0.7)], []]), lost_after_seconds=0.8)
    tracker.observe(_FRAME, now=1.0)
    assert tracker.observe(_FRAME, now=1.9) is None
    assert not tracker.present
    assert tracker.face_count == 0


def test_presence_recovers_when_face_returns() -> None:
    """A returning face is tracked again after a lapse."""
    face = _make_face(0.4, 0.3, 0.8, 0.7)
    tracker = PresenceTracker(_ScriptedDetector([[face], [], [face]]), lost_after_seconds=0.5)
    tracker.observe(_FRAME, now=1.0)
    tracker.observe(_FRAME, now=2.0)
    assert not tracker.present
    assert tracker.observe(_FRAME, now=2.1) is not None
    assert tracker.present


def test_presence_loop_reports_arrival_and_stop() -> None:
    """The polling thread reports the presence edge and stops cleanly."""
    arrived = threading.Event()
    changes: list[bool] = []

    def on_change(present: bool) -> None:
        changes.append(present)
        arrived.set()

    loop = PresenceLoop(
        PresenceTracker(_ScriptedDetector([[_make_face(0.4, 0.3, 0.8, 0.7)]])),
        frame_source=lambda: _FRAME,
        frames_per_second=100.0,
        on_presence_change=on_change,
    )
    loop.start()
    assert arrived.wait(timeout=2.0)
    loop.stop()
    assert changes == [True]
