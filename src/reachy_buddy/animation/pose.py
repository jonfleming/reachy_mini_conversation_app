"""Body pose value type and easing helpers for the animation layer."""

from dataclasses import dataclass


def smoothstep(t: float) -> float:
    """Ease a 0..1 progress value with zero slope at both ends."""
    x = min(1.0, max(0.0, t))
    return x * x * (3.0 - 2.0 * x)


@dataclass(frozen=True)
class BodyPose:
    """Head yaw/pitch/roll in degrees plus left/right antenna angles in radians."""

    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    antenna_left: float = -0.1745
    antenna_right: float = 0.1745

    def lerp(self, other: "BodyPose", t: float) -> "BodyPose":
        """Interpolate component-wise toward another pose by t in 0..1."""
        x = min(1.0, max(0.0, t))
        return BodyPose(
            yaw=self.yaw + (other.yaw - self.yaw) * x,
            pitch=self.pitch + (other.pitch - self.pitch) * x,
            roll=self.roll + (other.roll - self.roll) * x,
            antenna_left=self.antenna_left + (other.antenna_left - self.antenna_left) * x,
            antenna_right=self.antenna_right + (other.antenna_right - self.antenna_right) * x,
        )

    def __add__(self, other: "BodyPose") -> "BodyPose":
        """Add two poses component-wise (a base pose plus an offset pose)."""
        return BodyPose(
            yaw=self.yaw + other.yaw,
            pitch=self.pitch + other.pitch,
            roll=self.roll + other.roll,
            antenna_left=self.antenna_left + other.antenna_left,
            antenna_right=self.antenna_right + other.antenna_right,
        )
