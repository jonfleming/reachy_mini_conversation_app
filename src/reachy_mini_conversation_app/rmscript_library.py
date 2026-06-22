"""Data layer for the shared rmscript tool library (profiles/rmscript_tools/).

Thin CRUD over the .rmscript files that back rmscript-defined tools. No HTTP or
framework dependencies — importable anywhere.
"""

from __future__ import annotations
from typing import Dict, List
from pathlib import Path

from rmscript import compile_script

from .config import config
from .personality import _sanitize_name


def _root() -> Path:
    return config.rmscript_tools_root()


def list_rmscript_tools() -> List[Dict[str, str]]:
    """Return [{name, description}] for each .rmscript in the library, sorted by name."""
    root = _root()
    tools: List[Dict[str, str]] = []
    if root.exists():
        for rs in sorted(root.glob("*.rmscript")):
            result = compile_script(rs.read_text(encoding="utf-8"))
            tools.append({"name": rs.stem, "description": result.description or ""})
    return tools


def read_rmscript_tool(name: str) -> str:
    """Return the source of a library tool, or empty string if absent."""
    path = _root() / f"{_sanitize_name(name)}.rmscript"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def write_rmscript_tool(name: str, source: str) -> str:
    """Write source to <name>.rmscript and return the sanitized name."""
    safe = _sanitize_name(name)
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{safe}.rmscript").write_text(source.rstrip("\n") + "\n", encoding="utf-8")
    return safe


def delete_rmscript_tool(name: str) -> bool:
    """Delete <name>.rmscript; return whether a file was removed."""
    path = _root() / f"{_sanitize_name(name)}.rmscript"
    if path.is_file():
        path.unlink()
        return True
    return False
