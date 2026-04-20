"""System tool: short_term_memory — read the whole current session log."""

import logging
from typing import Any, Dict

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class ShortTermMemory(Tool):
    """Re-read the live session log when context has slipped out of the model's window."""

    name = "short_term_memory"
    description = (
        "Return the complete transcript of the current session so far. Use this when the "
        "user refers back to something said earlier in this very conversation that you no "
        "longer remember (long sessions get truncated from your context). The tool returns "
        "the raw log — you decide what matters. No arguments."
    )
    parameters_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Return the current session log as a single string."""
        if deps.memory_manager is None:
            return {"status": "memory_disabled"}

        logger.info("Tool call: short_term_memory")
        content = deps.memory_manager.read_current_session_log()
        return {"content": content, "length_chars": len(content)}
