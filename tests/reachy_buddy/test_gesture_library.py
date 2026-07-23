"""Tests for the gesture library: coverage, program shapes, and per-gesture meaning."""

import pytest

from reachy_buddy.animation.pose import BodyPose
from reachy_buddy.animation.program import GestureProgram
from reachy_buddy.animation.gestures import GestureLibrary


def _samples(program: GestureProgram, count: int = 240) -> list[BodyPose]:
    return [program.evaluate(program.duration * i / (count - 1)) for i in range(count)]


def test_library_covers_the_communicative_gestures() -> None:
    """The spec's seven communicative gestures plus the basics are all buildable."""
    names = GestureLibrary().names()
    for expected in (
        "look_up_recall",
        "turn_to_sound",
        "tilt_uncertain",
        "lean_interested",
        "antenna_twitch",
        "look_at_object",
        "glance_reaction",
        "nod",
        "shake",
    ):
        assert expected in names


def test_unknown_gesture_raises() -> None:
    """Building an unregistered name fails loudly."""
    with pytest.raises(KeyError):
        GestureLibrary().build("cartwheel")


def test_self_contained_gestures_return_to_neutral() -> None:
    """Gestures that are not aimed at a target end where they started."""
    library = GestureLibrary()
    for name in (
        "nod",
        "shake",
        "look_up_recall",
        "tilt_uncertain",
        "lean_interested",
        "antenna_twitch",
        "scan",
        "glance_down",
        "perk_up",
        "droop",
    ):
        program = library.build(name)
        assert program.evaluate(program.duration) == BodyPose(), name


def test_look_up_recall_gazes_upward() -> None:
    """Recalling a memory lifts the gaze high and aside while holding."""
    poses = _samples(GestureLibrary().look_up_recall())
    assert max(p.pitch for p in poses) >= 15.0
    assert min(p.yaw for p in poses) <= -5.0


def test_turn_to_sound_faces_the_source() -> None:
    """The turn overshoots slightly, then holds the sound's direction, antennas perked."""
    program = GestureLibrary().turn_to_sound(40.0)
    final = program.evaluate(program.duration)
    assert final.yaw == pytest.approx(40.0)
    assert final.antenna_left >= 0.5
    assert max(p.yaw for p in _samples(program)) > 40.0


def test_tilt_uncertain_holds_a_roll() -> None:
    """Uncertainty shows as a sustained head roll."""
    assert max(p.roll for p in _samples(GestureLibrary().tilt_uncertain())) >= 10.0


def test_lean_interested_tips_forward() -> None:
    """Interest tips the head forward toward the speaker."""
    assert min(p.pitch for p in _samples(GestureLibrary().lean_interested())) <= -8.0


def test_antenna_twitch_oscillates_antennas() -> None:
    """Excitement oscillates the antennas several times around a perked pose."""
    program = GestureLibrary().antenna_twitch()
    values = [p.antenna_left for p in _samples(program, count=400)]
    crossings = sum(1 for before, after in zip(values, values[1:]) if (before - 0.6) * (after - 0.6) < 0)
    assert crossings >= 4
    assert max(values) >= 0.8


def test_look_at_object_holds_the_target() -> None:
    """The object glance ends still holding the object in view."""
    program = GestureLibrary().look_at_object(30.0, -10.0)
    final = program.evaluate(program.duration)
    assert final.yaw == pytest.approx(30.0)
    assert final.pitch == pytest.approx(-10.0)


def test_glance_reaction_reads_the_user() -> None:
    """After the glance the pose stays on the user with engaged antennas."""
    program = GestureLibrary().glance_reaction(25.0)
    poses = _samples(program)
    assert max(p.yaw for p in poses) >= 20.0
    assert program.evaluate(program.duration).yaw == pytest.approx(25.0)
    assert max(p.antenna_left for p in poses) >= 0.4
