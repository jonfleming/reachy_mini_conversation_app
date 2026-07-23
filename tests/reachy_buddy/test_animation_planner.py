"""Tests for the animation planner driving poses from mood, gestures, and idle."""

import random

import pytest

from reachy_buddy.animation.idle import IdleMotionEngine
from reachy_buddy.animation.pose import BodyPose
from reachy_buddy.animation.planner import GestureCue, AnimationPlanner
from reachy_buddy.core.emotional_state import Emotion, EmotionalState


class _FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the clock forward."""
        self.now += seconds


class _RecordingSink:
    """Captures every pose the planner emits."""

    def __init__(self) -> None:
        self.poses: list[BodyPose] = []

    def apply(self, pose: BodyPose, duration: float) -> None:
        """Record the pose."""
        self.poses.append(pose)


def _rig(seed: int = 7) -> tuple[EmotionalState, _FakeClock, _RecordingSink, AnimationPlanner]:
    mood = EmotionalState()
    clock = _FakeClock()
    sink = _RecordingSink()
    planner = AnimationPlanner(mood, sink, idle=IdleMotionEngine(rng=random.Random(seed)), clock=clock)
    return mood, clock, sink, planner


def _run(planner: AnimationPlanner, clock: _FakeClock, seconds: float, step: float = 0.1) -> None:
    for _ in range(int(seconds / step)):
        clock.advance(step)
        planner.tick()


def test_idle_emits_continuous_micro_motion() -> None:
    """With nothing queued the body keeps moving gently, never freezing."""
    _, clock, sink, planner = _rig()
    planner.tick()
    _run(planner, clock, 8.0)
    pitches = [p.pitch for p in sink.poses]
    assert max(pitches) - min(pitches) > 0.2
    assert all(abs(p.pitch) < 3.0 for p in sink.poses)


def test_gesture_plays_then_idle_resumes() -> None:
    """A requested gesture takes over the body, completes, and hands back to idle."""
    _, clock, sink, planner = _rig()
    planner.tick()
    duration = planner.play(GestureCue("look_up_recall"))
    assert planner.busy
    _run(planner, clock, duration + 1.0)
    assert not planner.busy
    assert max(p.pitch for p in sink.poses) >= 15.0
    assert abs(sink.poses[-1].pitch) < 4.0


def test_gesture_queue_runs_fifo() -> None:
    """Queued gestures run in request order."""
    _, clock, sink, planner = _rig()
    planner.tick()
    first = planner.play(GestureCue("turn_to_sound", yaw_degrees=45.0))
    planner.play(GestureCue("nod"))
    _run(planner, clock, first - 0.05)
    assert max(p.yaw for p in sink.poses) >= 40.0
    assert min(p.pitch for p in sink.poses) > -6.0
    _run(planner, clock, 2.0)
    assert min(p.pitch for p in sink.poses) <= -6.0


def test_emotion_change_transitions_smoothly() -> None:
    """Switching mood blends body style gradually and never exceeds the slew rate."""
    mood, clock, sink, planner = _rig()
    planner.tick()
    _run(planner, clock, 2.0)
    sink.poses.clear()
    mood.feel(Emotion.EXCITED)
    _run(planner, clock, 6.0, step=0.05)
    deltas = [abs(b.antenna_left - a.antenna_left) for a, b in zip(sink.poses, sink.poses[1:])]
    assert max(deltas) <= 4.0 * 0.05 + 1e-9
    tail = [p.antenna_left for p in sink.poses[-20:]]
    assert sum(tail) / len(tail) > 0.45


def test_engaged_conversation_pauses_idle_gestures() -> None:
    """While engaged, no idle gesture fires but the body keeps breathing."""
    _, clock, sink, planner = _rig()
    planner.set_engaged(True)
    planner.tick()
    _run(planner, clock, 70.0)
    assert not planner.busy
    assert max(abs(p.yaw) for p in sink.poses) < 5.0
    pitches = [p.pitch for p in sink.poses]
    assert max(pitches) - min(pitches) > 0.2
    planner.set_engaged(False)
    _run(planner, clock, 0.2)
    assert planner.busy


def test_idle_gesture_eventually_fires_when_alone() -> None:
    """Left alone long enough, the buddy does something on its own."""
    _, clock, sink, planner = _rig()
    planner.tick()
    _run(planner, clock, 60.0)
    assert max(abs(p.yaw) for p in sink.poses) > 5.0 or max(abs(p.pitch) for p in sink.poses) > 5.0


def test_slew_limits_gesture_onset() -> None:
    """Even a snapping gesture onset is rate-limited per tick."""
    _, clock, sink, planner = _rig()
    planner.tick()
    planner.play(GestureCue("turn_to_sound", yaw_degrees=80.0))
    clock.advance(0.1)
    planner.tick()
    assert abs(sink.poses[-1].yaw - sink.poses[-2].yaw) <= 170.0 * 0.1 + 1e-9


def test_full_queue_logs_and_drops(caplog: pytest.LogCaptureFixture) -> None:
    """Overflowing the queue logs and drops instead of growing unbounded."""
    mood = EmotionalState()
    clock = _FakeClock()
    planner = AnimationPlanner(
        mood,
        _RecordingSink(),
        idle=IdleMotionEngine(rng=random.Random(7)),
        max_queue=1,
        clock=clock,
    )
    planner.tick()
    planner.play(GestureCue("nod"))
    planner.play(GestureCue("shake"))
    planner.play(GestureCue("scan"))
    assert "Gesture queue full" in caplog.text
