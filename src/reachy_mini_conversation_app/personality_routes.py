"""FastAPI routes for personality and voice management.

Exposes REST endpoints on the provided FastAPI app. Backend actions
(apply personality, fetch voices) are scheduled onto the running
LocalStream asyncio loop via the supplied get_loop callable.
"""

import asyncio
import logging
from collections.abc import Callable, Awaitable

from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import JSONResponse

from reachy_mini_conversation_app.config import (
    LOCKED_PROFILE,
    config,
    get_default_voice,
    get_available_voices,
)
from reachy_mini_conversation_app.personality import (
    delete_personality,
    list_personalities,
    save_user_personality,
)
from reachy_mini_conversation_app.profile_store import (
    DEFAULT_PROFILE_NAME,
    ProfileFormatError,
    read_profile,
    canonical_profile_name,
)
from reachy_mini_conversation_app.conversation_handler import ConversationHandler


logger = logging.getLogger(__name__)


class ApplyPayload(BaseModel):
    """Body of the apply-personality endpoint."""

    name: str
    persist: bool = False


class SavePayload(BaseModel):
    """Body of the save-personality endpoint."""

    name: str
    instructions: str
    voice: str | None = None
    greeting: str | None = None
    overwrite: bool = False


class VoicePayload(BaseModel):
    """Body of the apply-voice endpoint."""

    voice: str


