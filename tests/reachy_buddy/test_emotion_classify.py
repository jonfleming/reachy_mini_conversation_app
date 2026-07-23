"""Tests for the emotion label derivation and feel() anchors."""

from reachy_buddy.core.emotional_state import Emotion, EmotionalState, classify


def test_classify_covers_the_spec_labels() -> None:
    """Each spec-named region of the valence/arousal plane maps to its label."""
    assert classify(0.1, 0.45) == Emotion.CURIOUS
    assert classify(0.5, 0.8) == Emotion.EXCITED
    assert classify(0.0, -0.7) == Emotion.SLEEPY
    assert classify(0.75, 0.25) == Emotion.PROUD
    assert classify(-0.6, 0.1) == Emotion.CONCERNED
    assert classify(0.45, 0.4) == Emotion.PLAYFUL
    assert classify(0.0, 0.0) == Emotion.CALM


def test_feel_lands_on_every_emotion() -> None:
    """feel() moves the mood so the derived label matches the request, from any start."""
    for emotion in Emotion:
        mood = EmotionalState(valence=-1.0, arousal=1.0)
        mood.feel(emotion)
        assert mood.emotion is emotion


def test_feel_partial_intensity_only_biases() -> None:
    """A weak cue does not flip the label, it only leans the mood."""
    mood = EmotionalState()
    mood.feel(Emotion.EXCITED, intensity=0.3)
    assert mood.emotion is Emotion.CURIOUS


def test_decay_fades_label_back_to_calm() -> None:
    """An emotion felt long ago fades as the mood decays to neutral."""
    mood = EmotionalState()
    mood.feel(Emotion.EXCITED)
    mood.updated_at -= 3600.0
    mood.decay(half_life_seconds=300.0)
    assert mood.emotion is Emotion.CALM


def test_emotion_labels_are_strings() -> None:
    """Labels serialize as plain strings for prompts and logs."""
    assert Emotion.PLAYFUL == "playful"
