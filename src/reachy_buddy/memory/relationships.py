"""Relationship memory: per-person recall, callbacks, digests, and outage handling."""

import re
import time
import logging
from datetime import datetime, timezone
from dataclasses import dataclass

from reachy_buddy.memory.banks import BankManager, BankProfile
from reachy_buddy.memory.hindsight import MemoryItem, MemoryEntity, RecalledFact, HindsightError, HindsightClient
from reachy_buddy.memory.local_fallback import FallbackSpool


logger = logging.getLogger(__name__)

TAG_ACTIVITY = "activity"
TAG_OBSERVATION = "observation"
TAG_PREFERENCE = "preference"
TAG_HABIT = "habit"
TAG_VISITOR = "visitor"
TAG_ENROLLMENT = "enrollment"
TAG_THOUGHT = "thought"
TAG_SESSION_DIGEST = "session-digest"

_CALLBACK_MIN_AGE_DAYS = 1
_MAX_CALLBACK_QUESTION_CHARS = 240


def person_tag(person_id: str) -> str:
    """Return the tag scoping every memory about one person."""
    return f"person:{person_id}"


@dataclass(frozen=True)
class CallbackCandidate:
    """A follow-up the buddy could raise, grounded in one remembered fact."""

    fact_text: str
    days_since: int
    question: str
    origin: str


