"""Render the Important / Other / Older index from memory frontmatters.

Input: a list of memory summaries (as produced by ``MemoryManager.list_memories``).
Output: a markdown string written to ``active_memory.md``.

Tiering is by importance and size, NOT by a fixed time window: pinned memories
are always kept (``Important``); the rest are shown in full newest-first up to a
budget (``Other``); only the overflow beyond that budget is collapsed to ranked
tag counts (``Older topics``). So a long gap between sessions never wipes
memories — only an oversized index does.

See ``docs/memory-system-design.md``.
"""

from __future__ import annotations
from typing import Any
from datetime import datetime, timezone

from reachy_mini_conversation_app.memory.dates import event_date


# Max number of non-pinned memories shown in full (as one-line summaries) before
# the oldest overflow into the collapsed ``Older topics`` tag-count section.
OTHER_LIMIT = 40
OLDER_TAG_LIMIT = 15
_MIN_DATE = datetime.min.replace(tzinfo=timezone.utc)


def _fmt_entry(mem: dict[str, Any]) -> str:
    summary = mem.get("summary") or "(empty memory)"
    return f"- [{mem['id']}] {summary}"


def _group_by_primary_tag(memories: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group memories by first tag; memories without tags go under 'untagged'."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for mem in memories:
        tags = mem.get("tags") or []
        primary = tags[0] if tags else "untagged"
        groups.setdefault(primary, []).append(mem)
    return groups


def _tag_counts(memories: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Return ranked (tag, count) pairs across the given memories."""
    counts: dict[str, int] = {}
    for mem in memories:
        for tag in mem.get("tags") or []:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def render_index(memories: list[dict[str, Any]], limit: int = OTHER_LIMIT) -> str:
    """Render the memory index as markdown.

    Memories are split into three tiers (by importance and size, not age):
      - Important: ``pinned: true``, always kept regardless of age.
      - Other: the newest ``limit`` non-pinned memories, grouped by primary tag.
      - Older topics: the overflow beyond ``limit``, collapsed to ranked tag counts.
    """
    visible = [m for m in memories if not m.get("superseded_by")]

    important = [m for m in visible if m.get("pinned")]
    others = [m for m in visible if not m.get("pinned")]

    # Keep the newest `limit` in full; the oldest overflow collapses to tag counts.
    others.sort(key=lambda m: event_date(m) or _MIN_DATE, reverse=True)
    shown = others[: max(0, limit)]
    older = others[max(0, limit) :]

    lines: list[str] = ["# Memory index", ""]

    lines.append("## Important")
    if important:
        for mem in sorted(important, key=lambda m: m["id"]):
            lines.append(_fmt_entry(mem))
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Other")
    if shown:
        groups = _group_by_primary_tag(shown)
        for tag in sorted(groups):
            lines.append(f"### {tag}")
            for mem in sorted(groups[tag], key=lambda m: event_date(m) or _MIN_DATE):
                lines.append(_fmt_entry(mem))
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Older topics")
    if older:
        counts = _tag_counts(older)
        lines.append("Tags (count), ranked by frequency:")
        truncated: list[tuple[str, int]] = []
        remaining = 0
        if len(counts) > OLDER_TAG_LIMIT:
            truncated = counts[:OLDER_TAG_LIMIT]
            remaining = len(counts) - OLDER_TAG_LIMIT
        else:
            truncated = counts
        for tag, count in truncated:
            lines.append(f"- {tag} ({count})")
        if remaining:
            lines.append(f"- … +{remaining} more tags")
        lines.append("")
        lines.append("Use `recall_memories(tag=...)` to load (also filters by date_from/date_to).")
    else:
        lines.append("(none)")

    return "\n".join(lines).rstrip() + "\n"


def rebuild_index(manager: Any) -> str:
    """Rebuild ``active_memory.md`` from all on-disk memories.

    ``manager`` is a :class:`MemoryManager`. This function is the public
    entry point used by both the dreamer and test code.
    """
    memories = manager.list_memories(include_superseded=False)
    rendered = render_index(memories)
    manager._atomic_write_active(rendered)
    return rendered
