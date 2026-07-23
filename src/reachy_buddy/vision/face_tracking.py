"""Face tracking via the MediaPipe Face Landmarker task (Face Mesh landmarks)."""

import logging
from pathlib import Path

import cv2
import httpx
import numpy as np
import mediapipe as mp
from numpy.typing import NDArray
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision


logger = logging.getLogger(__name__)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
MODEL_FILENAME = "face_landmarker.task"


def default_models_dir() -> Path:
    """Return the per-user directory holding downloaded MediaPipe models."""
    return Path.home() / ".reachy_buddy" / "models"


def ensure_face_landmarker_model(models_dir: Path | None = None) -> Path:
    """Return the Face Landmarker model path, downloading it on first use."""
    models_dir = models_dir or default_models_dir()
    model_path = models_dir / MODEL_FILENAME
    if model_path.exists():
        return model_path
    models_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading Face Landmarker model to %s", model_path)
    with httpx.stream("GET", MODEL_URL, follow_redirects=True, timeout=120.0) as response:
        response.raise_for_status()
        with model_path.open("wb") as model_file:
            for chunk in response.iter_bytes():
                model_file.write(chunk)
    return model_path


def face_center(landmarks: NDArray[np.float64]) -> tuple[float, float]:
    """Return the bounding-box center of a face landmark array in normalized (x, y)."""
    return float((landmarks[:, 0].min() + landmarks[:, 0].max()) / 2), float(
        (landmarks[:, 1].min() + landmarks[:, 1].max()) / 2
    )


def face_size(landmarks: NDArray[np.float64]) -> float:
    """Return the bounding-box width of a face in normalized units; a rough distance proxy."""
    return float(landmarks[:, 0].max() - landmarks[:, 0].min())


class FaceTracker:
    """Detects faces in BGR frames and returns per-face landmark arrays."""

    def __init__(self, model_path: Path, max_faces: int = 4, min_confidence: float = 0.5) -> None:
        """Initialize the Face Landmarker from a local .task model file."""
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=max_faces,
            min_face_detection_confidence=min_confidence,
            min_tracking_confidence=min_confidence,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def detect(self, frame_bgr: NDArray[np.uint8]) -> list[NDArray[np.float64]]:
        """Return one Nx3 landmark array (normalized image coordinates) per detected face."""
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        result = self._landmarker.detect(image)
        return [np.array([[lm.x, lm.y, lm.z] for lm in landmarks]) for landmarks in result.face_landmarks]

    def close(self) -> None:
        """Release MediaPipe resources."""
        self._landmarker.close()
