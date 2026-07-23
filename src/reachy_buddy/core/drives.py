"""Motivation drives: the internal variables that make Reachy want things."""

import logging
from dataclasses import dataclass


logger = logging.getLogger(__name__)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


@dataclass
class Stimulus:
    """A nudge to the drives produced by a single observation; zero fields mean no change."""

    curiosity: float = 0.0
    social_energy: float = 0.0
    playfulness: float = 0.0
    focus: float = 0.0
    confidence: float = 0.0


STIMULUS_BY_KIND: dict[str, Stimulus] = {
    "person_arrived": Stimulus(curiosity=0.2, social_energy=0.05, playfulness=0.05),
    "person_left": Stimulus(curiosity=-0.05, social_energy=0.1),
    "person_named": Stimulus(curiosity=0.1, confidence=0.1),
    "object_noticed": Stimulus(curiosity=0.15),
    "scene_caption": Stimulus(curiosity=-0.05, focus=0.05),
    "user_activity": Stimulus(curiosity=0.1, focus=0.1, confidence=0.05),
    "conversation": Stimulus(social_energy=-0.05, playfulness=0.05),
    "laughter": Stimulus(playfulness=0.2, confidence=0.05),
    "answered": Stimulus(confidence=0.03, social_energy=0.02),
    "ignored": Stimulus(confidence=-0.03, playfulness=-0.05),
    "thought_discarded": Stimulus(curiosity=-0.02),
    "thought_pondered": Stimulus(curiosity=-0.01, focus=0.02),
    "thought_spoken": Stimulus(curiosity=-0.1, social_energy=-0.05),
    "ambient": Stimulus(),
}


@dataclass
class Drives:
    """Current motivation levels in [0, 1]; every observation moves them."""

    curiosity: float = 0.5
    social_energy: float = 0.6
    playfulness: float = 0.5
    focus: float = 0.5
    confidence: float = 0.5

    def apply(self, stimulus: Stimulus) -> None:
        """Add a stimulus to the drives, clamping every variable to [0, 1]."""
        self.curiosity = _clamp(self.curiosity + stimulus.curiosity)
        self.social_energy = _clamp(self.social_energy + stimulus.social_energy)
        self.playfulness = _clamp(self.playfulness + stimulus.playfulness)
        self.focus = _clamp(self.focus + stimulus.focus)
        self.confidence = _clamp(self.confidence + stimulus.confidence)

    def stimulate(self, kind: str, salience: float = 1.0) -> None:
        """Apply the table stimulus for an observation kind, scaled by salience."""
        stimulus = STIMULUS_BY_KIND.get(kind)
        if stimulus is None:
            logger.warning("Unknown stimulus kind %r; drives unchanged", kind)
            return
        self.apply(
            Stimulus(
                curiosity=stimulus.curiosity * salience,
                social_energy=stimulus.social_energy * salience,
                playfulness=stimulus.playfulness * salience,
                focus=stimulus.focus * salience,
                confidence=stimulus.confidence * salience,
            )
        )

    def decay_toward(self, baseline: "Drives", rate: float) -> None:
        """Drift each drive a fraction of the way toward the personality baseline."""
        self.curiosity = _clamp(self.curiosity + (baseline.curiosity - self.curiosity) * rate)
        self.social_energy = _clamp(self.social_energy + (baseline.social_energy - self.social_energy) * rate)
        self.playfulness = _clamp(self.playfulness + (baseline.playfulness - self.playfulness) * rate)
        self.focus = _clamp(self.focus + (baseline.focus - self.focus) * rate)
        self.confidence = _clamp(self.confidence + (baseline.confidence - self.confidence) * rate)