def mount_personality_routes(
    app: FastAPI,
    handler: ConversationHandler,
    get_loop: Callable[[], asyncio.AbstractEventLoop | None],
    *,
    persist_personality: Callable[[str | None, str | None], None] | None = None,
    get_persisted_personality: Callable[[], str | None] | None = None,
    apply_personality: Callable[[str | None], Awaitable[str]] | None = None,
    get_voices: Callable[[], Awaitable[list[str]]] | None = None,
    get_current_voice: Callable[[], str] | None = None,
    change_voice: Callable[[str], Awaitable[str]] | None = None,
    api_prefix: str | None = None,
) -> None:
    """Register personality management endpoints on a FastAPI app."""
    api_prefix = (api_prefix or "").rstrip("/")

    startup_choice = DEFAULT_PROFILE_NAME
    try:
        persisted_personality = get_persisted_personality() if get_persisted_personality is not None else None
        startup_choice = canonical_profile_name(persisted_personality or config.REACHY_MINI_CUSTOM_PROFILE)
    except Exception as exc:
        logger.warning("Failed to read configured startup personality: %s", exc)

    def _startup_choice() -> str:
        """Return the persisted startup personality or default."""
        try:
            if get_persisted_personality is not None:
                stored = get_persisted_personality()
                if stored:
                    return canonical_profile_name(stored)
        except Exception as exc:
            logger.warning("Failed to read persisted startup personality: %s", exc)
        return startup_choice

    def _set_startup_choice(selected_name: str) -> None:
        nonlocal startup_choice
        startup_choice = canonical_profile_name(selected_name)

    def _current_choice() -> str:
        return canonical_profile_name(config.REACHY_MINI_CUSTOM_PROFILE)

    def _voice_override() -> str | None:
        try:
            current_voice_callback = get_current_voice or handler.get_current_voice
            return current_voice_callback()
        except Exception as exc:
            logger.warning("Failed to read current voice override: %s", exc)
            return None

    @app.get(f"{api_prefix}/personalities")
    def _list() -> dict[str, object]:
        return {
            "choices": list_personalities(),
            "current": _current_choice(),
            "startup": _startup_choice(),
            "locked": LOCKED_PROFILE is not None,
            "locked_to": LOCKED_PROFILE,
        }

    @app.get(f"{api_prefix}/personalities/load")
    def _load(name: str) -> JSONResponse:
        try:
            profile = read_profile(name)
        except FileNotFoundError as exc:
            logger.warning("Failed to load profile %r: %s", name, exc)
            return JSONResponse({"error": "profile_unavailable", "detail": str(exc)}, status_code=404)
        except ProfileFormatError as exc:
            logger.warning("Failed to load profile %r: %s", name, exc)
            return JSONResponse({"error": "profile_unavailable", "detail": str(exc)}, status_code=422)
        return JSONResponse(
            {
                "instructions": profile.instructions,
                "greeting": profile.greeting or "",
                "voice": profile.voice or get_default_voice(),
            }
        )

    @app.post(f"{api_prefix}/personalities/save")
    def _save(payload: SavePayload) -> JSONResponse:
        if LOCKED_PROFILE is not None:
            return JSONResponse(
                {"ok": False, "error": "profile_locked", "locked_to": LOCKED_PROFILE},
                status_code=403,
            )
        if not payload.instructions.strip():
            return JSONResponse({"ok": False, "error": "invalid_instructions"}, status_code=400)
        try:
            value = save_user_personality(
                payload.name,
                payload.instructions,
                payload.voice or get_default_voice(),
                payload.greeting,
                overwrite=payload.overwrite,
            )
            return JSONResponse({"ok": True, "value": value, "choices": list_personalities()})
        except FileExistsError:
            return JSONResponse({"ok": False, "error": "profile_exists"}, status_code=409)
        except ProfileFormatError as exc:
            logger.warning("Failed to edit profile %r: %s", payload.name, exc)
            return JSONResponse({"ok": False, "error": "profile_unavailable", "detail": str(exc)}, status_code=422)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": "invalid_name", "detail": str(exc)}, status_code=400)
        except OSError as exc:
            logger.exception("Failed to save personality %r", payload.name)
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.delete(f"{api_prefix}/personalities")
    def _delete(name: str) -> JSONResponse:
        """Delete a user-created personality (name is the full selection string)."""
        if LOCKED_PROFILE is not None:
            return JSONResponse(
                {"ok": False, "error": "profile_locked", "locked_to": LOCKED_PROFILE},
                status_code=403,
            )
        if name in (_current_choice(), _startup_choice()):
            return JSONResponse(
                {"ok": False, "error": "profile_in_use", "choices": list_personalities()},
                status_code=409,
            )
        try:
            deleted = delete_personality(name)
        except OSError as exc:
            logger.exception("Failed to delete personality %r", name)
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
        if not deleted:
            return JSONResponse(
                {"ok": False, "error": "not_deletable", "choices": list_personalities()},
                status_code=404,
            )
        return JSONResponse({"ok": True, "choices": list_personalities()})

    @app.post(f"{api_prefix}/personalities/apply")
    def _apply(payload: ApplyPayload) -> JSONResponse:
        if LOCKED_PROFILE is not None:
            return JSONResponse(
                {"ok": False, "error": "profile_locked", "locked_to": LOCKED_PROFILE},
                status_code=403,
            )
        selected_name = canonical_profile_name(payload.name)
        persist = payload.persist
        persisted_choice = _startup_choice()

        if selected_name == _current_choice():
            if persist and persist_personality is not None:
                try:
                    voice_override = _voice_override()
                    persist_personality(
                        None if selected_name == DEFAULT_PROFILE_NAME else selected_name, voice_override
                    )
                    _set_startup_choice(selected_name)
                    persisted_choice = _startup_choice()
                except Exception as exc:
                    logger.warning("Failed to persist startup personality: %s", exc)
            return JSONResponse(
                {
                    "ok": True,
                    "status": "Personality unchanged.",
                    "startup": persisted_choice,
                }
            )

        loop = get_loop()
        if loop is None:
            return JSONResponse({"ok": False, "error": "loop_unavailable"}, status_code=503)

        async def _do_apply() -> tuple[str, str | None]:
            profile = None if selected_name == DEFAULT_PROFILE_NAME else selected_name
            if apply_personality is not None:
                status = await apply_personality(profile)
            else:
                status = await handler.apply_personality(profile)
            return status, _voice_override()

        try:
            logger.info("apply: requested name=%r", selected_name)
            fut = asyncio.run_coroutine_threadsafe(_do_apply(), loop)
            status, voice_override = fut.result(timeout=10)
            if persist and persist_personality is not None:
                try:
                    persist_personality(
                        None if selected_name == DEFAULT_PROFILE_NAME else selected_name, voice_override
                    )
                    _set_startup_choice(selected_name)
                    persisted_choice = _startup_choice()
                except Exception as exc:
                    logger.warning("Failed to persist startup personality: %s", exc)
            return JSONResponse({"ok": True, "status": status, "startup": persisted_choice})
        except Exception as exc:
            logger.exception("Failed to apply personality %r", selected_name)
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.get(f"{api_prefix}/voices")
    def _voices() -> list[str]:
        loop = get_loop()
        if loop is None:
            return get_available_voices()

        async def _get_v() -> list[str]:
            if get_voices is not None:
                return await get_voices()
            return await handler.get_available_voices()

        try:
            fut = asyncio.run_coroutine_threadsafe(_get_v(), loop)
            return fut.result(timeout=10)
        except Exception as exc:
            logger.warning("Failed to read available voices: %s", exc)
            return get_available_voices()

    @app.get(f"{api_prefix}/voices/current")
    def _current_voice() -> dict[str, str]:
        try:
            if get_current_voice is not None:
                return {"voice": get_current_voice()}
            return {"voice": handler.get_current_voice()}
        except Exception as exc:
            logger.warning("Failed to read current voice: %s", exc)
            return {"voice": get_default_voice()}

    @app.post(f"{api_prefix}/voices/apply")
    def _apply_voice(payload: VoicePayload) -> JSONResponse:
        selected_voice = payload.voice.strip()
        if not selected_voice:
            return JSONResponse({"ok": False, "error": "missing_voice"}, status_code=400)
        loop = get_loop()
        if loop is None:
            return JSONResponse({"ok": False, "error": "loop_unavailable"}, status_code=503)

        async def _do() -> str:
            if change_voice is not None:
                return await change_voice(selected_voice)
            return await handler.change_voice(selected_voice)

        try:
            fut = asyncio.run_coroutine_threadsafe(_do(), loop)
            status = fut.result(timeout=10)
            return JSONResponse({"ok": True, "status": status})
        except Exception as exc:
            logger.exception("Failed to apply voice %r", selected_voice)
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
