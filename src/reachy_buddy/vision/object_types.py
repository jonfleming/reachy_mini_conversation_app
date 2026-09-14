"""Detected-object value type, independent of OpenCV."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    """One detected object: label, confidence, and pixel-space (x, y, width, height) box."""

    label: str
    confidence: float
    box: tuple[int, int, int, int]
