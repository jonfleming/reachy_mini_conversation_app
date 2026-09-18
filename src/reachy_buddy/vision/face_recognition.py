"""Face recognition: enroll and identify people with the face_recognition library."""

import logging
from pathlib import Path

import numpy as np
from numpy.typing import NDArray


logger = logging.getLogger(__name__)

try:
    import face_recognition
except ImportError:
    face_recognition = None

UNKNOWN_LABEL = "unknown"
DEFAULT_FACES_PATH = Path.home() / ".reachy_buddy" / "faces.npz"


class FaceRecognizer:
    """Matches faces in RGB frames against enrolled encodings, persisted on disk."""

    def __init__(self, tolerance: float = 0.6, store_path: Path | None = None) -> None:
        """Initialize with match tolerance and an optional encodings file."""
        self.tolerance = tolerance
        self.store_path = store_path or DEFAULT_FACES_PATH
        self._encodings: list[NDArray[np.float64]] = []
        self._labels: list[str] = []
        self.load()

    @property
    def available(self) -> bool:
        """Whether the face_recognition library is importable."""
        return face_recognition is not None

    def enroll(
        self,
        name: str,
        frame_rgb: NDArray[np.uint8],
        locations: list[tuple[int, int, int, int]] | None = None,
    ) -> bool:
        """Enroll the first face found in the frame; return False when none is found."""
        if face_recognition is None:
            logger.warning("Cannot enroll %s: face_recognition is not installed", name)
            return False
        boxes = self._face_locations(frame_rgb, locations)
        if not boxes:
            logger.warning("Cannot enroll %s: no face in frame", name)
            return False
        encodings = face_recognition.face_encodings(frame_rgb, known_face_locations=boxes)
        if not encodings:
            logger.warning("Cannot enroll %s: encoding failed for %d box(es)", name, len(boxes))
            return False
        self._encodings.append(np.asarray(encodings[0], dtype=np.float64))
        self._labels.append(name)
        self.save()
        logger.info("Enrolled %s (%d known faces)", name, len(self._labels))
        return True

    def identify(
        self,
        frame_rgb: NDArray[np.uint8],
        locations: list[tuple[int, int, int, int]] | None = None,
    ) -> list[str]:
        """Return one label per face in the frame ('unknown' when unmatched)."""
        if face_recognition is None or not self._encodings:
            return []
        boxes = self._face_locations(frame_rgb, locations)
        if not boxes:
            return []
        labels: list[str] = []
        for encoding in face_recognition.face_encodings(frame_rgb, known_face_locations=boxes):
            matches = face_recognition.compare_faces(self._encodings, encoding, tolerance=self.tolerance)
            labels.append(self._labels[matches.index(True)] if any(matches) else UNKNOWN_LABEL)
        return labels

    def _face_locations(
        self,
        frame_rgb: NDArray[np.uint8],
        locations: list[tuple[int, int, int, int]] | None,
    ) -> list[tuple[int, int, int, int]]:
        if face_recognition is None:
            return []
        if locations:
            return locations
        found = face_recognition.face_locations(frame_rgb, number_of_times_to_upsample=1)
        boxes = found or face_recognition.face_locations(frame_rgb, number_of_times_to_upsample=2)
        return [(int(top), int(right), int(bottom), int(left)) for top, right, bottom, left in boxes]

    def save(self) -> None:
        """Write encodings and labels to store_path."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._encodings:
            return
        np.savez(
            self.store_path,
            encodings=np.stack(self._encodings),
            labels=np.array(self._labels),
        )

    def load(self) -> None:
        """Load encodings from store_path when the file exists."""
        if not self.store_path.is_file():
            return
        try:
            payload = np.load(self.store_path, allow_pickle=True)
            encodings = payload["encodings"]
            labels = payload["labels"]
        except (OSError, KeyError, ValueError) as exc:
            logger.warning("Failed to load face encodings from %s: %s", self.store_path, exc)
            return
        self._encodings = [np.asarray(row, dtype=np.float64) for row in encodings]
        self._labels = [str(label) for label in labels]
        logger.info("Loaded %d enrolled faces from %s", len(self._labels), self.store_path)
