import logging
from typing import Any

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies


logger = logging.getLogger(__name__)


class EnrollPerson(Tool):
    """Enroll the face currently in view under a spoken name."""

    name = "enroll_person"
    description = (
        "Save the face currently in the camera as a named person so they can be recognized later. "
        "Call this when someone tells you their name and they are in front of the camera."
    )
    needs_response = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The person's name, such as Jon.",
            },
        },
        "required": ["name"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        """Enroll the current camera face."""
        name = kwargs.get("name")
        if not isinstance(name, str) or not name.strip():
            return {"error": "name must be a non-empty string"}
        session = deps.buddy_session
        if session is None:
            return {"error": "Buddy presence is not running"}
        display = name.strip()
        if not session.enroll_person(display):
            logger.warning("enroll_person failed for %s", display)
            return {"error": "Could not enroll: no face in view or recognizer unavailable"}
        logger.info("Tool call: enroll_person name=%s", display)
        return {"enrolled": display}
