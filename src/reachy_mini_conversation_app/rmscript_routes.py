"""FastAPI routes for the shared rmscript tool library.

Exposes compile-checking and CRUD endpoints for .rmscript-defined tools, plus
preview/abort endpoints that play a script on the robot. Save rejects sources
that fail to compile, so the library never holds a tool that would hard-fail
the registry. Preview queues the script's moves on the (thread-safe) movement
manager and returns immediately; abort clears the queue and restores tracking.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from rmscript import compile_script
from fastapi.responses import JSONResponse

from .rmscript_library import (
    read_rmscript_tool,
    list_rmscript_tools,
    write_rmscript_tool,
    delete_rmscript_tool,
)
from .tools.rmscript_tool import queue_rmscript
from .conversation_handler import ConversationHandler


logger = logging.getLogger(__name__)


def _dump(items: Any) -> List[Dict[str, Any]]:
    """Serialize rmscript diagnostics (errors/warnings) to plain dicts."""
    return [{"line": i.line, "column": i.column, "message": i.message} for i in items]


def mount_rmscript_routes(app: FastAPI, handler: ConversationHandler) -> None:
    """Register shared rmscript tool library endpoints on a FastAPI app.

    Preview/abort use the handler's robot dependencies directly; the movement
    queue and head-tracking toggle are thread-safe, so no event loop is needed.
    """
    # Head-tracking state saved when a preview starts, restored on abort.
    saved_tracking: Dict[str, bool | None] = {"value": None}

    @app.post("/rmscript/preview")
    async def _preview(request: Request) -> Any:
        deps = handler.deps
        source = str((await request.json()).get("source", ""))
        result = queue_rmscript(source, deps)
        if not result["ok"]:
            return JSONResponse(result, status_code=400)
        cam = deps.camera_worker
        if cam is not None and saved_tracking["value"] is None:
            saved_tracking["value"] = cam.is_head_tracking_enabled
            cam.set_head_tracking_enabled(False)
        return result

    @app.post("/rmscript/abort")
    async def _abort() -> dict:  # type: ignore
        deps = handler.deps
        deps.movement_manager.clear_move_queue()
        cam = deps.camera_worker
        if cam is not None and saved_tracking["value"] is not None:
            cam.set_head_tracking_enabled(saved_tracking["value"])
            saved_tracking["value"] = None
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
