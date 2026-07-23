"""Tests for the typed Hindsight HTTP client (no live server)."""

import httpx
import pytest

from reachy_buddy.memory.hindsight import (
    MemoryItem,
    Disposition,
    HindsightError,
)
from .memory_testkit import ok_json, make_client


def _fact_payload() -> dict[str, object]:
    return {
        "id": "f1",
        "text": "Jon is learning Docker | When: Sunday, July 19, 2026 | Involving: Jon",
        "type": "experience",
        "context": "conversation at desk",
        "occurred_start": "2026-07-12T10:00:00+00:00",
        "occurred_end": None,
        "mentioned_at": "2026-07-19T08:43:01+00:00",
        "tags": ["person:jon", "activity"],
    }


@pytest.mark.asyncio
async def test_ensure_bank_sends_mission_and_disposition(recorded_requests) -> None:
    """Bank provisioning PUTs mission and disposition traits to the bank path."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/v1/default/banks/reachy-default"
        return ok_json({"bank_id": "reachy-default"})

    client = make_client(handler, recorded_requests)
    await client.ensure_bank(
        "reachy-default",
        mission="Care about people",
        disposition=Disposition(skepticism=5, literalism=4, empathy=2),
        retain_mission="Extract activities",
    )
    await client.close()

    _, _, body, _ = recorded_requests[0]
    assert body["reflect_mission"] == "Care about people"
    assert body["retain_mission"] == "Extract activities"
    assert body["disposition_skepticism"] == 5
    assert body["disposition_literalism"] == 4
    assert body["disposition_empathy"] == 2


@pytest.mark.asyncio
async def test_retain_sends_items_and_reads_receipt(recorded_requests) -> None:
    """Retain posts item payloads and surfaces async operation ids."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/default/banks/b1/memories"
        return ok_json({"success": True, "items_count": 1, "async": True, "operation_id": "op-9"})

    client = make_client(handler, recorded_requests)
    receipt = await client.retain(
        "b1",
        [
            MemoryItem(
                content="Jon likes decaf", tags=("person:jon", "preference"), context="desk", timestamp=1700000000.0
            )
        ],
    )
    await client.close()

    _, _, body, _ = recorded_requests[0]
    assert body["async"] is True
    item = body["items"][0]
    assert item["content"] == "Jon likes decaf"
    assert item["tags"] == ["person:jon", "preference"]
    assert item["context"] == "desk"
    assert item["timestamp"].startswith("2023-11-14T22:13:20")
    assert receipt.operation_ids == ("op-9",)
    assert receipt.queued_async is True


@pytest.mark.asyncio
async def test_recall_scopes_tags_and_parses_facts(recorded_requests) -> None:
    """Recall sends the tag scope and parses results into typed facts."""

    def handler(request: httpx.Request) -> httpx.Response:
        return ok_json({"results": [_fact_payload()]})

    client = make_client(handler, recorded_requests)
    facts = await client.recall("b1", "what is Jon doing", tags=("person:jon",), tags_match="any_strict")
    await client.close()

    _, _, body, _ = recorded_requests[0]
    assert body["tags"] == ["person:jon"]
    assert body["tags_match"] == "any_strict"
    assert len(facts) == 1
    fact = facts[0]
    assert fact.fact_id == "f1"
    assert fact.fact_type == "experience"
    assert fact.tags == ("person:jon", "activity")
    assert fact.context == "conversation at desk"
    assert fact.occurred_start == "2026-07-12T10:00:00+00:00"


@pytest.mark.asyncio
async def test_reflect_entities_and_tags(recorded_requests) -> None:
    """Reflect returns text; entities and tags endpoints parse their lists."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/reflect"):
            return ok_json({"text": "Ask Jon about Docker."})
        if request.url.path.endswith("/entities"):
            return ok_json(
                {
                    "items": [
                        {
                            "id": "e1",
                            "canonical_name": "Jon",
                            "mention_count": 7,
                            "first_seen": "2026-01-01T00:00:00+00:00",
                            "last_seen": None,
                        }
                    ]
                }
            )
        if request.url.path.endswith("/tags"):
            return ok_json({"items": [{"tag": "person:jon", "count": 7}]})
        return ok_json({}, status=404)

    client = make_client(handler, recorded_requests)
    assert await client.reflect("b1", "what changed for Jon?") == "Ask Jon about Docker."
    entities = await client.entities("b1")
    tag_counts = await client.tags("b1")
    await client.close()

    assert entities[0].canonical_name == "Jon"
    assert entities[0].mention_count == 7
    assert (tag_counts[0].tag, tag_counts[0].count) == ("person:jon", 7)


@pytest.mark.asyncio
async def test_http_errors_raise_hindsight_error(recorded_requests) -> None:
    """Server and connection failures surface as HindsightError, never raw httpx."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/memories"):
            return ok_json({"detail": "boom"}, status=500)
        raise httpx.ConnectError("connection refused")

    client = make_client(handler, recorded_requests)
    with pytest.raises(HindsightError) as status_error:
        await client.retain("b1", [MemoryItem(content="x")])
    assert status_error.value.status_code == 500
    with pytest.raises(HindsightError) as conn_error:
        await client.recall("b1", "anything")
    assert conn_error.value.status_code is None
    await client.close()


@pytest.mark.asyncio
async def test_health_never_raises(recorded_requests) -> None:
    """Health reports False on failure and True only for a healthy payload."""

    def handler(request: httpx.Request) -> httpx.Response:
        return ok_json({"status": "healthy", "database": "connected"})

    client = make_client(handler, recorded_requests)
    assert await client.health() is True
    await client.close()

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = make_client(broken, recorded_requests)
    assert await client.health() is False
    await client.close()


def test_memory_item_payload_roundtrip() -> None:
    """MemoryItem survives to_payload/from_payload with tags, entities, and timestamp."""
    item = MemoryItem(
        content="Sarah visited",
        tags=("person:sarah", "visitor"),
        context="afternoon",
        timestamp=1700000000.0,
        metadata={"was": "unknown-3f2a"},
        entities=("Sarah",),
    )
    restored = MemoryItem.from_payload(item.to_payload())
    assert restored.content == item.content
    assert restored.tags == item.tags
    assert restored.context == item.context
    assert restored.timestamp == pytest.approx(item.timestamp)
    assert restored.metadata == item.metadata
    assert restored.entities == item.entities


def test_disposition_clamps_out_of_range_traits() -> None:
    """Disposition clamps traits into Hindsight's 1-5 range."""
    disposition = Disposition(skepticism=0, literalism=9, empathy=3)
    assert (disposition.skepticism, disposition.literalism, disposition.empathy) == (1, 5, 3)
