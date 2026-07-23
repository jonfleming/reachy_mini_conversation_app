"""Face recognition: enroll and identify people with the face_recognition library."""

import logging

import numpy as np
import face_recognition
from numpy.typing import NDArray


logger = logging.getLogger(__name__)

UNKNOWN_LABEL = "unknown"


class FaceRecognizer:
    """Matches faces in RGB frames against enrolled encodings."""

    def __init__(self, tolerance: float = 0.6) -> None:
        """Initialize with the distance tolerance for a match (lower is stricter)."""
        self.tolerance = tolerance
        self._encodings: list[NDArray[np.float64]] = []
        self._labels: list[str] = []

    def enroll(self, name: str, frame_rgb: NDArray[np.uint8]) -> bool:
        """Enroll the first face found in the frame; return False when none is found."""
        encodings = face_recognition.face_encodings(frame_rgb)
        if not encodings:
            logger.warning("Cannot enroll %s: no face in frame", name)
            return False
        self._encodings.append(encodings[0])
        self._labels.append(name)
        logger.info("Enrolled %s (%d known faces)", name, len(self._labels))
        return True

    def identify(self, frame_rgb: NDArray[np.uint8]) -> list[str]:
        """Return one label per face in the frame ('unknown' when unmatched)."""
        labels: list[str] = []
        for encoding in face_recognition.face_encodings(frame_rgb):
            matches = face_recognition.compare_faces(self._encodings, encoding, tolerance=self.tolerance)
            labels.append(self._labels[matches.index(True)] if any(matches) else UNKNOWN_LABEL)
        return labels
