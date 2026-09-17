from importlib.metadata import entry_points

import reachy_mini_conversation_fleming
from reachy_mini_conversation_fleming.main import ReachyMiniConversationApp


def test_package_imports_as_fleming() -> None:
    """This fork must import as reachy_mini_conversation_fleming, not the pollen package name."""
    assert reachy_mini_conversation_fleming.__name__ == "reachy_mini_conversation_fleming"


def test_reachy_mini_apps_registers_fleming_entry_point() -> None:
    """Control discovers this app under the Fleming reachy_mini_apps entry-point name."""
    apps = {ep.name: ep for ep in entry_points(group="reachy_mini_apps")}

    assert "reachy_mini_conversation_fleming" in apps
    assert apps["reachy_mini_conversation_fleming"].load() is ReachyMiniConversationApp
