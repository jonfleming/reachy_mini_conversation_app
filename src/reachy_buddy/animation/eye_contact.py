"""Eye contact: maps face positions in the camera frame to head gaze angles."""


class EyeContactController:
    """Converts normalized face positions into yaw/pitch targets for the head."""

    def __init__(self, horizontal_fov_degrees: float = 70.0, vertical_fov_degrees: float = 50.0) -> None:
        """Initialize with the camera's field of view."""
        self.horizontal_fov_degrees = horizontal_fov_degrees
        self.vertical_fov_degrees = vertical_fov_degrees

    def gaze_angles(self, face_center: tuple[float, float]) -> tuple[float, float]:
        """Return (yaw, pitch) in degrees to center a normalized (x, y) face position."""
        x, y = face_center
        yaw = (x - 0.5) * self.horizontal_fov_degrees
        pitch = (0.5 - y) * self.vertical_fov_degrees
        return yaw, pitch
