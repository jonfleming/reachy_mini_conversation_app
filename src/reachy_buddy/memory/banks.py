"""Per-personality Hindsight bank provisioning: one bank per character."""

import re
import logging
from dataclasses import dataclass

from reachy_buddy.memory.hindsight import Disposition, HindsightClient


logger = logging.getLogger(__name__)

DEFAULT_MISSION = (
    "You are the long-term memory of a desktop companion robot. "
    "Retain what matters about the people it lives with: their activities, plans, "
    "preferences, habits, moods, relationships, projects, and recurring visitors."
)
DEFAULT_DISPOSITION = Disposition(skepticism=2, literalism=3, empathy=4)


@dataclass(frozen=True)
class BankProfile:
    """How one personality maps to its Hindsight bank."""

    personality: str
    bank_id: str
    mission: str
    disposition: Disposition
    retain_mission: str | None = None


class BankManager:
    """Resolves personalities to banks and provisions them lazily, once per process."""

    def __init__(
        self,
        client: HindsightClient,
        *,
        prefix: str = "reachy",
        default_mission: str = DEFAULT_MISSION,
        default_disposition: Disposition = DEFAULT_DISPOSITION,
    ) -> None:
        """Initialize with the shared client and the bank-id prefix."""
        self._client = client
        self._prefix = prefix
        self._default_mission = default_mission
        self._default_disposition = default_disposition
        self._ensured: set[str] = set()

    def profile_for(
        self,
        personality: str,
        *,
        mission: str | None = None,
        disposition: Disposition | None = None,
        retain_mission: str | None = None,
    ) -> BankProfile:
        """Build the bank profile for a personality, applying per-character overrides."""
        slug = re.sub(r"[^a-z0-9_-]+", "-", personality.lower()).strip("-") or "default"
        return BankProfile(
            personality=personality,
            bank_id=f"{self._prefix}-{slug}",
            mission=mission or self._default_mission,
            disposition=disposition or self._default_disposition,
            retain_mission=retain_mission,
        )

    async def ensure(self, profile: BankProfile) -> None:
        """Provision the profile's bank on first use, then skip repeat calls."""
        if profile.bank_id in self._ensured:
            return
        await self._client.ensure_bank(
            profile.bank_id,
            mission=profile.mission,
            disposition=profile.disposition,
            retain_mission=profile.retain_mission,
        )
        self._ensured.add(profile.bank_id)
        logger.info("Provisioned Hindsight bank %s for personality %s", profile.bank_id, profile.personality)
