"""Fixtures for memory subsystem tests: a MemoryStore around MockTransport."""

from pathlib import Path

import pytest

from reachy_buddy.memory.banks import BankManager
from reachy_buddy.memory.relationships import MemoryStore
from reachy_buddy.memory.local_fallback import FallbackSpool
from .memory_testkit import Handler, RecordedRequest, make_client


@pytest.fixture()
def recorded_requests() -> list[RecordedRequest]:
    """Collect (method, path, json-body, status) for every request the client makes."""
    return []


@pytest.fixture()
def store_factory(tmp_path: Path, recorded_requests: list[RecordedRequest]):
    """Return a factory building a MemoryStore around a scripted transport handler."""

    def build(handler: Handler, *, flush_max_items: int = 20) -> MemoryStore:
        client = make_client(handler, recorded_requests)
        banks = BankManager(client)
        profile = banks.profile_for("default")
        return MemoryStore(client, banks, FallbackSpool(tmp_path), profile, flush_max_items=flush_max_items)

    return build
