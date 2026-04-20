"""System tool: recall_topic — read every memory matching a tag, bounded by ``limit``."""

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 5


class RecallTopic(Tool):
    """Pull every memory carrying a given tag — for broad 'what do you remember about X?' questions."""

    name = "recall_topic"
    description = (
        "Fetch every memory tagged with a given topic. Use this when the user asks a broad "
        "question like 'what do you remember about chess?' rather than referencing one specific "
        "past conversation. Tags are shown in the `## Recent` section of the MEMORY index as "
        "`### <tag>` subheadings, and in the `## Older` section as '<tag> (count)' lines. "
        "Returns up to `limit` memories, newest first."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "tag": {
                "type": "string",
                "description": "The tag to search for (case-sensitive). Required.",
            },
            "limit": {
                "type": "integer",
                "description": f"Max memories to return (default {DEFAULT_LIMIT}).",
            },
        },
        "required": ["tag"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Return up to ``limit`` memories matching ``tag``, newest first."""
        if deps.memory_manager is None:
            return {"status": "memory_disabled"}

        tag = (kwargs.get("tag") or "").strip()
        if not tag:
            return {"error": "tag is required"}
        limit = int(kwargs.get("limit") or DEFAULT_LIMIT)
        limit = max(1, min(limit, 20))

        logger.info("Tool call: recall_topic tag=%r limit=%d", tag, limit)

        manager = deps.memory_manager
        matches = manager.list_memories(tag=tag)
        # Newest first: prefer created, fall back to id.
        matches.sort(key=lambda m: m.get("created") or m["id"], reverse=True)
        bundle = []
        for entry in matches[:limit]:
            try:
                bundle.append(manager.read_memory(entry["id"]))
            except FileNotFoundError:
                logger.warning("recall_topic: indexed memory %s missing on disk", entry["id"])

        return {
            "tag": tag,
            "returned": len(bundle),
            "total_matches": len(matches),
            "memories": bundle,
        }
