"""Tests for the gaze behavior engine."""

import random
import threading

from reachy_buddy.animation.gaze import PRE_SPEECH_SHIFT_SECONDS, GazeLoop, GazeMode, GazeCommand, GazeController


def _make_controller() -> GazeController:
    return GazeController(rng=random.Random(42))


def _tick(controller: GazeController, start: float, stop: float, step: float = 0.05) -> list[GazeCommand]:
    commands = []
    now = start
    while now <= stop:
        commands.append(controller.update(now=now))
        now += step
    return commands


def test_idle_wanders_without_freezing() -> None:
    """Idle gaze keeps moving, inside the configured ranges."""
    controller = _make_controller()
    commands = _tick(controller, 0.0, 10.0, 0.1)
    yaws = [command.yaw_degrees for command in commands]
    pitches = [command.pitch_degrees for command in commands]
    assert max(yaws) - min(yaws) > 5.0
    assert len({round(yaw, 1) for yaw in yaws}) > 3
    assert all(abs(yaw) <= controller.idle_yaw_range + 1e-6 for yaw in yaws)
    assert all(abs(pitch) <= controller.idle_pitch_range + 1e-6 for pitch in pitches)


def test_tracking_converges_smoothly_to_face() -> None:
    """With a face present the gaze approaches its angles monotonically, without jumps."""
    controller = _make_controller()
    controller.track_face((0.8, 0.5))
    commands = _tick(controller, 0.0, 3.0, 0.1)
    yaws = [command.yaw_degrees for command in commands]
    assert controller.mode is GazeMode.TRACKING
    assert all(earlier <= later + 1e-9 for earlier, later in zip(yaws, yaws[1:]))
    assert all(yaw <= 21.0 + 1e-6 for yaw in yaws)
    assert abs(yaws[-1] - 21.0) < 0.5


def test_pre_speech_shift_lands_within_300ms() -> None:
    """Gaze shifts onto the listener and signals readiness after the pre-speech delay."""
    controller = _make_controller()
    controller.track_face((0.8, 0.5))
    wait = controller.prepare_speech(now=0.0)
    assert wait == PRE_SPEECH_SHIFT_SECONDS == 0.3
    assert not controller.speech_ready(now=0.29)
    commands = _tick(controller, 0.0, 0.3)
    assert controller.speech_ready(now=0.31)
    assert controller.mode is GazeMode.TRACKING
    assert commands[-1].yaw_degrees >= 0.9 * 21.0


def test_pre_speech_without_face_returns_to_idle() -> None:
    """With nobody present the pre-speech shift recenters, then falls back to idle."""
    controller = _make_controller()
    controller.prepare_speech(now=0.0)
    _tick(controller, 0.0, 0.35)
    assert controller.mode is GazeMode.IDLE


def test_glance_at_object_then_back_to_face() -> None:
    """A glance dwells on the object direction, then resumes tracking the face."""
    controller = _make_controller()
    controller.track_face((0.8, 0.5))
    _tick(controller, 0.0, 1.0, 0.1)
    controller.glance_at(40.0, -5.0, dwell_seconds=0.7, now=1.0)
    glance_commands = _tick(controller, 1.1, 1.6, 0.1)
    assert controller.mode is GazeMode.GLANCE
    assert max(command.yaw_degrees for command in glance_commands) > 21.0
    _tick(controller, 1.75, 4.0, 0.1)
    assert controller.mode is GazeMode.TRACKING
    assert abs(controller.update(now=4.1).yaw_degrees - 21.0) < 1.0


def test_uncertainty_tilts_head_then_recovers() -> None:
    """Expressing uncertainty adds a roll tilt that clears after its hold time."""
    controller = _make_controller()
    controller.express_uncertainty(now=0.0)
    assert controller.update(now=0.1).roll_degrees == 14.0
    assert controller.update(now=2.1).roll_degrees == 0.0


def test_interest_leans_forward_then_recovers() -> None:
    """Expressing interest leans the head forward, then returns to neutral."""
    controller = _make_controller()
    controller.express_interest(now=0.0)
    assert controller.update(now=0.1).forward_m == 0.02
    assert controller.update(now=2.6).forward_m == 0.0


def test_speaking_calms_tracking_into_eye_contact() -> None:
    """While speaking, the gaze moves toward the face more gently for stable eye contact."""
    silent = _make_controller()
    speaking = _make_controller()
    speaking.set_speaking(True)
    silent.track_face((0.8, 0.5))
    speaking.track_face((0.8, 0.5))
    silent_step = silent.update(now=0.0).yaw_degrees
    speaking_step = speaking.update(now=0.0).yaw_degrees
    assert 0.0 < speaking_step < silent_step


def test_gaze_loop_emits_commands_and_stops() -> None:
    """The loop thread pushes commands to the sink until stopped."""
    received: list[GazeCommand] = []
    enough = threading.Event()

    def sink(command: GazeCommand) -> None:
        received.append(command)
        if len(received) >= 5:
            enough.set()

    loop = GazeLoop(_make_controller(), command_sink=sink, updates_per_second=100.0)
    loop.start()
    assert enough.wait(timeout=2.0)
    loop.stop()
    assert all(isinstance(command, GazeCommand) for command in received)
