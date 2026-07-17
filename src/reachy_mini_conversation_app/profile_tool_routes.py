"""FastAPI routes for per-personality toolset settings."""

import asyncio
import logging
from pathlib import Path
from collections.abc import Callable

from fastapi import Query, FastAPI
from pydantic import BaseModel
from fastapi.responses import JSONResponse

from reachy_mini_conversation_app.config import LOCKED_PROFILE, config
from reachy_mini_conversation_app.personality import AvailableTool, list_personalities, available_tool_catalog
from reachy_mini_conversation_app.profile_store import (
    normalize_tool_names,
    canonical_profile_name,
    profile_directory_has_definition,
)
from reachy_mini_conversation_app.tool_settings import RestartCallback, error_response, apply_tool_change
from reachy_mini_conversation_app.profile_toolsets import (
    read_profile_tool_override,
    clear_profile_tool_override,
    write_profile_tool_override,
    read_profile_default_tool_names,
)


logger = logging.getLogger(__name__)


class UpdateProfileToolsPayload(BaseModel):
    """Body of the profile-toolset update endpoint."""

    profile: str
    enabled_tools: list[str]


def _known_profile_names() -> list[str]:
    profile_names = [canonical_profile_name(profile) for profile in list_personalities()]
    active_profile = canonical_profile_name(config.REACHY_MINI_CUSTOM_PROFILE)
    if active_profile not in profile_names and profile_directory_has_definition(
        config.resolve_profile_dir(active_profile)
    ):
        profile_names.append(active_profile)
    return sorted(set(profile_names), key=lambda profile: (profile != "default", profile))


def _validated_profile(profile: str | None, known_profile_names: list[str]) -> str:
    profile_name = canonical_profile_name(profile)
    if profile_name not in known_profile_names:
        raise ValueError(f"Unknown personality: {profile_name}")
    return profile_name


def _profile_tool_payload(
    profile_name: str,
    known_profile_names: list[str],
    available_tools: list[AvailableTool],
    enabled_tools: list[str],
    *,
    overridden: bool,
) -> dict[str, object]:
    active_profile = canonical_profile_name(config.REACHY_MINI_CUSTOM_PROFILE)
    available_ids = {tool["id"] for tool in available_tools}
    return {
        "profile": profile_name,
        "is_active": profile_name == active_profile,
        "overridden": overridden,
        "editable": LOCKED_PROFILE is None,
        "profiles": [
            {"id": known_profile, "active": known_profile == active_profile} for known_profile in known_profile_names
        ],
        "enabled_tools": enabled_tools,
        "available_tools": available_tools,
        "unavailable_enabled_tools": [tool_id for tool_id in enabled_tools if tool_id not in available_ids],
    }


def mount_profile_tool_routes(
    app: FastAPI,
    get_loop: Callable[[], asyncio.AbstractEventLoop | None],
    restart_conversation: RestartCallback,
    *,
    instance_path: str | Path | None,
    api_prefix: str | None = None,
) -> None:
    """Register per-personality toolset endpoints on a FastAPI app."""
    route_path = f"{(api_prefix or '').rstrip('/')}/profile_tools"

    @app.get(route_path)
    def _get_profile_tools(profile: str | None = Query(None)) -> JSONResponse:
        try:
            known_profile_names = _known_profile_names()
            profile_name = _validated_profile(profile or config.REACHY_MINI_CUSTOM_PROFILE, known_profile_names)
            override = read_profile_tool_override(profile_name, instance_path)
            enabled_tools = list(override) if override is not None else read_profile_default_tool_names(profile_name)
            return JSONResponse(
                _profile_tool_payload(
                    profile_name,
                    known_profile_names,
                    available_tool_catalog(),
                    enabled_tools,
                    overridden=override is not None,
                )
            )
        except ValueError as exc:
            return error_response("unknown_profile", str(exc), 404)
        except Exception as exc:
            logger.exception("Failed to read profile tools for %r", profile)
            return error_response("profile_tools_unavailable", str(exc), 500)

    @app.put(route_path)
    def _update_profile_tools(payload: UpdateProfileToolsPayload) -> JSONResponse:
        if LOCKED_PROFILE is not None:
            return error_response("profile_locked", "Personality tool editing is locked.", 403)
        try:
            known_profile_names = _known_profile_names()
            profile_name = _validated_profile(payload.profile, known_profile_names)
            current_override = read_profile_tool_override(profile_name, instance_path)
            default_tools = read_profile_default_tool_names(profile_name)
            current_tools = list(current_override) if current_override is not None else list(default_tools)
            available_tools = available_tool_catalog()
            available_ids = {tool["id"] for tool in available_tools}
            enabled_tools = normalize_tool_names(payload.enabled_tools)
            unknown_tools = sorted(set(enabled_tools) - available_ids - set(current_tools))
            if unknown_tools:
                return error_response(
                    "invalid_tool_selection",
                    f"Unknown tools for '{profile_name}': {', '.join(unknown_tools)}",
                    400,
                )
            write_profile_tool_override(profile_name, enabled_tools, instance_path)
            is_active = profile_name == canonical_profile_name(config.REACHY_MINI_CUSTOM_PROFILE)
            apply_detail = (
                apply_tool_change(
                    instance_path,
                    get_loop,
                    restart_conversation,
                    "profile_tools_changed",
                )
                if is_active
                else "The tools will apply next time this personality is selected."
            )
            response = _profile_tool_payload(
                profile_name,
                known_profile_names,
                available_tools,
                enabled_tools,
                overridden=True,
            )
            response["message"] = f"Saved tools for {profile_name}. {apply_detail}"
            return JSONResponse(response)
        except ValueError as exc:
            return error_response("unknown_profile", str(exc), 404)
        except Exception as exc:
            logger.exception("Failed to save profile tools for %r", payload.profile)
            return error_response("profile_tools_save_failed", str(exc), 500)

    @app.delete(route_path)
    def _reset_profile_tools(profile: str = Query(...)) -> JSONResponse:
        if LOCKED_PROFILE is not None:
            return error_response("profile_locked", "Personality tool editing is locked.", 403)
        try:
            known_profile_names = _known_profile_names()
            profile_name = _validated_profile(profile, known_profile_names)
            default_tools = read_profile_default_tool_names(profile_name)
            available_tools = available_tool_catalog()
            cleared = clear_profile_tool_override(profile_name, instance_path)
            is_active = profile_name == canonical_profile_name(config.REACHY_MINI_CUSTOM_PROFILE)
            apply_detail = (
                apply_tool_change(
                    instance_path,
                    get_loop,
                    restart_conversation,
                    "profile_tools_changed",
                )
                if cleared and is_active
                else "The tools will apply next time this personality is selected."
            )
            response = _profile_tool_payload(
                profile_name,
                known_profile_names,
                available_tools,
                default_tools,
                overridden=False,
            )
            response["message"] = f"Restored profile defaults for {profile_name}. {apply_detail}"
            return JSONResponse(response)
        except ValueError as exc:
            return error_response("unknown_profile", str(exc), 404)
        except Exception as exc:
            logger.exception("Failed to reset profile tools for %r", profile)
            return error_response("profile_tools_reset_failed", str(exc), 500)
