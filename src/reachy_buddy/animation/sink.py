"""Pose sinks: where the planner sends its computed body poses."""

from typing import Protocol

from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose
from reachy_buddy.animation.pose import BodyPose


class PoseSink(Protocol):
    """Consumer of planner-computed body poses (hardware or test double)."""

    def apply(self, pose: BodyPose, duration: float) -> None:
        """Move toward the pose, reaching it in about `duration` seconds."""
        ...


class ReachyPoseSink:
    """Sends planner poses to a Reachy Mini as one goto_target per update."""

    def __init__(self, reachy: ReachyMini) -> None:
        """Initialize with the robot handle used for all motion commands."""
        self._reachy = reachy

    def apply(self, pose: BodyPose, duration: float) -> None:
        """Command head and antennas together via the SDK's min-jerk goto."""
        head = create_head_pose(pitch=pose.pitch, yaw=pose.yaw, roll=pose.roll, degrees=True)
        self._reachy.goto_target(head=head, antennas=[pose.antenna_left, pose.antenna_right], duration=duration)
