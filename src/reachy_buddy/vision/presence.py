"""Continuous face presence: debounced primary-face tracking over a frame stream."""

import time
import logging
import threading
from typing import Protocol
from dataclasses import dataclass
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from reachy_buddy.vision.face_tracking import face_size, face_center


logger = logging.getLogger(__name__)

FrameSource = Callable[[], NDArray[np.uint8] | None]


@dataclass(frozen=True)
class TrackedFace:
    """The primary face in view: normalized center, bbox-width size, and last sighting time."""

    center: tuple[float, float]
    size: float
    last_seen: float


class LandmarkDetector(Protocol):
    """Anything that returns per-face Nx3 landmark arrays for a BGR frame."""

    def detect(self, frame_bgr: NDArray[np.uint8]) -> list[NDArray[np.float64]]:
        """Return one landmark array per detected face."""
        ...


class PresenceTracker:
    """Tracks the primary face across frames with a short lost-detection tolerance."""

    def __init__(self, detector: LandmarkDetector, lost_after_seconds: float = 0.8) -> None:
        """Initialize with the landmark detector and the debounce window for lost faces."""
        self._detector = detector
        self.lost_after_seconds = lost_after_seconds
        self._primary: TrackedFace | None = None
        self._face_count = 0

    def observe(self, frame_bgr: NDArray[np.uint8], now: float | None = None) -> TrackedFace | None:
        """Detect faces in one frame and return the debounced primary face, if any."""
        now = time.monotonic() if now is None else now
        faces = self._detector.detect(frame_bgr)
        if faces:
            landmarks = max(faces, key=face_size)
            self._primary = TrackedFace(face_center(landmarks), face_size(landmarks), now)
            self._face_count = len(faces)
        elif self._primary is not None and now - self._primary.last_seen >= self.lost_after_seconds:
            logger.debug("Presence lost after %.1fs without detection", now - self._primary.last_seen)
            self._primary = None
            self._face_count = 0
        return self._primary

    @property
    def present(self) -> bool:
        """Whether a face is currently tracked, including the debounce window."""
        return self._primary is not None

    @property
    def face_count(self) -> int:
        """Number of faces in the latest detection that found any."""
        return self._face_count


class PresenceLoop:
    """Background thread polling a frame source into a PresenceTracker at a fixed rate."""

    def __init__(
        self,
        tracker: PresenceTracker,
        frame_source: FrameSource,
        frames_per_second: float = 5.0,
        on_presence_change: Callable[[bool], None] | None = None,
    ) -> None:
        """Initialize with the tracker, frame source, poll rate, and presence-edge callback."""
        self._tracker = tracker
        self._frame_source = frame_source
        self._on_presence_change = on_presence_change
        self._interval = 1.0 / frames_per_second
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="reachy-buddy-presence", daemon=True)

    @property
    def tracker(self) -> PresenceTracker:
        """Return the tracker holding the latest debounced presence state."""
        return self._tracker

    def start(self) -> None:
        """Start the polling thread."""
        self._thread.start()

    def stop(self) -> None:
        """Signal the polling thread to stop and wait for it to exit."""
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        present = self._tracker.present
        while not self._stop.is_set():
            frame = self._frame_source()
            if frame is not None:
                self._tracker.observe(frame)
                if self._tracker.present != present:
                    present = self._tracker.present
                    logger.info("Presence changed: %s", "arrived" if present else "left")
                    if self._on_presence_change is not None:
                        self._on_presence_change(present)
            self._stop.wait(self._interval)
