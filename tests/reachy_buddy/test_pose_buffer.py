"""Tests for the pose buffer idle fill that never commands the robot directly."""

from unittest.mock import MagicMock

from reachy_buddy.animation.pose import BodyPose
from reachy_buddy.animation.pose_buffer import PoseBuffer, BuddyIdleMove, PoseBufferSink


def test_pose_buffer_sink_does_not_touch_the_robot() -> None:
    """The live sink writes a buffer; hardware is owned by MovementManager."""
    robot = MagicMock()
    buffer = PoseBuffer()
    sink = PoseBufferSink(buffer)

    sink.apply(BodyPose(yaw=12.0, pitch=-3.0), 0.1)

    assert buffer.get().yaw == 12.0
    robot.goto_target.assert_not_called()
    robot.set_target.assert_not_called()


def test_buddy_idle_move_samples_the_buffer() -> None:
    """The infinite idle move evaluates to the latest buffered pose."""
    buffer = PoseBuffer()
    buffer.set(BodyPose(yaw=20.0, pitch=5.0, antenna_left=0.1, antenna_right=-0.1))
    move = BuddyIdleMove(buffer)

    assert move.duration == float("inf")
    assert move.is_idle_fill is True
    head, antennas, body_yaw = move.evaluate(0.0)
    assert body_yaw == 0.0
    assert antennas[0] == 0.1
    assert antennas[1] == -0.1
    assert head is not None
