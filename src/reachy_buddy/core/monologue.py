"""Private thought stream: an internal monologue that mostly never gets spoken."""

import time
import random
import logging
from typing import Literal, Protocol
from collections import deque
from dataclasses import dataclass

from reachy_buddy.core.personality import Personality


logger = logging.getLogger(__name__)

DISCARD_BELOW = 0.35
PONDER_BELOW = 0.6
MEMORY_AT = 0.8

Disposition = Literal["discard", "ponder", "speak_candidate", "memory_candidate"]


@dataclass
class Thought:
    """One monologue line and its fate; speech emerges from the stream, not from isolated prompts."""

    text: str
    ts: float
    salience: float
    disposition: Disposition
    origin: str

    @property
    def speak_worthy(self) -> bool:
        """Whether the thought may leave the head; memory candidates are speak candidates too."""
        return self.disposition in ("speak_candidate", "memory_candidate")


@dataclass(frozen=True)
class ThoughtContext:
    """Prompt material for one thought: the current world, mood, silence, and recent stream."""

    world_summary: str
    seconds_since_speech: float
    emotion_label: str
    present_labels: tuple[str, ...] = ()
    recent_thoughts: tuple[str, ...] = ()


class ThoughtGenerator(Protocol):
    """Produces one thought line plus a self-rated salience in [0, 1]."""

    def generate(self, context: ThoughtContext) -> tuple[str, float]:
        """Return (text, salience) for the given context."""
        ...


class TemplateThoughtGenerator:
    """Offline generator drafting spec-shaped thoughts from the world summary; an LLM replaces it later."""

    def __init__(self, rng: random.Random | None = None) -> None:
        """Initialize with an optional seeded RNG for deterministic tests."""
        self._rng = rng or random.Random()

    def generate(self, context: ThoughtContext) -> tuple[str, float]:
        """Draft a thought from presence, silence, and the world summary, with salience jitter."""
        options: list[tuple[str, float]] = []
        if context.present_labels:
            options.append((f"{context.present_labels[0]} has been around for a while now", 0.4))
        silent_minutes = context.seconds_since_speech / 60.0
        if silent_minutes >= 1.0:
            options.append(
                (f"I haven't talked in {max(1, round(silent_minutes))} minutes", min(0.9, 0.3 + silent_minutes / 30.0))
            )
        if context.world_summary:
            options.append((context.world_summary, 0.5))
        if context.recent_thoughts:
            options.append((f"Still turning over: {context.recent_thoughts[-1]}", 0.45))
        if not options:
            options.append(("Quiet room, nothing new yet", 0.2))
        text, salience = self._rng.choice(options)
        return text, min(1.0, max(0.0, salience + self._rng.uniform(-0.15, 0.15)))


class ThoughtStream:
    """The 10-20 s jittered monologue; keeps pondered thoughts in a small ring."""

    def __init__(
        self,
        personality: Personality | None = None,
        generator: ThoughtGenerator | None = None,
        rng: random.Random | None = None,
        ring_size: int = 20,
    ) -> None:
        """Initialize with the personality cadence, a generator, and the ponder ring size."""
        self.personality = personality or Personality()
        self._rng = rng or random.Random()
        self._generator = generator or TemplateThoughtGenerator(self._rng)
        self._ring: deque[Thought] = deque(maxlen=ring_size)
        self._next_due_at = 0.0

    def due(self) -> bool:
        """Whether it is time to think again."""
        return time.time() >= self._next_due_at

    def step(self, context: ThoughtContext) -> Thought:
        """Generate one thought, file it by salience, and schedule the next one."""
        text, salience = self._generator.generate(context)
        disposition = self._classify(salience)
        thought = Thought(
            text=text,
            ts=time.time(),
            salience=salience,
            disposition=disposition,
            origin=type(self._generator).__name__,
        )
        if disposition != "discard":
            self._ring.append(thought)
        low_s, high_s = self.personality.monologue_cadence_s
        self._next_due_at = time.time() + self._rng.uniform(low_s, high_s)
        logger.debug("thought (%s, %.2f): %s", disposition, salience, text)
        if thought.speak_worthy:
            logger.info("speak candidate (%.2f): %s", salience, text)
        return thought

    def recent_texts(self, count: int = 3) -> tuple[str, ...]:
        """Return the newest pondered thought texts, oldest first."""
        return tuple(t.text for t in list(self._ring)[-count:])

    def latest_speak_candidate(self) -> Thought | None:
        """Return the newest speak-worthy thought in the ring, if any."""
        for thought in reversed(self._ring):
            if thought.speak_worthy:
                return thought
        return None

    def _classify(self, salience: float) -> Disposition:
        if salience < DISCARD_BELOW:
            return "discard"
        if salience < PONDER_BELOW:
            return "ponder"
        if salience < MEMORY_AT:
            return "speak_candidate"
        return "memory_candidate"
