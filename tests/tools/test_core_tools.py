from typing import Any
from unittest.mock import MagicMock

import pytest

from reachy_desktop_buddy.tools import core_tools
from reachy_desktop_buddy.tools.core_tools import Tool, ToolDependencies, dispatch_tool_call


class _EchoTool(Tool):
    _auto_register = False
    name = "echo"
    description = "echo"
    parameters_schema = {"type": "object", "properties": {}}

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, **kwargs}


def _deps() -> ToolDependencies:
    return ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown tools fail closed instead of raising into the conversation loop."""
    monkeypatch.setattr(core_tools, "get_tools", lambda: {})
    result = await dispatch_tool_call("missing", "{}", _deps())
    assert result == {"error": "unknown tool: missing"}


@pytest.mark.asyncio
async def test_dispatch_tool_call_returns_tool_result(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A registered tool is invoked with the supplied args and logs completion."""
    monkeypatch.setattr(core_tools, "get_tools", lambda: {"echo": _EchoTool()})
    with caplog.at_level("INFO", logger=core_tools.logger.name):
        result = await dispatch_tool_call("echo", '{"message": "hello"}', _deps())
    assert result == {"ok": True, "message": "hello"}
    assert any("Dispatching tool echo" in record.message for record in caplog.records)
    assert any("completed in" in record.message for record in caplog.records)
