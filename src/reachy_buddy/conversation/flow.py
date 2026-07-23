"""Conversation flow: presence-driven phases for when Reachy should speak."""

import time
import logging
from enum import Enum


logger = logging.getLogger(__name__)


class ConversationPhase(Enum):
    """High-level state of the buddy's conversational engagement."""

    ALONE = "alone"
    GREETING = "greeting"
    ENGAGED = "engaged"
    FAREWELL = "farewell"


class ConversationFlow:
    """Drives phase transitions from presence events (faces arriving and leaving)."""

    def __init__(self, greet_after_seconds: float = 2.0, farewell_after_seconds: float = 30.0) -> None:
        """Initialize with the dwell delays before greeting and farewelling."""
        self.greet_after_seconds = greet_after_seconds
        self.farewell_after_seconds = farewell_after_seconds
        self.phase = ConversationPhase.ALONE
        self._present_since: float | None = None
        self._absent_since: float | None = None

    def on_person_present(self) -> None:
        """Update the phase for a detected presence."""
        now = time.time()
        self._absent_since = None
        if self._present_since is None:
            self._present_since = now
        if self.phase is ConversationPhase.ALONE and now - self._present_since >= self.greet_after_seconds:
            self.phase = ConversationPhase.GREETING
            logger.info("Greeting triggered")

    def on_person_absent(self) -> None:
        """Update the phase when no person is visible."""
        self._present_since = None
        if self.phase is not ConversationPhase.ENGAGED:
            return
        if self._absent_since is None:
            self._absent_since = time.time()
        elif time.time() - self._absent_since >= self.farewell_after_seconds:
            self.phase = ConversationPhase.FAREWELL
            self._absent_since = None
            logger.info("Farewell triggered")

    def mark_greeted(self) -> None:
        """Move from GREETING to ENGAGED once the greeting is delivered."""
        if self.phase is ConversationPhase.GREETING:
            self.phase = ConversationPhase.ENGAGED

    def reset(self) -> None:
        """Return to ALONE after a farewell is delivered."""
        self.phase = ConversationPhase.ALONE
        self._present_since = None
        self._absent_since = None
