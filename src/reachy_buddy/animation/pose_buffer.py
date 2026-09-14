"""Thread-safe latest pose for MovementManager idle fill; never talks to hardware."""

import threading

import numpy as np
from numpy.typing import NDArray

from reachy_mini.utils import create_head_pose
from reachy_mini.motion.move import Move
from reachy_buddy.animation.pose import BodyPose


class PoseBuffer:
    """Holds the most recent buddy pose for the movement loop to sample."""

    def __init__(self) -> None:
        """Initialize at a neutral pose."""
        self._lock = threading.Lock()
        self._pose = BodyPose()

    def set(self, pose: BodyPose) -> None:
        """Replace the latest pose."""
        with self._lock:
            self._pose = pose

    def get(self) -> BodyPose:
        """Return the latest pose."""
        with self._lock:
            return self._pose


class PoseBufferSink:
    """PoseSink that writes into a PoseBuffer instead of commanding the robot."""

    def __init__(self, buffer: PoseBuffer) -> None:
        """Initialize with the shared buffer."""
        self._buffer = buffer

    def apply(self, pose: BodyPose, duration: float) -> None:
        """Store the pose; duration is unused because MovementManager owns timing."""
        self._buffer.set(pose)


class BuddyIdleMove(Move):  # type: ignore[misc]
    """Infinite idle fill that samples a PoseBuffer each control-loop tick."""

    is_idle_fill = True

    def __init__(self, buffer: PoseBuffer) -> None:
        """Initialize with the buffer written by the buddy session."""
        self._buffer = buffer

    @property
    def duration(self) -> float:
        """Stay on the queue until a primary move replaces this fill."""
        return float("inf")

    def evaluate(self, t: float) -> tuple[NDArray[np.float64], NDArray[np.float64], float]:
        """Return the latest buffered pose as a Move sample."""
        pose = self._buffer.get()
        head = create_head_pose(pitch=pose.pitch, yaw=pose.yaw, roll=pose.roll, z=0.0, degrees=True)
        antennas = np.array([pose.antenna_left, pose.antenna_right], dtype=np.float64)
        return head, antennas, 0.0
