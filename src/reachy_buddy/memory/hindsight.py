"""Hindsight memory backend: typed async client over the Hindsight HTTP API."""

import logging
from datetime import datetime, timezone
from dataclasses import dataclass

import httpx


logger = logging.getLogger(__name__)

_API_PREFIX = "/v1/default/banks"


class HindsightError(Exception):
    """Raised when a Hindsight request fails; carries the HTTP status when known."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Initialize with a human message and optional HTTP status code."""
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Disposition:
    """Hindsight personality traits steering fact extraction (each 1-5)."""

    skepticism: int
    literalism: int
    empathy: int

    def __post_init__(self) -> None:
        """Clamp every trait into Hindsight's 1-5 range."""
        for name in ("skepticism", "literalism", "empathy"):
            value = getattr(self, name)
            object.__setattr__(self, name, max(1, min(5, value)))


@dataclass(frozen=True)
class MemoryItem:
    """One retain-worthy memory: content plus tags/context for later scoping."""

    content: str
    tags: tuple[str, ...] = ()
    context: str | None = None
    timestamp: float | None = None
    metadata: dict[str, str] | None = None
    entities: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        """Return the Hindsight MemoryItem JSON shape."""
        payload: dict[str, object] = {"content": self.content}
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.context:
            payload["context"] = self.context
        if self.timestamp is not None:
            payload["timestamp"] = datetime.fromtimestamp(self.timestamp, timezone.utc).isoformat()
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        if self.entities:
            payload["entities"] = [{"text": name} for name in self.entities]
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "MemoryItem":
        """Rebuild an item from its JSON shape, tolerating missing extras."""
        timestamp = payload.get("timestamp")
        epoch: float | None = None
        if isinstance(timestamp, str):
            try:
                epoch = datetime.fromisoformat(timestamp).timestamp()
            except ValueError:
                logger.warning("Ignoring unparseable spool timestamp: %s", timestamp)
        elif isinstance(timestamp, (int, float)):
            epoch = float(timestamp)
        entities = payload.get("entities")
        names: list[str] = []
        if isinstance(entities, list):
            for entry in entities:
                if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                    names.append(str(entry["text"]))
                elif isinstance(entry, str):
                    names.append(entry)
        context = payload.get("context")
        metadata = payload.get("metadata")
        return cls(
            content=str(payload.get("content", "")),
            tags=_str_tuple(payload.get("tags")),
            context=context if isinstance(context, str) else None,
            timestamp=epoch,
            metadata={str(k): str(v) for k, v in metadata.items()} if isinstance(metadata, dict) else None,
            entities=tuple(names),
        )


@dataclass(frozen=True)
class RecalledFact:
    """One fact returned by Hindsight recall."""

    fact_id: str
    text: str
    fact_type: str
    tags: tuple[str, ...]
    context: str | None
    occurred_start: str | None
    occurred_end: str | None
    mentioned_at: str | None


@dataclass(frozen=True)
class MemoryEntity:
    """A canonical entity Hindsight extracted for a bank (person, project, object)."""

    entity_id: str
    canonical_name: str
    mention_count: int
    first_seen: str | None
    last_seen: str | None


@dataclass(frozen=True)
class TagCount:
    """A tag and how many memories carry it."""

    tag: str
    count: int


@dataclass(frozen=True)
class RetainReceipt:
    """Acknowledgement of a retain call, with async operation ids when present."""

    items_count: int
    queued_async: bool
    operation_ids: tuple[str, ...]


def _str_tuple(value: object) -> tuple[str, ...]:
    """Narrow a JSON value to a tuple of strings, dropping non-strings."""
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _opt_str(value: object) -> str | None:
    """Narrow a JSON value to a string or None."""
    return value if isinstance(value, str) else None


