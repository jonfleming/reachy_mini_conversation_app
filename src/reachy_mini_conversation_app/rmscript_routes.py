"""FastAPI routes for the shared rmscript tool library.

Exposes compile-checking and CRUD endpoints for .rmscript-defined tools, plus
preview/abort endpoints that play a script on the robot. Save rejects sources
that fail to compile, so the library never holds a tool that would hard-fail
the registry. Preview runs the script through the same paced path as the real
tool (a background task, so waits/sounds/pictures are honored) with head
tracking off; abort cancels that task, clears the queue, and restores tracking.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List

from fastapi import File, FastAPI, Request, UploadFile
from rmscript import compile_script
from fastapi.responses import JSONResponse

from .sound_library import (
    save_sound,
    delete_sound,
    list_user_sounds,
    list_builtin_sounds,
)
from .rmscript_library import (
    read_rmscript_tool,
    list_rmscript_tools,
    write_rmscript_tool,
    delete_rmscript_tool,
)
from .tools.rmscript_tool import RmscriptTool, prepare_preview
from .conversation_handler import ConversationHandler


logger = logging.getLogger(__name__)


def _dump(items: Any) -> List[Dict[str, Any]]:
    """Serialize rmscript diagnostics (errors/warnings) to plain dicts."""
    return [{"line": i.line, "column": i.column, "message": i.message} for i in items]


def mount_rmscript_routes(app: FastAPI, handler: ConversationHandler) -> None:
    """Register shared rmscript tool library endpoints on a FastAPI app.

    Preview runs the tool in a background task; ``preview`` tracks that task and
    the head-tracking state to restore. The movement queue and head-tracking
    toggle are thread-safe, so the task drives the robot directly.
    """
    # In-flight preview task and the head-tracking value to restore afterwards.
    preview: Dict[str, Any] = {"task": None, "tracking": None}

    def _disable_tracking() -> None:
        """Turn head tracking off, remembering its prior value (once per preview)."""
        cam = handler.deps.camera_worker
        if cam is not None and preview["tracking"] is None:
            preview["tracking"] = cam.is_head_tracking_enabled
            cam.set_head_tracking_enabled(False)

    def _restore_tracking() -> None:
        """Restore head tracking to its pre-preview value, if we changed it."""
        cam = handler.deps.camera_worker
        if cam is not None and preview["tracking"] is not None:
            cam.set_head_tracking_enabled(preview["tracking"])
        preview["tracking"] = None

    def _cancel_task() -> None:
        """Cancel the running preview task, if any, and forget it."""
        task = preview["task"]
        if task is not None and not task.done():
            task.cancel()
        preview["task"] = None

    async def _run_preview(tool: RmscriptTool) -> None:
        """Play the behavior, restoring tracking only if not superseded/aborted."""
        try:
            await tool(handler.deps)
        finally:
            # A superseding preview or an explicit abort manages state instead.
            if preview["task"] is asyncio.current_task():
                preview["task"] = None
                _restore_tracking()

    @app.post("/rmscript/preview")
    async def _preview(request: Request) -> Any:
        source = str((await request.json()).get("source", ""))
        tool, duration = prepare_preview(source)
        if tool is None:
            return JSONResponse({"ok": False, "error": "compile_failed"}, status_code=400)
        _cancel_task()
        handler.deps.movement_manager.clear_move_queue()
        _disable_tracking()
        preview["task"] = asyncio.create_task(_run_preview(tool))
        return {"ok": True, "duration": duration}

    @app.post("/rmscript/abort")
    async def _abort() -> dict:  # type: ignore
        _cancel_task()
        handler.deps.movement_manager.clear_move_queue()
        _restore_tracking()
        return {"ok": True}

    @app.post("/rmscript/verify")
    async def _verify(request: Request) -> dict:  # type: ignore
        raw = await request.json()
        result = compile_script(str(raw.get("source", "")))
        return {
            "success": result.success,
            "name": getattr(result, "name", None),
            "description": result.description,
            "errors": _dump(result.errors),
            "warnings": _dump(result.warnings),
        }

    @app.get("/rmscript/tools")
    def _list() -> dict:  # type: ignore
        return {"tools": list_rmscript_tools()}

    @app.get("/rmscript/tools/{name}")
    def _get(name: str) -> dict:  # type: ignore
        return {"name": name, "source": read_rmscript_tool(name)}

    @app.post("/rmscript/tools/{name}")
    async def _save(name: str, request: Request) -> Any:
        raw = await request.json()
        source = str(raw.get("source", ""))
        result = compile_script(source)
        if not result.success:
            return JSONResponse({"ok": False, "errors": _dump(result.errors)}, status_code=400)
        saved = write_rmscript_tool(name, source)
        return {"ok": True, "name": saved, "tools": list_rmscript_tools()}

    @app.delete("/rmscript/tools/{name}")
    def _delete(name: str) -> dict:  # type: ignore
        deleted = delete_rmscript_tool(name)
        return {"ok": deleted, "tools": list_rmscript_tools()}

    def _sounds_payload() -> Dict[str, Any]:
        """User and built-in sound names available to `play`."""
        return {"user": list_user_sounds(), "builtin": list_builtin_sounds()}

    @app.get("/rmscript/sounds")
    def _list_sounds() -> dict:  # type: ignore
        return _sounds_payload()

    @app.post("/rmscript/sounds")
    async def _upload_sound(file: UploadFile = File(...)) -> Any:
        data = await file.read()
        try:
            name = save_sound(file.filename or "", data)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        return {"ok": True, "name": name, **_sounds_payload()}

    @app.delete("/rmscript/sounds/{name}")
    def _delete_sound(name: str) -> dict:  # type: ignore
        deleted = delete_sound(name)
        return {"ok": deleted, **_sounds_payload()}