class MemoryStore:
    """Facade over Hindsight + spool: buffered real-time writes, per-person reads, callbacks.

    Writes are queued in memory and flushed on demand (flush_max_items) or by the
    caller's periodic flush(); outages spill to the spool and replay on recovery.
    """

    def __init__(
        self,
        client: HindsightClient,
        banks: BankManager,
        spool: FallbackSpool,
        profile: BankProfile,
        *,
        flush_max_items: int = 20,
    ) -> None:
        """Initialize the store for one personality's bank profile."""
        self._client = client
        self._banks = banks
        self._spool = spool
        self._profile = profile
        self._flush_max_items = flush_max_items
        self._buffer: list[MemoryItem] = []
        self._degraded = False

    @property
    def bank_id(self) -> str:
        """Return the Hindsight bank this store writes to."""
        return self._profile.bank_id

    @property
    def degraded(self) -> bool:
        """Return True while Hindsight is unreachable and writes are spooling."""
        return self._degraded

    @property
    def pending_writes(self) -> int:
        """Return buffered plus spooled items not yet retained by Hindsight."""
        return len(self._buffer) + self._spool.pending_count(self.bank_id)

    async def start(self) -> None:
        """Provision the bank and replay any spool left by a previous outage."""
        try:
            await self._banks.ensure(self._profile)
        except HindsightError as exc:
            self._degraded = True
            logger.warning("Hindsight unavailable at startup; memory degraded: %s", exc)
            return
        self._degraded = False
        await self.flush()

    def queue(self, item: MemoryItem) -> int:
        """Buffer an item for the next flush; returns the buffer size."""
        self._buffer.append(item)
        return len(self._buffer)

    async def submit(self, item: MemoryItem) -> None:
        """Queue an item and flush once the buffer reaches flush_max_items."""
        if self.queue(item) >= self._flush_max_items:
            await self.flush()

    async def submit_observation(self, text: str, *, person_id: str | None = None, context: str | None = None) -> None:
        """Buffer a visual or conversational observation."""
        await self.submit(_tagged(text, TAG_OBSERVATION, person_id, context=context))

    async def submit_activity(self, person_id: str, text: str) -> None:
        """Buffer a user-stated activity ('I'm working on the CAD mount')."""
        await self.submit(_tagged(text, TAG_ACTIVITY, person_id))

    async def submit_preference(self, person_id: str, text: str) -> None:
        """Buffer a learned preference ('prefers decaf in the afternoon')."""
        await self.submit(_tagged(text, TAG_PREFERENCE, person_id))

    async def submit_habit(self, person_id: str, text: str) -> None:
        """Buffer a mined habit ('usually starts work around 9am on weekdays')."""
        await self.submit(_tagged(text, TAG_HABIT, person_id))

    async def submit_visitor(self, person_id: str, text: str) -> None:
        """Buffer a visitor sighting or introduction."""
        await self.submit(_tagged(text, TAG_VISITOR, person_id))

    async def submit_enrollment(self, person_id: str, display_name: str, *, was_unknown_id: str | None = None) -> None:
        """Buffer a name-to-face enrollment, linking any pre-enrollment sightings."""
        text = f"{display_name} told me their name"
        item = _tagged(text, TAG_ENROLLMENT, person_id, entities=(display_name,))
        if was_unknown_id:
            item = MemoryItem(
                content=item.content,
                tags=item.tags,
                context=item.context,
                timestamp=item.timestamp,
                metadata={"was": was_unknown_id},
                entities=item.entities,
            )
        await self.submit(item)

    async def submit_thought(self, text: str, *, person_id: str | None = None) -> None:
        """Buffer a distilled private thought worth keeping."""
        await self.submit(_tagged(text, TAG_THOUGHT, person_id))

    async def digest_session(self, summary: str, *, person_ids: tuple[str, ...] = ()) -> None:
        """Retain a session digest immediately and flush; digests power week-scale callbacks."""
        tags = (TAG_SESSION_DIGEST, *(person_tag(person_id) for person_id in person_ids))
        await self.submit(MemoryItem(content=summary, tags=tags, context="session digest"))
        await self.flush()

    async def flush(self) -> None:
        """Retain the buffer (and replay the spool first); spool everything on outage."""
        items, self._buffer = self._buffer, []
        try:
            pending = self._spool.read(self.bank_id)
            if pending:
                await self._client.retain(self.bank_id, pending)
                self._spool.clear(self.bank_id)
                logger.info("Replayed %s spooled memories into %s", len(pending), self.bank_id)
            if items:
                await self._client.retain(self.bank_id, items)
        except HindsightError as exc:
            self._degraded = True
            self._spool.append(self.bank_id, items)
            logger.warning("Hindsight retain failed; spooled %s items: %s", len(items), exc)
            return
        self._degraded = False

    async def recall_about(self, person_id: str, query: str | None = None, *, limit: int = 5) -> list[RecalledFact]:
        """Recall facts about one person; falls back to spool search during outages."""
        text = query or "what this person is working on, cares about, and recent events in their life"
        try:
            facts = await self._client.recall(
                self.bank_id,
                text,
                tags=(person_tag(person_id),),
                tags_match="any_strict",
                max_tokens=max(1024, limit * 256),
            )
            self._degraded = False
            return facts[:limit]
        except HindsightError as exc:
            self._degraded = True
            logger.warning("Recall failed; searching spool instead: %s", exc)
            return [
                RecalledFact(
                    fact_id="",
                    text=item.content,
                    fact_type="spooled",
                    tags=item.tags,
                    context=item.context,
                    occurred_start=None,
                    occurred_end=None,
                    mentioned_at=None,
                )
                for item in self._spool.search(self.bank_id, text, limit=limit)
            ]

    async def relationship_prompt(self, person_id: str, *, display_name: str | None = None, max_facts: int = 6) -> str:
        """Render remembered facts about a person as a block for session instructions."""
        facts = await self.recall_about(person_id, limit=max_facts)
        if not facts:
            return ""
        name = display_name or person_id
        lines = [f"What you remember about {name} (long-term memory):"]
        now = time.time()
        for fact in facts:
            lines.append(f"- {clean_fact_text(fact.text)} ({human_age(fact_age_days(fact, now))})")
        return "\n".join(lines)

    async def suggest_callbacks(
        self,
        person_id: str,
        *,
        display_name: str | None = None,
        limit: int = 3,
    ) -> list[CallbackCandidate]:
        """Suggest follow-up questions grounded in this person's past memories.

        Reflect phrasing is tried first; when reflect is unavailable or returns
        nothing usable, deterministic instruction-shaped hints are built from the
        facts instead, so callbacks survive a flaky server-side LLM.
        """
        name = display_name or person_id
        facts = await self.recall_about(
            person_id,
            f"recent activities, projects, plans, frustrations, and habits of {name}",
            limit=8,
        )
        now = time.time()
        aged = [(fact, fact_age_days(fact, now)) for fact in facts]
        candidates = [(fact, age) for fact, age in aged if age >= _CALLBACK_MIN_AGE_DAYS] or aged
        candidates = candidates[:limit]
        if not candidates:
            return []

        questions = await self._reflect_questions(name, candidates, limit)
        if questions:
            return [
                CallbackCandidate(
                    fact_text=clean_fact_text(fact.text),
                    days_since=age,
                    question=question,
                    origin="reflect",
                )
                for (fact, age), question in zip(candidates, questions)
            ]
        return [
            CallbackCandidate(
                fact_text=clean_fact_text(fact.text),
                days_since=age,
                question=f'Ask {name} how it turned out: "{clean_fact_text(fact.text)}" ({human_age(age)}).',
                origin="template",
            )
            for fact, age in candidates
        ]

    async def recurring_entities(self, *, min_mentions: int = 2) -> list[MemoryEntity]:
        """List entities mentioned at least min_mentions times (recurring people/projects)."""
        try:
            entities = await self._client.entities(self.bank_id)
            self._degraded = False
        except HindsightError as exc:
            self._degraded = True
            logger.warning("Entity listing failed: %s", exc)
            return []
        return [entity for entity in entities if entity.mention_count >= min_mentions]

    async def close(self) -> None:
        """Flush pending writes and close the HTTP client."""
        await self.flush()
        await self._client.close()

    async def _reflect_questions(self, name: str, candidates: list[tuple[RecalledFact, int]], limit: int) -> list[str]:
        """Ask Hindsight reflect to phrase callback questions; [] on any failure."""
        numbered = "\n".join(
            f"{index}. {clean_fact_text(fact.text)} ({human_age(age)})"
            for index, (fact, age) in enumerate(candidates, start=1)
        )
        prompt = (
            f"You are the long-term memory of a desktop companion robot. "
            f"Here is what you remember about {name}:\n\n{numbered}\n\n"
            f"Suggest up to {limit} short follow-up questions the robot could ask {name} now, "
            "each about one concrete item above — how it turned out, or what happened since. "
            "Reply with one question per line and nothing else."
        )
        try:
            # Facts are inlined in the prompt, so no tag scoping is needed here;
            # the answer stays grounded even if retrieval inside reflect misfires.
            text = await self._client.reflect(self.bank_id, prompt, budget="low")
        except HindsightError as exc:
            logger.warning("Reflect failed; using template callbacks: %s", exc)
            return []
        return parse_questions(text, limit)


