"""FastAPI routes for the shared rmscript tool library.

Exposes compile-checking and CRUD endpoints for .rmscript-defined tools.
Save rejects sources that fail to compile, so the library never holds a tool
that would hard-fail the registry. No robot motion here (see preview routes).
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


logger = logging.getLogger(__name__)


def _dump(items: Any) -> List[Dict[str, Any]]:
    """Serialize rmscript diagnostics (errors/warnings) to plain dicts."""
    return [
        {
            "line": getattr(i, "line", None),
            "column": getattr(i, "column", None),
            "message": getattr(i, "message", str(i)),
        }
        for i in items
    ]


def mount_rmscript_routes(app: FastAPI) -> None:
    """Register shared rmscript tool library endpoints on a FastAPI app."""

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
