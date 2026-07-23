"""Tests for the BodyPose value type and gesture program evaluation."""

import pytest

from reachy_buddy.animation.pose import BodyPose, smoothstep
from reachy_buddy.animation.program import PoseKeyframe, GestureProgram


def test_smoothstep_endpoints_and_midpoint() -> None:
    """Easing is clamped and passes through 0, 0.5, and 1."""
    assert smoothstep(-1.0) == 0.0
    assert smoothstep(0.0) == 0.0
    assert smoothstep(0.5) == 0.5
    assert smoothstep(1.0) == 1.0
    assert smoothstep(2.0) == 1.0


def test_lerp_midpoint() -> None:
    """A halfway lerp averages every component."""
    low = BodyPose(yaw=-10.0, pitch=0.0, roll=4.0, antenna_left=-0.5, antenna_right=0.5)
    high = BodyPose(yaw=10.0, pitch=8.0, roll=-4.0, antenna_left=0.5, antenna_right=-0.5)
    mid = low.lerp(high, 0.5)
    assert mid.yaw == pytest.approx(0.0)
    assert mid.pitch == pytest.approx(4.0)
    assert mid.roll == pytest.approx(0.0)
    assert mid.antenna_left == pytest.approx(0.0)
    assert mid.antenna_right == pytest.approx(0.0)


def test_pose_add_combines_base_and_offset() -> None:
    """Base pose plus a micro-motion offset adds component-wise."""
    base = BodyPose(pitch=2.0, antenna_left=0.35, antenna_right=-0.35)
    offset = BodyPose(yaw=0.5, pitch=-0.3, roll=0.0, antenna_left=0.1, antenna_right=-0.1)
    combined = base + offset
    assert combined.yaw == pytest.approx(0.5)
    assert combined.pitch == pytest.approx(1.7)
    assert combined.antenna_left == pytest.approx(0.45)


def _program() -> GestureProgram:
    return GestureProgram(
        "test",
        [PoseKeyframe(BodyPose(yaw=20.0, antenna_left=0.0, antenna_right=0.0), 0.5), PoseKeyframe(BodyPose(), 0.5)],
    )


def test_program_starts_at_neutral_and_ends_at_last_keyframe() -> None:
    """Evaluate clamps at both ends of the track."""
    program = _program()
    assert program.evaluate(-0.1) == BodyPose()
    assert program.evaluate(0.0) == BodyPose()
    assert program.evaluate(10.0) == BodyPose()


def test_program_hits_keyframe_poses() -> None:
    """At a keyframe boundary the pose equals that keyframe."""
    program = _program()
    assert program.evaluate(0.5).yaw == pytest.approx(20.0)
    assert 0.0 < program.evaluate(0.25).yaw < 20.0


def test_program_duration_is_the_track_length() -> None:
    """Duration sums the keyframe durations."""
    assert _program().duration == pytest.approx(1.0)


def test_program_requires_keyframes() -> None:
    """An empty track is rejected."""
    with pytest.raises(ValueError):
        GestureProgram("empty", [])
