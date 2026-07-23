"""Tests for the emotional state and its label."""

from reachy_buddy.core.drives import Drives
from reachy_buddy.core.emotional_state import EmotionalState


def test_nudge_clamps_valence_and_arousal() -> None:
    """Mood components stay inside [-1, 1] no matter how hard they are pushed."""
    mood = EmotionalState(valence=0.9, arousal=-0.9)
    mood.nudge(0.5, -0.5)

    assert mood.valence == 1.0
    assert mood.arousal == -1.0


def test_decay_pulls_mood_toward_neutral() -> None:
    """An old extreme mood fades toward zero."""
    mood = EmotionalState(valence=1.0, arousal=1.0)
    mood.updated_at -= 600.0
    mood.decay(half_life_seconds=300.0)

    assert 0.0 < mood.valence < 0.5
    assert 0.0 < mood.arousal < 0.5


def test_label_playful() -> None:
    """High playfulness reads as playful."""
    assert EmotionalState().label(Drives(playfulness=0.8)) == "playful"


def test_label_excited() -> None:
    """High arousal with high curiosity reads as excited."""
    mood = EmotionalState(arousal=0.7)
    assert mood.label(Drives(curiosity=0.7)) == "excited"


def test_label_curious() -> None:
    """High curiosity on its own reads as curious."""
    mood = EmotionalState(arousal=0.4)
    assert mood.label(Drives(curiosity=0.7)) == "curious"


def test_label_sleepy() -> None:
    """Low arousal with low social energy reads as sleepy."""
    mood = EmotionalState(arousal=0.1)
    assert mood.label(Drives(social_energy=0.2)) == "sleepy"


def test_label_proud() -> None:
    """High confidence with positive valence reads as proud."""
    mood = EmotionalState(valence=0.3, arousal=0.4)
    assert mood.label(Drives(confidence=0.8)) == "proud"


def test_label_concerned() -> None:
    """Negative valence reads as concerned."""
    mood = EmotionalState(valence=-0.5, arousal=0.4)
    assert mood.label(Drives()) == "concerned"


def test_label_calm_by_default() -> None:
    """Neutral mood and drives read as calm."""
    assert EmotionalState().label(Drives()) == "calm"
