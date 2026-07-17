"""Tests for Hugging Face Space and profile-tool management routes."""

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reachy_mini_conversation_app.config import DEFAULT_PROFILES_DIRECTORY, config
from reachy_mini_conversation_app.tool_spaces import (
    InstalledToolSpaceTool,
    ResolvedInstalledToolSpace,
    InstalledToolSpacesManifest,
    read_installed_tool_spaces,
    write_installed_tool_spaces,
)
from reachy_mini_conversation_app.profile_store import write_profile
from reachy_mini_conversation_app.profile_toolsets import (
    read_profile_tool_names,
    read_profile_tool_override,
)
from reachy_mini_conversation_app.tool_space_routes import mount_tool_space_routes
from reachy_mini_conversation_app.profile_tool_routes import mount_profile_tool_routes


SPACE_SLUG = "example/search-tool"
SPACE_ALIAS = "example_search_tool"
TOOL_NAME = f"{SPACE_ALIAS}__search_web"


def _resolved_space() -> ResolvedInstalledToolSpace:
    return ResolvedInstalledToolSpace(
        slug=SPACE_SLUG,
        alias=SPACE_ALIAS,
        mcp_url="https://example-search-tool.hf.space/gradio_api/mcp/",
        private=False,
        tools=[
            InstalledToolSpaceTool(
                local_name=TOOL_NAME,
                client_tool_name=f"{SPACE_ALIAS}__search_tool_search_web",
                remote_name="search_tool_search_web",
                description="Search the web",
                parameters_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ],
    )


def _configure_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    instance_path = tmp_path / "instance"
    profiles_root = tmp_path / "profiles"
    write_profile("default", profiles_root / "default", "Default profile.", ["dance"])
    write_profile("guide", profiles_root / "guide", "Guide profile.", ["camera"])
    write_installed_tool_spaces(instance_path, InstalledToolSpacesManifest(spaces=[]))
    monkeypatch.setattr(config, "INSTANCE_PATH", instance_path)
    monkeypatch.setattr(config, "PROFILES_DIRECTORY", profiles_root)
    monkeypatch.setattr("reachy_mini_conversation_app.profile_store.DEFAULT_PROFILES_DIRECTORY", profiles_root)
    monkeypatch.setattr(config, "REACHY_MINI_CUSTOM_PROFILE", None)
    monkeypatch.setattr(
        "reachy_mini_conversation_app.tool_spaces.resolve_tool_space_sync",
        lambda slug: _resolved_space(),
    )
    return instance_path, profiles_root


def _mount_routes(
    instance_path: Path,
    get_loop: MagicMock,
    restart_conversation: AsyncMock,
) -> TestClient:
    app = FastAPI()
    mount_tool_space_routes(
        app,
        get_loop,
        restart_conversation,
        instance_path=instance_path,
        api_prefix="/api/v1",
    )
    mount_profile_tool_routes(
        app,
        get_loop,
        restart_conversation,
        instance_path=instance_path,
        api_prefix="/api/v1",
    )
    return TestClient(app)


def test_web_install_adds_global_inventory_without_enabling_a_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installing from the web should make tools available without granting profile access."""
    instance_path, profiles_root = _configure_profiles(tmp_path, monkeypatch)
    default_profile_text = (profiles_root / "default" / "profile.md").read_text(encoding="utf-8")
    initialize_tools = MagicMock()
    monkeypatch.setattr("reachy_mini_conversation_app.tool_settings.initialize_tools", initialize_tools)
    restart_conversation = AsyncMock()
    client = _mount_routes(instance_path, MagicMock(return_value=None), restart_conversation)

    response = client.post("/api/v1/tool_spaces", json={"slug": SPACE_SLUG})

    assert response.status_code == 200
    added = response.json()
    assert added["spaces"] == [{"slug": SPACE_SLUG, "private": False, "tool_count": 1}]
    assert added["editable"] is True
    assert "ready to assign to personalities" in added["message"]
    assert read_profile_tool_override("default", instance_path) is None
    assert (profiles_root / "default" / "profile.md").read_text(encoding="utf-8") == default_profile_text
    initialize_tools.assert_not_called()
    restart_conversation.assert_not_called()

    profile_response = client.get("/api/v1/profile_tools", params={"profile": "default"})
    profile_tools = profile_response.json()
    assert profile_tools["enabled_tools"] == ["dance"]
    assert TOOL_NAME in {tool["id"] for tool in profile_tools["available_tools"]}
    assert client.get("/api/v1/tool_spaces").json() == {"spaces": added["spaces"], "editable": True}


def test_preinstalled_space_tools_are_available_to_every_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bundled Space inventory should be selectable without leaking default-profile access."""
    monkeypatch.setattr(config, "INSTANCE_PATH", tmp_path)
    monkeypatch.setattr(config, "PROFILES_DIRECTORY", DEFAULT_PROFILES_DIRECTORY)
    monkeypatch.setattr(config, "REACHY_MINI_CUSTOM_PROFILE", "mars_rover")
    client = _mount_routes(tmp_path, MagicMock(return_value=None), AsyncMock())

    response = client.get("/api/v1/profile_tools", params={"profile": "mars_rover"})

    assert response.status_code == 200
    payload = response.json()
    available_ids = {tool["id"] for tool in payload["available_tools"]}
    preinstalled_tool_ids = {
        "pollen_robotics_reachy_mini_search_tool__search_web",
        "pollen_robotics_reachy_mini_weather_tool__get_weather",
        "pollen_robotics_reachy_mini_time_tool__get_time",
    }
    assert preinstalled_tool_ids <= available_ids
    assert preinstalled_tool_ids.isdisjoint(payload["enabled_tools"])


def test_profile_tools_put_and_delete_control_one_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Profile-tool updates should persist independently and reset to authored defaults."""
    instance_path, profiles_root = _configure_profiles(tmp_path, monkeypatch)
    guide_profile_text = (profiles_root / "guide" / "profile.md").read_text(encoding="utf-8")
    initialize_tools = MagicMock()
    monkeypatch.setattr("reachy_mini_conversation_app.tool_settings.initialize_tools", initialize_tools)
    client = _mount_routes(instance_path, MagicMock(return_value=None), AsyncMock())
    assert client.post("/api/v1/tool_spaces", json={"slug": SPACE_SLUG}).status_code == 200

    update_response = client.put(
        "/api/v1/profile_tools",
        json={"profile": "guide", "enabled_tools": ["camera", TOOL_NAME, TOOL_NAME]},
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["profile"] == "guide"
    assert updated["is_active"] is False
    assert updated["overridden"] is True
    assert updated["enabled_tools"] == ["camera", TOOL_NAME]
    assert "next time this personality is selected" in updated["message"]
    assert read_profile_tool_names("default", instance_path) == ["dance"]
    assert (profiles_root / "guide" / "profile.md").read_text(encoding="utf-8") == guide_profile_text
    initialize_tools.assert_not_called()

    reset_response = client.delete("/api/v1/profile_tools", params={"profile": "guide"})

    assert reset_response.status_code == 200
    reset = reset_response.json()
    assert reset["overridden"] is False
    assert reset["enabled_tools"] == ["camera"]
    assert "next time this personality is selected" in reset["message"]
    assert read_profile_tool_override("guide", instance_path) is None
    initialize_tools.assert_not_called()


def test_remove_tool_space_disables_its_tools_in_every_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing a Space should clean its tool IDs from every profile selection."""
    instance_path, _ = _configure_profiles(tmp_path, monkeypatch)
    initialize_tools = MagicMock()
    monkeypatch.setattr("reachy_mini_conversation_app.tool_settings.initialize_tools", initialize_tools)
    client = _mount_routes(instance_path, MagicMock(return_value=None), AsyncMock())
    assert client.post("/api/v1/tool_spaces", json={"slug": SPACE_SLUG}).status_code == 200
    assert (
        client.put(
            "/api/v1/profile_tools",
            json={"profile": "default", "enabled_tools": ["dance", TOOL_NAME]},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/v1/profile_tools",
            json={"profile": "guide", "enabled_tools": ["camera", TOOL_NAME]},
        ).status_code
        == 200
    )
    initialize_tools.reset_mock()

    remove_response = client.delete("/api/v1/tool_spaces", params={"slug": SPACE_SLUG})

    assert remove_response.status_code == 200
    removed = remove_response.json()
    assert removed["spaces"] == []
    assert "Disabled 2 tools across personalities" in removed["message"]
    assert read_profile_tool_names("default", instance_path) == ["dance"]
    assert read_profile_tool_names("guide", instance_path) == ["camera"]
    initialize_tools.assert_called_once_with(instance_path=instance_path, force=True)
    assert read_installed_tool_spaces(instance_path).spaces == []


def test_add_tool_space_rejects_invalid_slug_without_network_access(tmp_path: Path) -> None:
    """The UI route should only accept Hugging Face owner/Space slugs."""
    app = FastAPI()
    mount_tool_space_routes(
        app,
        lambda: None,
        AsyncMock(),
        instance_path=tmp_path,
        api_prefix="/api/v1",
    )

    response = TestClient(app).post("/api/v1/tool_spaces", json={"slug": "https://example.com/mcp"})

    assert response.status_code == 400
    assert set(response.json()) == {"error", "detail"}
    assert response.json()["error"] == "invalid_tool_space_slug"


def test_locked_mode_exposes_inventory_but_rejects_tool_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Locked variants should keep tool settings visible and make every mutation read-only."""
    instance_path, _ = _configure_profiles(tmp_path, monkeypatch)
    monkeypatch.setattr("reachy_mini_conversation_app.tool_space_routes.LOCKED_PROFILE", "default")
    monkeypatch.setattr("reachy_mini_conversation_app.profile_tool_routes.LOCKED_PROFILE", "default")
    client = _mount_routes(instance_path, MagicMock(return_value=None), AsyncMock())

    assert client.get("/api/v1/tool_spaces").json()["editable"] is False
    assert client.get("/api/v1/profile_tools", params={"profile": "default"}).json()["editable"] is False
    assert client.post("/api/v1/tool_spaces", json={"slug": SPACE_SLUG}).status_code == 403
    assert client.delete("/api/v1/tool_spaces", params={"slug": SPACE_SLUG}).status_code == 403
    assert (
        client.put(
            "/api/v1/profile_tools",
            json={"profile": "default", "enabled_tools": []},
        ).status_code
        == 403
    )
    assert client.delete("/api/v1/profile_tools", params={"profile": "default"}).status_code == 403


def test_active_profile_tool_update_restarts_a_running_conversation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing active profile tools should reconnect the running conversation."""
    instance_path, _ = _configure_profiles(tmp_path, monkeypatch)
    monkeypatch.setattr("reachy_mini_conversation_app.tool_settings.initialize_tools", MagicMock())
    conversation_loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=conversation_loop.run_forever)
    loop_thread.start()
    restart_called = threading.Event()

    async def _restart_conversation(reason: str) -> None:
        assert reason == "profile_tools_changed"
        restart_called.set()

    try:
        app = FastAPI()
        mount_tool_space_routes(
            app,
            lambda: conversation_loop,
            _restart_conversation,
            instance_path=instance_path,
            api_prefix="/api/v1",
        )
        mount_profile_tool_routes(
            app,
            lambda: conversation_loop,
            _restart_conversation,
            instance_path=instance_path,
            api_prefix="/api/v1",
        )
        client = TestClient(app)
        assert client.post("/api/v1/tool_spaces", json={"slug": SPACE_SLUG}).status_code == 200

        response = client.put(
            "/api/v1/profile_tools",
            json={"profile": "default", "enabled_tools": ["dance", TOOL_NAME]},
        )

        assert response.status_code == 200
        assert "Reconnecting the conversation" in response.json()["message"]
        assert restart_called.wait(timeout=1.0)
    finally:
        conversation_loop.call_soon_threadsafe(conversation_loop.stop)
        loop_thread.join(timeout=1.0)
        conversation_loop.close()


def test_saved_tool_change_reports_success_when_runtime_reload_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted selection should not be reported as a failed save when live reload fails."""
    instance_path, _ = _configure_profiles(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "reachy_mini_conversation_app.tool_settings.initialize_tools",
        MagicMock(side_effect=RuntimeError("reload failed")),
    )
    client = _mount_routes(instance_path, MagicMock(return_value=None), AsyncMock())

    response = client.put(
        "/api/v1/profile_tools",
        json={"profile": "default", "enabled_tools": ["dance"]},
    )

    assert response.status_code == 200
    assert "Restart the conversation app" in response.json()["message"]
    assert read_profile_tool_override("default", instance_path) == ["dance"]
