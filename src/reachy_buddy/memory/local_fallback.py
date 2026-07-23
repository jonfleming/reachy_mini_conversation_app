"""Local fallback spool: survives Hindsight outages without losing memories."""

import json
import logging
from pathlib import Path
from collections.abc import Iterable

from reachy_buddy.memory.hindsight import MemoryItem


logger = logging.getLogger(__name__)


class FallbackSpool:
    """Append-only per-bank JSONL spool replayed when Hindsight comes back."""

    def __init__(self, directory: Path) -> None:
        """Initialize with the spool directory, created on demand."""
        self._directory = directory

    def path_for(self, bank_id: str) -> Path:
        """Return the spool file for a bank."""
        return self._directory / f"{bank_id}.jsonl"

    def append(self, bank_id: str, items: Iterable[MemoryItem]) -> int:
        """Append items to the bank's spool; returns how many were written."""
        batch = list(items)
        if not batch:
            return 0
        self._directory.mkdir(parents=True, exist_ok=True)
        with self.path_for(bank_id).open("a", encoding="utf-8") as handle:
            for item in batch:
                handle.write(json.dumps(item.to_payload()) + "\n")
        logger.info(
            "Spooled %s memor%s for %s (Hindsight unreachable)", len(batch), "y" if len(batch) == 1 else "ies", bank_id
        )
        return len(batch)

    def read(self, bank_id: str) -> list[MemoryItem]:
        """Read all spooled items for a bank, skipping corrupt lines."""
        path = self.path_for(bank_id)
        if not path.exists():
            return []
        items: list[MemoryItem] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                items.append(MemoryItem.from_payload(json.loads(line)))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("Skipping corrupt spool line in %s: %s", path, exc)
        return items

    def clear(self, bank_id: str) -> None:
        """Drop the bank's spool file after a successful replay."""
        self.path_for(bank_id).unlink(missing_ok=True)

    def pending_count(self, bank_id: str) -> int:
        """Return how many items are waiting to be replayed."""
        path = self.path_for(bank_id)
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def search(self, bank_id: str, query: str, *, limit: int = 5) -> list[MemoryItem]:
        """Degraded recall: rank spooled items by query-term overlap, newest last-write wins."""
        terms = {term.strip(".,?!\"'").lower() for term in query.split() if len(term.strip(".,?!\"'")) > 2}
        if not terms:
            return []
        scored: list[tuple[int, float, MemoryItem]] = []
        for item in self.read(bank_id):
            haystack = item.content.lower()
            hits = sum(1 for term in terms if term in haystack)
            if hits:
                scored.append((hits, item.timestamp or 0.0, item))
        scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        return [item for _, _, item in scored[:limit]]
