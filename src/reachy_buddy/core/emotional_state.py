"""Emotional state: a valence/arousal mood with derived, spec-named emotion labels."""

import time
from enum import Enum
from dataclasses import field, dataclass

from reachy_buddy.core.drives import Drives


class Emotion(str, Enum):
    """The buddy's expressive labels; the body-language vocabulary is built on these."""

    CALM = "calm"
    CURIOUS = "curious"
    EXCITED = "excited"
    SLEEPY = "sleepy"
    PROUD = "proud"
    CONCERNED = "concerned"
    PLAYFUL = "playful"


# Canonical valence/arousal anchor per label; feel() snaps the mood onto the anchor.
_EMOTION_ANCHORS: dict[Emotion, tuple[float, float]] = {
    Emotion.CALM: (0.0, 0.0),
    Emotion.CURIOUS: (0.1, 0.45),
    Emotion.EXCITED: (0.5, 0.8),
    Emotion.SLEEPY: (0.0, -0.7),
    Emotion.PROUD: (0.75, 0.25),
    Emotion.CONCERNED: (-0.6, 0.1),
    Emotion.PLAYFUL: (0.45, 0.4),
}


def classify(valence: float, arousal: float) -> Emotion:
    """Map a valence/arousal point to the dominant emotion label."""
    if arousal < -0.4:
        return Emotion.SLEEPY
    if arousal > 0.55 and valence > 0.15:
        return Emotion.EXCITED
    if valence < -0.35:
        return Emotion.CONCERNED
    if valence > 0.55 and arousal >= 0.0:
        return Emotion.PROUD
    if valence > 0.25 and arousal > 0.15:
        return Emotion.PLAYFUL
    if arousal > 0.2:
        return Emotion.CURIOUS
    return Emotion.CALM


@dataclass
class EmotionalState:
    """Current mood as valence/arousal in [-1, 1]; the emotion label is derived, never stored."""

    valence: float = 0.0
    arousal: float = 0.0
    updated_at: float = field(default_factory=time.time)

    def nudge(self, valence_delta: float, arousal_delta: float) -> None:
        """Shift the mood by the given deltas, clamped to [-1, 1]."""
        self.valence = min(1.0, max(-1.0, self.valence + valence_delta))
        self.arousal = min(1.0, max(-1.0, self.arousal + arousal_delta))
        self.updated_at = time.time()

    def feel(self, emotion: Emotion, intensity: float = 1.0) -> None:
        """Move the mood onto an emotion's anchor, scaled by intensity in [0, 1]."""
        anchor_valence, anchor_arousal = _EMOTION_ANCHORS[emotion]
        scale = min(1.0, max(0.0, intensity))
        self.nudge(anchor_valence * scale - self.valence, anchor_arousal * scale - self.arousal)

    def decay(self, half_life_seconds: float = 300.0) -> None:
        """Pull the mood toward neutral by the elapsed number of half-lives."""
        now = time.time()
        factor = 0.5 ** ((now - self.updated_at) / half_life_seconds)
        self.valence *= factor
        self.arousal *= factor
        self.updated_at = now

    @property
    def emotion(self) -> Emotion:
        """Derive the dominant emotion from the current valence/arousal alone."""
        return classify(self.valence, self.arousal)

    def label(self, drives: Drives) -> Emotion:
        """Derive the emotion label from mood plus motivation drives."""
        if self.valence <= -0.3:
            return Emotion.CONCERNED
        if drives.playfulness >= 0.7:
            return Emotion.PLAYFUL
        if self.arousal >= 0.6 and drives.curiosity >= 0.6:
            return Emotion.EXCITED
        if drives.confidence >= 0.7 and self.valence > 0.0 and self.arousal >= 0.3:
            return Emotion.PROUD
        if drives.curiosity >= 0.6 and self.arousal >= 0.3:
            return Emotion.CURIOUS
        if self.arousal <= 0.15 and drives.social_energy <= 0.3:
            return Emotion.SLEEPY
        return Emotion.CALM
