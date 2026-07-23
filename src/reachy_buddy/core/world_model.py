"""World model: what Reachy currently believes is in front of it."""

import time
from dataclasses import dataclass


@dataclass
class Observation:
    """A tracked entity: label, latest confidence, first/last sighting times, kind, and salience."""

    label: str
    confidence: float
    first_seen: float
    last_seen: float
    kind: str = "ambient"
    salience: float = 0.5


def _format_age(seconds: float) -> str:
    if seconds < 90.0:
        return "just now"
    minutes = round(seconds / 60.0)
    if minutes < 90:
        return f"{minutes} min"
    return f"{round(minutes / 60.0)} h"


class WorldModel:
    """Keeps recently observed entities and expires stale ones."""

    def __init__(self, retention_seconds: float = 30.0) -> None:
        """Initialize with the time window an observation stays 'active'."""
        self.retention_seconds = retention_seconds
        self._observations: dict[str, Observation] = {}

    def record(self, label: str, confidence: float, kind: str = "ambient", salience: float = 0.5) -> None:
        """Insert or refresh an observation."""
        now = time.time()
        existing = self._observations.get(label)
        if existing is None:
            self._observations[label] = Observation(label, confidence, now, now, kind, salience)
        else:
            existing.confidence = confidence
            existing.last_seen = now
            existing.kind = kind
            existing.salience = salience

    def active(self) -> list[Observation]:
        """Return observations still within the retention window."""
        now = time.time()
        return [o for o in self._observations.values() if now - o.last_seen <= self.retention_seconds]

    def forget_stale(self) -> None:
        """Drop observations past the retention window."""
        now = time.time()
        self._observations = {
            label: o for label, o in self._observations.items() if now - o.last_seen <= self.retention_seconds
        }

    def summary_text(self, max_chars: int = 800) -> str:
        """Render active observations as one prompt-ready line, e.g. 'Jon (12 min), coffee cup (just now)'."""
        active = self.active()
        if not active:
            return "Nothing observed yet."
        now = time.time()
        parts = [f"{o.label} ({_format_age(now - o.first_seen)})" for o in sorted(active, key=lambda o: o.first_seen)]
        summary = ", ".join(parts)
        if len(summary) > max_chars:
            summary = summary[: max_chars - 1].rstrip() + "…"
        return summary
