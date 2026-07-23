"""Tests for env-driven memory configuration."""

from pathlib import Path

from reachy_buddy.memory.config import MemoryConfig
from reachy_buddy.memory.hindsight import Disposition


def test_from_env_uses_defaults() -> None:
    """Without BUDDY_* vars, config targets the local server with reachy- banks."""
    config = MemoryConfig.from_env("default", env={})

    assert config.base_url == "http://localhost:8888"
    assert config.bank_prefix == "reachy"
    assert config.personality == "default"


def test_from_env_reads_overrides() -> None:
    """BUDDY_* vars override URL, prefix, and spool dir."""
    config = MemoryConfig.from_env(
        "noir",
        env={
            "BUDDY_HINDSIGHT_URL": "http://100.120.84.114:8888",
            "BUDDY_HINDSIGHT_BANK_PREFIX": "buddy",
            "BUDDY_MEMORY_SPOOL_DIR": "/tmp/spool",
        },
    )

    assert config.base_url == "http://100.120.84.114:8888"
    assert config.bank_prefix == "buddy"
    assert config.spool_dir == Path("/tmp/spool")


def test_build_store_wires_personality_bank(tmp_path: Path) -> None:
    """The built store writes to the personality's own bank."""
    config = MemoryConfig(personality="Noir Detective", spool_dir=tmp_path, disposition=Disposition(5, 4, 2))
    store = config.build_store()

    assert store.bank_id == "reachy-noir-detective"
    assert store.degraded is False
