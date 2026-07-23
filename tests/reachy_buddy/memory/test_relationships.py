"""Tests for the MemoryStore relationship layer (scripted transport, no live server)."""

from datetime import datetime, timezone, timedelta

import httpx
import pytest

from reachy_buddy.memory.hindsight import MemoryItem, RecalledFact
from reachy_buddy.memory.relationships import (
    human_age,
    fact_age_days,
    clean_fact_text,
    parse_questions,
)
from reachy_buddy.memory.local_fallback import FallbackSpool
from .memory_testkit import ok_json


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _succeeded(entry: tuple[str, str, dict[str, object], object], path_suffix: str) -> bool:
    return entry[0] == "POST" and entry[1].endswith(path_suffix) and entry[3] == 200


def _fact(text: str, days: float, tags: tuple[str, ...] = ("person:jon",)) -> dict[str, object]:
    return {
        "id": f"id-{text[:6]}",
        "text": text,
        "type": "experience",
        "mentioned_at": _iso_days_ago(days),
        "tags": list(tags),
    }


def _happy_handler(recall_results: list[dict[str, object]], reflect_text: str = ""):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "PUT":
            return ok_json({"bank_id": "ok"})
        if path.endswith("/memories/recall"):
            return ok_json({"results": recall_results})
        if path.endswith("/reflect"):
            return ok_json({"text": reflect_text})
        if path.endswith("/memories"):
            return ok_json({"success": True, "items_count": 1, "async": True, "operation_id": "op-1"})
        if path.endswith("/entities"):
            return ok_json({"items": []})
        return ok_json({})

    return handler


@pytest.mark.asyncio
async def test_submit_buffers_and_flushes_at_threshold(store_factory, recorded_requests, tmp_path) -> None:
    """Writes stay in memory until the buffer reaches flush_max_items."""
    store = store_factory(_happy_handler([]), flush_max_items=2)
    await store.start()

    await store.submit_activity("jon", "Jon said he is learning Docker")
    assert not [entry for entry in recorded_requests if entry[1].endswith("/memories")]

    await store.submit_observation("Jon looked tired", person_id="jon")
    retains = [entry for entry in recorded_requests if _succeeded(entry, "/memories")]
    assert len(retains) == 1
    items = retains[0][2]["items"]
    assert [item["content"] for item in items] == ["Jon said he is learning Docker", "Jon looked tired"]
    assert items[0]["tags"] == ["activity", "person:jon"]
    assert items[1]["tags"] == ["observation", "person:jon"]
    await store.close()


