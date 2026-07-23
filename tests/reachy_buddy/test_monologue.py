"""Tests for the private thought stream."""

import random

from reachy_buddy.core.monologue import (
    Thought,
    ThoughtStream,
    ThoughtContext,
    TemplateThoughtGenerator,
)
from reachy_buddy.core.personality import Personality


class FixedGenerator:
    """Test double that always returns the same thought and salience."""

    def __init__(self, salience: float) -> None:
        """Initialize with the salience every generated thought will carry."""
        self._salience = salience

    def generate(self, context: ThoughtContext) -> tuple[str, float]:
        """Return a fixed thought with the configured salience."""
        return "fixed thought", self._salience


def make_stream(salience: float) -> ThoughtStream:
    """Build a thought stream whose generator always produces the given salience."""
    return ThoughtStream(
        personality=Personality(monologue_cadence_s=(10.0, 20.0)),
        generator=FixedGenerator(salience),
        rng=random.Random(42),
    )


def context() -> ThoughtContext:
    """Build a minimal thought context."""
    return ThoughtContext(world_summary="Jon (5 min)", seconds_since_speech=120.0, emotion_label="curious")


def test_low_salience_thoughts_are_discarded() -> None:
    """Most thoughts die in the head: salience below the discard band leaves no trace."""
    thought = make_stream(0.1).step(context())

    assert thought.disposition == "discard"
    assert not thought.speak_worthy


def test_mid_salience_thoughts_are_pondered_not_spoken() -> None:
    """Pondered thoughts join the stream and feed the next thought's context."""
    stream = make_stream(0.5)
    thought = stream.step(context())

    assert thought.disposition == "ponder"
    assert not thought.speak_worthy
    assert stream.recent_texts() == ("fixed thought",)


def test_high_salience_thoughts_become_speak_candidates() -> None:
    """Strong thoughts surface for the curiosity engine to arbitrate."""
    stream = make_stream(0.7)
    thought = stream.step(context())

    assert thought.disposition == "speak_candidate"
    assert thought.speak_worthy
    assert stream.latest_speak_candidate() == thought


def test_exceptional_thoughts_are_kept_as_memory_candidates() -> None:
    """The strongest thoughts are both speak-worthy and worth remembering."""
    thought = make_stream(0.95).step(context())

    assert thought.disposition == "memory_candidate"
    assert thought.speak_worthy


def test_cadence_gates_when_thoughts_happen() -> None:
    """A fresh stream thinks immediately, then waits for the personality's cadence."""
    stream = make_stream(0.5)
    assert stream.due()

    stream.step(context())
    assert not stream.due()


def test_zero_cadence_thinks_every_tick() -> None:
    """A zero cadence range leaves the stream permanently due."""
    stream = ThoughtStream(
        personality=Personality(monologue_cadence_s=(0.0, 0.0)),
        generator=FixedGenerator(0.5),
        rng=random.Random(42),
    )
    stream.step(context())

    assert stream.due()


def test_template_generator_drafts_from_an_empty_world() -> None:
    """With nothing to go on, the template generator still thinks a quiet thought."""
    generator = TemplateThoughtGenerator(rng=random.Random(42))
    text, salience = generator.generate(
        ThoughtContext(world_summary="", seconds_since_speech=0.0, emotion_label="calm")
    )

    assert text == "Quiet room, nothing new yet"
    assert 0.0 <= salience <= 1.0


def test_template_generator_notices_long_silence() -> None:
    """A long silence becomes a thought about not having talked, echoing the spec example."""
    generator = TemplateThoughtGenerator(rng=random.Random(0))
    seen_texts = set()
    for _ in range(20):
        text, salience = generator.generate(
            ThoughtContext(world_summary="", seconds_since_speech=900.0, emotion_label="calm")
        )
        seen_texts.add(text)
        assert 0.0 <= salience <= 1.0

    assert "I haven't talked in 15 minutes" in seen_texts


def test_thought_speak_worthy_property() -> None:
    """Speak and memory candidates may leave the head; discard and ponder may not."""
    assert Thought("a", 0.0, 0.7, "speak_candidate", "test").speak_worthy
    assert Thought("b", 0.0, 0.9, "memory_candidate", "test").speak_worthy
    assert not Thought("c", 0.0, 0.1, "discard", "test").speak_worthy
    assert not Thought("d", 0.0, 0.5, "ponder", "test").speak_worthy
