"""Object detection through OpenCV DNN; inactive until ONNX model files are configured."""

import logging
from pathlib import Path
from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray


logger = logging.getLogger(__name__)

_INPUT_SIZE = 640
_CONFIDENCE_THRESHOLD = 0.5
_NMS_THRESHOLD = 0.4


@dataclass(frozen=True)
class Detection:
    """One detected object: label, confidence, and pixel-space (x, y, width, height) box."""

    label: str
    confidence: float
    box: tuple[int, int, int, int]


class ObjectDetector:
    """Runs a YOLO-style ONNX model through cv2.dnn when weights are provided."""

    def __init__(self, onnx_path: Path | None = None, labels_path: Path | None = None) -> None:
        """Load the model and labels; without both paths the detector stays disabled."""
        self._net: cv2.dnn.Net | None = None
        self._labels: list[str] = []
        if onnx_path is not None and labels_path is not None:
            self._net = cv2.dnn.readNetFromONNX(str(onnx_path))
            self._labels = labels_path.read_text(encoding="utf-8").splitlines()
            logger.info("Object detector loaded %s (%d labels)", onnx_path.name, len(self._labels))
        else:
            logger.info("Object detector disabled: no model configured")

    @property
    def enabled(self) -> bool:
        """Whether a model is loaded and detect() can produce results."""
        return self._net is not None

    def detect(self, frame_bgr: NDArray[np.uint8]) -> list[Detection]:
        """Return detections for the frame; empty while no model is configured."""
        if self._net is None:
            return []
        blob = cv2.dnn.blobFromImage(frame_bgr, scalefactor=1 / 255.0, size=(_INPUT_SIZE, _INPUT_SIZE), swapRB=True)
        self._net.setInput(blob)
        outputs = np.asarray(self._net.forward(), dtype=np.float32)
        return self._decode(outputs, frame_bgr.shape[1], frame_bgr.shape[0])

    def _decode(self, outputs: NDArray[np.float32], frame_width: int, frame_height: int) -> list[Detection]:
        scale_x = frame_width / _INPUT_SIZE
        scale_y = frame_height / _INPUT_SIZE
        boxes: list[list[int]] = []
        scores: list[float] = []
        class_ids: list[int] = []
        for row in outputs[0].T:
            class_scores = row[4:]
            class_id = int(np.argmax(class_scores))
            confidence = float(class_scores[class_id])
            if confidence < _CONFIDENCE_THRESHOLD:
                continue
            center_x, center_y, width, height = row[:4]
            boxes.append(
                [
                    int((center_x - width / 2) * scale_x),
                    int((center_y - height / 2) * scale_y),
                    int(width * scale_x),
                    int(height * scale_y),
                ]
            )
            scores.append(confidence)
            class_ids.append(class_id)
        detections: list[Detection] = []
        for index in cv2.dnn.NMSBoxes(boxes, scores, _CONFIDENCE_THRESHOLD, _NMS_THRESHOLD):
            i = int(index)
            label = self._labels[class_ids[i]] if class_ids[i] < len(self._labels) else str(class_ids[i])
            x, y, width, height = boxes[i]
            detections.append(Detection(label, scores[i], (x, y, width, height)))
        return detections