@pytest.mark.asyncio
async def test_outage_spools_and_recovery_replays_in_order(store_factory, recorded_requests, tmp_path) -> None:
    """Outage: writes spool to disk; recovery: spool replays before new writes."""
    state = {"down": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["down"] and request.url.path.endswith("/memories"):
            raise httpx.ConnectError("server down")
        return _happy_handler([])(request)

    store = store_factory(handler, flush_max_items=10)
    await store.start()
    await store.submit_activity("jon", "Jon is learning Docker")
    await store.submit_preference("jon", "Jon prefers decaf after lunch")
    await store.flush()

    assert store.degraded is True
    assert store.pending_writes == 2
    assert not [entry for entry in recorded_requests if _succeeded(entry, "/memories")]

    state["down"] = False
    await store.submit_observation("Jon is at his desk", person_id="jon")
    await store.flush()

    retains = [entry[2]["items"] for entry in recorded_requests if _succeeded(entry, "/memories")]
    assert [[item["content"] for item in batch] for batch in retains] == [
        ["Jon is learning Docker", "Jon prefers decaf after lunch"],
        ["Jon is at his desk"],
    ]
    assert store.degraded is False
    assert store.pending_writes == 0
    await store.close()


@pytest.mark.asyncio
async def test_recall_about_scopes_to_person(store_factory, recorded_requests) -> None:
    """Person recall queries only that person's tag with strict matching."""
    store = store_factory(_happy_handler([_fact("Jon is learning Docker | When: today | Involving: Jon", 0)]))
    await store.start()

    facts = await store.recall_about("jon")

    recall_requests = [entry for entry in recorded_requests if entry[1].endswith("/memories/recall")]
    assert recall_requests[0][2]["tags"] == ["person:jon"]
    assert recall_requests[0][2]["tags_match"] == "any_strict"
    assert facts[0].text.startswith("Jon is learning Docker")
    await store.close()


@pytest.mark.asyncio
async def test_recall_about_falls_back_to_spool_during_outage(store_factory, tmp_path) -> None:
    """With Hindsight down, recall serves degraded results from the spool."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("server down")

    FallbackSpool(tmp_path).append(
        "reachy-default",
        [MemoryItem(content="Jon is learning Docker", tags=("activity", "person:jon"), timestamp=1.0)],
    )
    store = store_factory(handler)
    await store.start()

    facts = await store.recall_about("jon", "docker")

    assert store.degraded is True
    assert [fact.text for fact in facts] == ["Jon is learning Docker"]
    assert facts[0].fact_type == "spooled"
    await store.close()


@pytest.mark.asyncio
async def test_relationship_prompt_formats_facts_with_age(store_factory) -> None:
    """The prompt block lists cleaned facts with natural-language ages."""
    results = [_fact("Jon is learning Docker | When: Sunday, July 19, 2026 | Involving: Jon", 3)]
    store = store_factory(_happy_handler(results))
    await store.start()

    block = await store.relationship_prompt("jon", display_name="Jon")

    assert block.startswith("What you remember about Jon")
    assert "- Jon is learning Docker (3 days ago)" in block
    assert "|" not in block
    await store.close()


@pytest.mark.asyncio
async def test_relationship_prompt_empty_without_memories(store_factory) -> None:
    """No memories means an empty block, not a bare header."""
    store = store_factory(_happy_handler([]))
    await store.start()
    assert await store.relationship_prompt("jon") == ""
    await store.close()


@pytest.mark.asyncio
async def test_suggest_callbacks_uses_reflect_phrasing(store_factory) -> None:
    """Reflect phrasing wins when the server returns usable questions."""
    results = [
        _fact("Jon was learning Docker | When: last week | Involving: Jon", 9),
        _fact("Jon was frustrated with his 3D printer | When: yesterday | Involving: Jon", 1),
    ]
    reflect = "- Did you ever get that Docker container working?\n- Did the new printer part fix it?"
    store = store_factory(_happy_handler(results, reflect))
    await store.start()

    callbacks = await store.suggest_callbacks("jon", display_name="Jon")

    assert len(callbacks) == 2
    assert callbacks[0].origin == "reflect"
    assert callbacks[0].question == "Did you ever get that Docker container working?"
    assert callbacks[0].fact_text == "Jon was learning Docker"
    assert callbacks[0].days_since == 9
    assert callbacks[1].question == "Did the new printer part fix it?"
    await store.close()


@pytest.mark.asyncio
async def test_suggest_callbacks_falls_back_to_templates(store_factory) -> None:
    """A broken reflect still yields grounded, instruction-shaped callbacks."""
    results = [_fact("Jon was learning Docker | When: last week | Involving: Jon", 9)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/reflect"):
            return ok_json({"detail": "llm down"}, status=500)
        return _happy_handler(results)(request)

    store = store_factory(handler)
    await store.start()

    callbacks = await store.suggest_callbacks("jon", display_name="Jon")

    assert len(callbacks) == 1
    assert callbacks[0].origin == "template"
    assert "Jon was learning Docker" in callbacks[0].question
    assert "last week" in callbacks[0].question
    await store.close()


@pytest.mark.asyncio
async def test_suggest_callbacks_empty_without_memories(store_factory) -> None:
    """No memories means no callbacks to suggest."""
    store = store_factory(_happy_handler([]))
    await store.start()
    assert await store.suggest_callbacks("jon") == []
    await store.close()


@pytest.mark.asyncio
async def test_digest_session_retains_immediately_with_tags(store_factory, recorded_requests) -> None:
    """Session digests bypass the buffer and carry digest + person tags."""
    store = store_factory(_happy_handler([]))
    await store.start()

    await store.digest_session(
        "Jon worked on the CAD mount for two hours; one unrecognized visitor.", person_ids=("jon",)
    )

    retains = [entry for entry in recorded_requests if _succeeded(entry, "/memories")]
    assert len(retains) == 1
    item = retains[0][2]["items"][0]
    assert item["tags"] == ["session-digest", "person:jon"]
    assert "CAD mount" in item["content"]
    await store.close()


@pytest.mark.asyncio
async def test_recurring_entities_filters_by_mentions(store_factory) -> None:
    """Only entities mentioned at least min_mentions times come back."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/entities"):
            return ok_json(
                {
                    "items": [
                        {"id": "e1", "canonical_name": "Jon", "mention_count": 12},
                        {"id": "e2", "canonical_name": "Sarah", "mention_count": 1},
                        {"id": "e3", "canonical_name": "printer", "mention_count": 4},
                    ]
                }
            )
        return _happy_handler([])(request)

    store = store_factory(handler)
    await store.start()

    names = [entity.canonical_name for entity in await store.recurring_entities(min_mentions=2)]
    assert names == ["Jon", "printer"]
    await store.close()


def test_clean_fact_text_strips_decorations() -> None:
    """Hindsight's When/Involving suffixes are removed from fact text."""
    assert clean_fact_text("Jon is learning Docker | When: today | Involving: Jon") == "Jon is learning Docker"
    assert clean_fact_text("Plain fact.") == "Plain fact"


def test_human_age_buckets() -> None:
    """Ages render as natural language buckets."""
    assert human_age(0) == "today"
    assert human_age(1) == "yesterday"
    assert human_age(5) == "5 days ago"
    assert human_age(9) == "last week"
    assert human_age(21) == "3 weeks ago"
    assert human_age(45) == "last month"
    assert human_age(200) == "6 months ago"


def test_fact_age_days_prefers_occurred_start() -> None:
    """Age uses occurred_start when present, mentioned_at otherwise."""
    now = datetime(2026, 7, 19, tzinfo=timezone.utc).timestamp()
    fact = RecalledFact(
        fact_id="x",
        text="t",
        fact_type="world",
        tags=(),
        context=None,
        occurred_start="2026-07-10T00:00:00+00:00",
        occurred_end=None,
        mentioned_at="2026-07-18T00:00:00+00:00",
    )
    assert fact_age_days(fact, now) == 9
    undated = RecalledFact("x", "t", "world", (), None, None, None, None)
    assert fact_age_days(undated, now) == 0


def test_parse_questions_tolerates_markdown_noise() -> None:
    """Question parsing skips bullets, numbering, braces junk, and non-questions."""
    text = (
        "Here are some questions:\n"
        "- Did you get the container working?\n"
        "1. How is the printer now?\n"
        '{"name":"search_observations","parameters":{"query":"?"}}\n'
        "Jon likes coffee.\n"
        "2) What happened with the CAD mount?\n"
    )
    assert parse_questions(text, 5) == [
        "Did you get the container working?",
        "How is the printer now?",
        "What happened with the CAD mount?",
    ]
