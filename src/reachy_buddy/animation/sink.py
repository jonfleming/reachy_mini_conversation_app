"""Pose sinks: where the planner sends its computed body poses."""

from typing import Protocol

from reachy_buddy.animation.pose import BodyPose
from reachy_buddy.animation.pose_buffer import PoseBuffer, PoseBufferSink


class PoseSink(Protocol):
    """Consumer of planner-computed body poses (hardware or test double)."""

    def apply(self, pose: BodyPose, duration: float) -> None:
        """Move toward the pose, reaching it in about `duration` seconds."""
        ...


# Live motion goes through MovementManager via PoseBufferSink; do not goto_target here.
MovementPoseSink = PoseBufferSink

__all__ = ["PoseSink", "PoseBuffer", "PoseBufferSink", "MovementPoseSink"]
