"""Gesture programs: named keyframe tracks evaluated over time."""

from dataclasses import dataclass

from reachy_buddy.animation.pose import BodyPose, smoothstep


@dataclass(frozen=True)
class PoseKeyframe:
    """A pose reached `duration` seconds after the previous keyframe begins."""

    pose: BodyPose
    duration: float


class GestureProgram:
    """Evaluates a fixed keyframe track from neutral, easing between keyframes."""

    def __init__(self, name: str, keyframes: list[PoseKeyframe]) -> None:
        """Store the gesture name and its keyframe track."""
        if not keyframes:
            raise ValueError("a gesture needs at least one keyframe")
        self._name = name
        self._keyframes = keyframes
        self._duration = sum(key.duration for key in keyframes)

    @property
    def name(self) -> str:
        """Return the gesture's name."""
        return self._name

    @property
    def duration(self) -> float:
        """Return the total track length in seconds."""
        return self._duration

    def evaluate(self, t: float) -> BodyPose:
        """Return the pose at t seconds into the gesture, clamped to the track."""
        if t <= 0.0:
            return BodyPose()
        remaining = t
        previous = BodyPose()
        for key in self._keyframes:
            if remaining <= key.duration:
                return previous.lerp(key.pose, smoothstep(remaining / key.duration))
            remaining -= key.duration
            previous = key.pose
        return self._keyframes[-1].pose
