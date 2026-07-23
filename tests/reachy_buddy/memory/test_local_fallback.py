"""Tests for the local fallback spool."""

from pathlib import Path

import pytest

from reachy_buddy.memory.hindsight import MemoryItem
from reachy_buddy.memory.local_fallback import FallbackSpool


def test_append_read_clear_cycle(tmp_path: Path) -> None:
    """Items spooled to disk round-trip and clear removes them."""
    spool = FallbackSpool(tmp_path)
    items = [
        MemoryItem(content="Jon is learning Docker", tags=("person:jon", "activity"), timestamp=1700000000.0),
        MemoryItem(content="The printer fan arrived", tags=("observation",)),
    ]

    assert spool.append("bank", items) == 2
    assert spool.pending_count("bank") == 2

    restored = spool.read("bank")
    assert [item.content for item in restored] == [item.content for item in items]
    assert restored[0].tags == ("person:jon", "activity")
    assert restored[0].timestamp == pytest.approx(1700000000.0)

    spool.clear("bank")
    assert spool.pending_count("bank") == 0
    assert spool.read("bank") == []


def test_append_nothing_writes_no_file(tmp_path: Path) -> None:
    """An empty batch is a no-op."""
    spool = FallbackSpool(tmp_path)
    assert spool.append("bank", []) == 0
    assert not spool.path_for("bank").exists()


def test_read_skips_corrupt_lines(tmp_path: Path) -> None:
    """A corrupt spool line is skipped with a warning, not an exception."""
    spool = FallbackSpool(tmp_path)
    spool.append("bank", [MemoryItem(content="good line")])
    with spool.path_for("bank").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    restored = spool.read("bank")
    assert [item.content for item in restored] == ["good line"]


def test_search_ranks_by_term_overlap(tmp_path: Path) -> None:
    """Degraded recall ranks spooled items by shared query terms."""
    spool = FallbackSpool(tmp_path)
    spool.append(
        "bank",
        [
            MemoryItem(content="Jon is learning Docker containers", timestamp=1.0),
            MemoryItem(content="The weather is rainy today", timestamp=2.0),
            MemoryItem(content="Jon got the Docker container running finally", timestamp=3.0),
        ],
    )

    hits = spool.search("bank", "docker container")
    assert [item.content for item in hits] == [
        "Jon got the Docker container running finally",
        "Jon is learning Docker containers",
    ]
    assert spool.search("bank", "nothing matches here") == []


def test_banks_spool_to_separate_files(tmp_path: Path) -> None:
    """Each personality bank gets its own spool file."""
    spool = FallbackSpool(tmp_path)
    spool.append("reachy-default", [MemoryItem(content="a")])
    spool.append("reachy-noir", [MemoryItem(content="b")])

    assert spool.pending_count("reachy-default") == 1
    assert spool.pending_count("reachy-noir") == 1
    assert spool.path_for("reachy-default") != spool.path_for("reachy-noir")
