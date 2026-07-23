"""Memory configuration: env-driven wiring for the Hindsight memory store."""

import os
from pathlib import Path
from dataclasses import dataclass
from collections.abc import Mapping

from reachy_buddy.memory.banks import BankManager
from reachy_buddy.memory.hindsight import Disposition, HindsightClient
from reachy_buddy.memory.relationships import MemoryStore
from reachy_buddy.memory.local_fallback import FallbackSpool


DEFAULT_HINDSIGHT_URL = "http://localhost:8888"
DEFAULT_BANK_PREFIX = "reachy"
DEFAULT_SPOOL_DIR = Path.home() / ".reachy_buddy" / "memory_spool"


@dataclass(frozen=True)
class MemoryConfig:
    """Everything needed to build a MemoryStore for one personality."""

    personality: str = "default"
    base_url: str = DEFAULT_HINDSIGHT_URL
    bank_prefix: str = DEFAULT_BANK_PREFIX
    spool_dir: Path = DEFAULT_SPOOL_DIR
    mission: str | None = None
    disposition: Disposition | None = None

    @classmethod
    def from_env(
        cls,
        personality: str = "default",
        *,
        mission: str | None = None,
        disposition: Disposition | None = None,
        env: Mapping[str, str] | None = None,
    ) -> "MemoryConfig":
        """Build a config from BUDDY_* environment variables with sane defaults."""
        source = os.environ if env is None else env
        return cls(
            personality=personality,
            base_url=source.get("BUDDY_HINDSIGHT_URL", DEFAULT_HINDSIGHT_URL),
            bank_prefix=source.get("BUDDY_HINDSIGHT_BANK_PREFIX", DEFAULT_BANK_PREFIX),
            spool_dir=Path(source.get("BUDDY_MEMORY_SPOOL_DIR", str(DEFAULT_SPOOL_DIR))),
            mission=mission,
            disposition=disposition,
        )

    def build_store(self, *, flush_max_items: int = 20) -> MemoryStore:
        """Construct the client, bank manager, spool, and store for this config."""
        client = HindsightClient(self.base_url)
        banks = BankManager(client, prefix=self.bank_prefix)
        profile = banks.profile_for(self.personality, mission=self.mission, disposition=self.disposition)
        return MemoryStore(client, banks, FallbackSpool(self.spool_dir), profile, flush_max_items=flush_max_items)
