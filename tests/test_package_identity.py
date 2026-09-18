from importlib.metadata import entry_points

import reachy_desktop_buddy


def test_package_imports_as_desktop_buddy() -> None:
    """The fork package name must be reachy_desktop_buddy, not the pollen name."""
    assert reachy_desktop_buddy.__name__ == "reachy_desktop_buddy"


def test_reachy_mini_apps_registers_desktop_buddy_entry_point() -> None:
    """Control discovers this app under the reachy_desktop_buddy entry-point name."""
    apps = {ep.name: ep for ep in entry_points(group="reachy_mini_apps")}

    assert "reachy_desktop_buddy" in apps
    assert apps["reachy_desktop_buddy"].value == ("reachy_desktop_buddy.main:ReachyDesktopBuddy")
