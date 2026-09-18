"""Tests for the enroll_person tool."""

from unittest.mock import MagicMock

import pytest

from reachy_desktop_buddy.tools.core_tools import ToolDependencies
from reachy_desktop_buddy.tools.enroll_person import EnrollPerson


@pytest.mark.asyncio
async def test_enroll_person_saves_the_current_face() -> None:
    """The tool forwards a name to the running buddy session."""
    session = MagicMock()
    session.enroll_person.return_value = True
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock(), buddy_session=session)

    result = await EnrollPerson()(deps, name="Jon")

    assert result == {"enrolled": "Jon"}
    session.enroll_person.assert_called_once_with("Jon")


@pytest.mark.asyncio
async def test_enroll_person_errors_when_buddy_is_off() -> None:
    """Without a sidecar there is nothing to enroll into."""
    deps = ToolDependencies(reachy_mini=MagicMock(), movement_manager=MagicMock())
    result = await EnrollPerson()(deps, name="Jon")
    assert "error" in result
