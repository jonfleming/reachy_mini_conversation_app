"""Curiosity engine: scores novelty and arbitrates what Reachy does about it."""

import time
import logging
from typing import Literal
from dataclasses import dataclass

from reachy_buddy.core.drives import Drives, Stimulus
from reachy_buddy.core.monologue import Thought
from reachy_buddy.core.personality import Personality


logger = logging.getLogger(__name__)

ActionKind = Literal["speak", "ask", "joke", "quiet", "attend"]


@dataclass
class ActionIntent:
    """One deliberate choice handed to the orchestrator, with the reason kept for logs."""

    kind: ActionKind
    payload: str
    urgency: float
    reason: str


class CuriosityEngine:
    """Turns drives, novelty, and thoughts into a single deliberate action per tick."""

    def __init__(self, familiarity_seconds: float = 600.0, personality: Personality | None = None) -> None:
        """Initialize with the novelty horizon and the personality whose thresholds govern decisions."""
        self.familiarity_seconds = familiarity_seconds
        self.personality = personality or Personality()
        self._last_seen: dict[str, float] = {}
        self._last_proactive_at = 0.0
        self._engagement = 1.0

    def score(self, label: str) -> float:
        """Return novelty in [0, 1]; 1.0 for never seen, rising back as time passes."""
        last = self._last_seen.get(label)
        if last is None:
            return 1.0
        return min(1.0, (time.time() - last) / self.familiarity_seconds)

    def mark_seen(self, label: str) -> None:
        """Record that a label received attention just now."""
        self._last_seen[label] = time.time()

    @property
    def engagement(self) -> float:
        """How encouraged the engine currently is to speak up, learned from past outcomes."""
        return self._engagement

    def decide(
        self,
        drives: Drives,
        *,
        seconds_since_speech: float,
        thought: Thought | None = None,
        novel_subject: str | None = None,
        someone_present: bool = True,
    ) -> ActionIntent:
        """Pick the single most urgent action the current internal state justifies."""
        personality = self.personality
        if not someone_present:
            return ActionIntent("attend", "", 0.0, "nobody is here; watching quietly costs nothing")
        if drives.confidence < personality.quiet_confidence or drives.social_energy < personality.quiet_social_energy:
            return ActionIntent(
                "quiet",
                "",
                0.0,
                f"confidence {drives.confidence:.2f}, social energy {drives.social_energy:.2f}; quietly watching",
            )
        cooldown_left = personality.speak_cooldown_s - (time.time() - self._last_proactive_at)
        if cooldown_left > 0:
            return ActionIntent("attend", "", 0.0, f"proactive cooldown has {cooldown_left:.0f}s left")
        candidates = self._candidates(drives, seconds_since_speech, thought, novel_subject)
        if not candidates:
            return ActionIntent("attend", "", 0.0, "nothing crosses a threshold")
        chosen = max(candidates, key=lambda candidate: candidate.urgency)
        logger.info("intent %s (urgency %.2f): %s", chosen.kind, chosen.urgency, chosen.reason)
        return chosen

    def mark_spoke(self) -> None:
        """Start the proactive cooldown after an unsolicited utterance is released."""
        self._last_proactive_at = time.time()

    def outcome_stimulus(self, answered: bool) -> Stimulus:
        """Learn from an utterance's fate and return the drives adjustment for it."""
        if answered:
            self._engagement = min(1.5, self._engagement + 0.05)
            return Stimulus(confidence=0.03, social_energy=0.02)
        self._engagement = max(0.5, self._engagement - 0.1)
        return Stimulus(confidence=-0.03, playfulness=-0.05)

    def _candidates(
        self,
        drives: Drives,
        seconds_since_speech: float,
        thought: Thought | None,
        novel_subject: str | None,
    ) -> list[ActionIntent]:
        personality = self.personality
        candidates: list[ActionIntent] = []
        if novel_subject is not None and drives.curiosity >= personality.ask_threshold:
            candidates.append(
                ActionIntent(
                    "ask",
                    f"Ask about {novel_subject}",
                    drives.curiosity,
                    f"curiosity {drives.curiosity:.2f} crossed {personality.ask_threshold:.2f} on {novel_subject}",
                )
            )
        if drives.playfulness >= personality.joke_threshold:
            candidates.append(
                ActionIntent(
                    "joke",
                    "Make a light joke",
                    drives.playfulness * 0.9,
                    f"playfulness {drives.playfulness:.2f} crossed {personality.joke_threshold:.2f}",
                )
            )
        if thought is not None and thought.speak_worthy:
            score = (
                0.6 * thought.salience
                + 0.3 * personality.chattiness * self._engagement
                + 0.1 * min(seconds_since_speech / 600.0, 1.0)
            )
            if score >= 0.75:
                candidates.append(
                    ActionIntent(
                        "speak",
                        thought.text,
                        score,
                        f"thought salience {thought.salience:.2f} scored {score:.2f} with chattiness "
                        f"{personality.chattiness:.2f} x engagement {self._engagement:.2f}",
                    )
                )
        return candidates