def _tagged(
    text: str,
    kind: str,
    person_id: str | None,
    *,
    context: str | None = None,
    entities: tuple[str, ...] = (),
) -> MemoryItem:
    """Build a timestamped MemoryItem with the kind tag and optional person tag."""
    tags = (kind, person_tag(person_id)) if person_id else (kind,)
    return MemoryItem(content=text, tags=tags, context=context, timestamp=time.time(), entities=entities)


def clean_fact_text(text: str) -> str:
    """Strip Hindsight's ' | When: ... | Involving: ...' decorations from fact text."""
    return text.split(" | ")[0].strip().rstrip(".")


def fact_age_days(fact: RecalledFact, now: float) -> int:
    """Return whole days since the fact occurred (mentioned_at as fallback)."""
    for raw in (fact.occurred_start, fact.mentioned_at):
        if not raw:
            continue
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.fromtimestamp(now, timezone.utc) - moment).total_seconds() // 86400))
    return 0


def human_age(days: int) -> str:
    """Render a day count as natural language ('yesterday', 'last week', ...)."""
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "last week"
    if days < 31:
        return f"{days // 7} weeks ago"
    if days < 62:
        return "last month"
    return f"{days // 30} months ago"


def parse_questions(text: str, limit: int) -> list[str]:
    """Extract one-question-per-line from reflect markdown; junk-tolerant."""
    questions: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"^\d+[.)]\s*", "", raw.strip().lstrip("-*• ").strip()).strip().strip('"')
        if not line or "?" not in line or "{" in line or "}" in line:
            continue
        if len(line) > _MAX_CALLBACK_QUESTION_CHARS:
            continue
        questions.append(line)
        if len(questions) >= limit:
            break
    return questions