class HindsightClient:
    """Thin async wrapper over the Hindsight REST endpoints the buddy uses."""

    def __init__(
        self,
        base_url: str = "http://localhost:8888",
        timeout_seconds: float = 10.0,
        slow_timeout_seconds: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the client; an injected client (tests) is used as-is."""
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(slow_timeout_seconds, connect=timeout_seconds),
        )

    async def health(self) -> bool:
        """Return True when the server reports healthy; never raises."""
        try:
            response = await self._client.get("/health")
            return response.status_code == 200 and response.json().get("status") == "healthy"
        except httpx.HTTPError as exc:
            logger.warning("Hindsight health check failed: %s", exc)
            return False

    async def ensure_bank(
        self,
        bank_id: str,
        *,
        mission: str,
        disposition: Disposition,
        retain_mission: str | None = None,
    ) -> None:
        """Create or update a bank with the given mission and disposition."""
        payload: dict[str, object] = {
            "name": bank_id,
            "reflect_mission": mission,
            "disposition_skepticism": disposition.skepticism,
            "disposition_literalism": disposition.literalism,
            "disposition_empathy": disposition.empathy,
        }
        if retain_mission:
            payload["retain_mission"] = retain_mission
        await self._request("PUT", f"{_API_PREFIX}/{bank_id}", payload)

    async def retain(self, bank_id: str, items: list[MemoryItem], *, queued_async: bool = True) -> RetainReceipt:
        """Retain items; async mode queues server-side and returns operation ids."""
        payload = {"items": [item.to_payload() for item in items], "async": queued_async}
        body = await self._request("POST", f"{_API_PREFIX}/{bank_id}/memories", payload)
        operation_ids: list[str] = []
        if isinstance(body.get("operation_id"), str):
            operation_ids.append(str(body["operation_id"]))
        operation_ids.extend(_str_tuple(body.get("operation_ids")))
        items_count = body.get("items_count")
        return RetainReceipt(
            items_count=items_count if isinstance(items_count, int) else len(items),
            queued_async=bool(body.get("async", queued_async)),
            operation_ids=tuple(operation_ids),
        )

    async def recall(
        self,
        bank_id: str,
        query: str,
        *,
        tags: tuple[str, ...] = (),
        tags_match: str = "any_strict",
        budget: str = "mid",
        max_tokens: int = 2048,
        fact_types: tuple[str, ...] = (),
    ) -> list[RecalledFact]:
        """Recall facts matching a query, optionally scoped by tags."""
        payload: dict[str, object] = {"query": query, "budget": budget, "max_tokens": max_tokens}
        if tags:
            payload["tags"] = list(tags)
            payload["tags_match"] = tags_match
        if fact_types:
            payload["types"] = list(fact_types)
        body = await self._request("POST", f"{_API_PREFIX}/{bank_id}/memories/recall", payload)
        results = body.get("results")
        if not isinstance(results, list):
            return []
        return [self._parse_fact(entry) for entry in results if isinstance(entry, dict)]

    async def reflect(
        self,
        bank_id: str,
        query: str,
        *,
        tags: tuple[str, ...] = (),
        tags_match: str = "any_strict",
        budget: str = "low",
        max_tokens: int = 1024,
    ) -> str:
        """Run a grounded reflect pass and return its markdown text."""
        payload: dict[str, object] = {"query": query, "budget": budget, "max_tokens": max_tokens}
        if tags:
            payload["tags"] = list(tags)
            payload["tags_match"] = tags_match
        body = await self._request("POST", f"{_API_PREFIX}/{bank_id}/reflect", payload)
        text = body.get("text")
        return text if isinstance(text, str) else ""

    async def entities(self, bank_id: str, *, limit: int = 100) -> list[MemoryEntity]:
        """List canonical entities known to the bank, most-mentioned first."""
        body = await self._request("GET", f"{_API_PREFIX}/{bank_id}/entities", None, params={"limit": limit})
        items = body.get("items")
        if not isinstance(items, list):
            return []
        return [
            MemoryEntity(
                entity_id=str(entry.get("id", "")),
                canonical_name=str(entry.get("canonical_name", "")),
                mention_count=int(entry.get("mention_count", 0)),
                first_seen=entry.get("first_seen") if isinstance(entry.get("first_seen"), str) else None,
                last_seen=entry.get("last_seen") if isinstance(entry.get("last_seen"), str) else None,
            )
            for entry in items
            if isinstance(entry, dict)
        ]

    async def tags(self, bank_id: str, *, limit: int = 100) -> list[TagCount]:
        """List tags present in the bank with their memory counts."""
        body = await self._request("GET", f"{_API_PREFIX}/{bank_id}/tags", None, params={"limit": limit})
        items = body.get("items")
        if not isinstance(items, list):
            return []
        return [
            TagCount(tag=str(entry.get("tag", "")), count=int(entry.get("count", 0)))
            for entry in items
            if isinstance(entry, dict)
        ]

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    @staticmethod
    def _parse_fact(entry: dict[str, object]) -> RecalledFact:
        """Parse one recall result entry into a RecalledFact."""
        context = _opt_str(entry.get("context"))
        return RecalledFact(
            fact_id=str(entry.get("id", "")),
            text=str(entry.get("text", "")),
            fact_type=str(entry.get("type", "world")),
            tags=_str_tuple(entry.get("tags")),
            context=context if context else None,
            occurred_start=_opt_str(entry.get("occurred_start")),
            occurred_end=_opt_str(entry.get("occurred_end")),
            mentioned_at=_opt_str(entry.get("mentioned_at")),
        )

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None,
        params: dict[str, int] | None = None,
    ) -> dict[str, object]:
        """Send one request and unwrap the JSON body, raising HindsightError on failure."""
        try:
            response = await self._client.request(method, path, json=payload, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HindsightError(
                f"Hindsight {method} {path} failed with {exc.response.status_code}", exc.response.status_code
            ) from exc
        except httpx.HTTPError as exc:
            raise HindsightError(f"Hindsight {method} {path} failed: {exc}") from exc
        body = response.json()
        return body if isinstance(body, dict) else {}
