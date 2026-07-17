"""FastAPI routes for managing installed Hugging Face Space tools."""

import asyncio
import logging
from pathlib import Path
from collections.abc import Callable

from fastapi import Query, FastAPI
from pydantic import BaseModel
from fastapi.responses import JSONResponse

from reachy_mini_conversation_app.config import LOCKED_PROFILE, config
from reachy_mini_conversation_app.tool_spaces import (
    ToolSpaceNotInstalledError,
    InstalledToolSpacesManifest,
    ToolSpaceAliasConflictError,
    ToolSpaceProfileUpdateError,
    remove_tool_space,
    install_tool_space,
    read_installed_tool_spaces,
)
from reachy_mini_conversation_app.profile_store import canonical_profile_name
from reachy_mini_conversation_app.tool_settings import RestartCallback, error_response, apply_tool_change
from reachy_mini_conversation_app.profile_toolsets import read_profile_tool_names


logger = logging.getLogger(__name__)


class AddToolSpacePayload(BaseModel):
    """Body of the add-tool-Space endpoint."""

    slug: str


def _space_settings_payload(manifest: InstalledToolSpacesManifest) -> dict[str, object]:
    return {
        "spaces": [
            {
                "slug": space.slug,
                "private": space.private,
                "tool_count": len(space.tools),
            }
            for space in sorted(manifest.spaces, key=lambda installed_space: installed_space.slug)
        ],
        "editable": LOCKED_PROFILE is None,
    }


def _error_detail(error: BaseException) -> str:
    return str(error).strip() or type(error).__name__


def mount_tool_space_routes(
    app: FastAPI,
    get_loop: Callable[[], asyncio.AbstractEventLoop | None],
    restart_conversation: RestartCallback,
    *,
    instance_path: str | Path | None,
    api_prefix: str | None = None,
) -> None:
    """Register Hugging Face Space tool-management endpoints on a FastAPI app."""
    route_path = f"{(api_prefix or '').rstrip('/')}/tool_spaces"

    @app.get(route_path)
    async def _list_tool_spaces() -> JSONResponse:
        try:
            manifest = await asyncio.to_thread(read_installed_tool_spaces, instance_path)
        except Exception as exc:
            logger.exception("Failed to list installed tool Spaces")
            return error_response("tool_spaces_unavailable", _error_detail(exc), 500)
        return JSONResponse(_space_settings_payload(manifest))

    @app.post(route_path)
    async def _add_tool_space(payload: AddToolSpacePayload) -> JSONResponse:
        if LOCKED_PROFILE is not None:
            return error_response("profile_locked", "Tool Space editing is locked.", 403)
        try:
            result = await asyncio.to_thread(
                install_tool_space,
                payload.slug,
                instance_path,
                install_only=True,
            )
        except ToolSpaceAliasConflictError as exc:
            logger.warning("Tool Space alias conflict: %s", exc)
            return error_response("tool_space_alias_conflict", _error_detail(exc), 409)
        except ValueError as exc:
            logger.warning("Invalid tool Space slug %r: %s", payload.slug, exc)
            return error_response("invalid_tool_space_slug", _error_detail(exc), 400)
        except RuntimeError as exc:
            logger.error("Failed to install tool Space %r: %s", payload.slug, exc)
            return error_response("tool_space_install_failed", _error_detail(exc), 502)
        except Exception as exc:
            logger.exception("Unexpected failure installing tool Space %r", payload.slug)
            return error_response("tool_space_install_failed", _error_detail(exc), 500)

        active_profile = canonical_profile_name(config.REACHY_MINI_CUSTOM_PROFILE)
        try:
            active_tools = read_profile_tool_names(active_profile, instance_path)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            logger.warning("Installed Tool Space but could not inspect active profile %r: %s", active_profile, exc)
            active_tools = []
        apply_detail = (
            apply_tool_change(
                instance_path,
                get_loop,
                restart_conversation,
                "tool_spaces_changed",
            )
            if any(tool_name.startswith(f"{result.resolved_space.alias}__") for tool_name in active_tools)
            else "The Space is ready to assign to personalities."
        )

        action = "Refreshed" if result.refreshed else "Installed"
        tool_count = len(result.resolved_space.tools)
        tool_label = "tool" if tool_count == 1 else "tools"
        message = (
            f"{action} {result.resolved_space.slug} with {tool_count} {tool_label}. "
            "Choose which personalities can use them in Tool access. "
            f"{apply_detail}"
        )
        return JSONResponse(
            {
                **_space_settings_payload(result.manifest),
                "message": message,
            }
        )

    @app.delete(route_path)
    async def _remove_tool_space(slug: str = Query(...)) -> JSONResponse:
        if LOCKED_PROFILE is not None:
            return error_response("profile_locked", "Tool Space editing is locked.", 403)
        try:
            result = await asyncio.to_thread(remove_tool_space, slug, instance_path)
            disabled_profiles = result.disabled_profiles
        except ToolSpaceNotInstalledError as exc:
            logger.warning("Cannot remove tool Space %r: %s", slug, exc)
            return error_response("tool_space_not_installed", _error_detail(exc), 404)
        except ToolSpaceProfileUpdateError as exc:
            logger.error("Failed to disable removed tool Space: %s", exc)
            return error_response("profile_disable_failed", _error_detail(exc), 500)
        except ValueError as exc:
            logger.warning("Invalid tool Space slug %r: %s", slug, exc)
            return error_response("invalid_tool_space_slug", _error_detail(exc), 400)
        except RuntimeError as exc:
            logger.error("Failed to remove tool Space %r: %s", slug, exc)
            return error_response("tool_space_remove_failed", _error_detail(exc), 500)
        except Exception as exc:
            logger.exception("Unexpected failure removing tool Space %r", slug)
            return error_response("tool_space_remove_failed", _error_detail(exc), 500)

        active_profile = canonical_profile_name(config.REACHY_MINI_CUSTOM_PROFILE)
        apply_detail = (
            apply_tool_change(
                instance_path,
                get_loop,
                restart_conversation,
                "tool_spaces_changed",
            )
            if any(profile_name == active_profile for profile_name, _ in disabled_profiles)
            else "No active conversation restart is needed."
        )

        disabled_tool_count = sum(len(tool_ids) for _, tool_ids in disabled_profiles)
        tool_label = "tool" if disabled_tool_count == 1 else "tools"
        message = (
            f"Removed {result.removed_space.slug}. Disabled {disabled_tool_count} {tool_label} across personalities. "
            f"{apply_detail}"
        )
        return JSONResponse(
            {
                **_space_settings_payload(result.manifest),
                "message": message,
            }
        )
