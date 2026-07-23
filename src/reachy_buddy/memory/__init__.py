"""Memory: Hindsight backend integration with per-personality banks."""

from reachy_buddy.memory.banks import BankManager, BankProfile
from reachy_buddy.memory.config import MemoryConfig
from reachy_buddy.memory.hindsight import (
    TagCount,
    MemoryItem,
    Disposition,
    MemoryEntity,
    RecalledFact,
    RetainReceipt,
    HindsightError,
    HindsightClient,
)
from reachy_buddy.memory.relationships import (
    MemoryStore,
    CallbackCandidate,
    person_tag,
)
from reachy_buddy.memory.local_fallback import FallbackSpool


__all__ = [
    "BankManager",
    "BankProfile",
    "CallbackCandidate",
    "Disposition",
    "FallbackSpool",
    "HindsightClient",
    "HindsightError",
    "MemoryConfig",
    "MemoryEntity",
    "MemoryItem",
    "MemoryStore",
    "RecalledFact",
    "RetainReceipt",
    "TagCount",
    "person_tag",
]
