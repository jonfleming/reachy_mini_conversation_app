"""Data layer for the rmscript sound library (profiles/rmscript_tools/sounds/).

User-uploaded sounds live in the writable ``sounds/`` directory; the robot's
built-in sounds are read-only. Both are playable via ``play <name>`` in
rmscript (see ``tools/rmscript_tool.py::_resolve_sound``). No HTTP or framework
dependencies — importable anywhere.
"""

from __future__ import annotations
from typing import List
from pathlib import Path

from reachy_mini.utils.constants import ASSETS_ROOT_PATH
from .config import config
from .personality import _sanitize_name


# Audio extensions accepted for upload and listing (match _resolve_sound).
SOUND_EXTENSIONS = ("wav", "mp3", "ogg")

# Upper bound for a single uploaded sound (short clips; the bundled ones are <1 MB).
MAX_SOUND_BYTES = 10 * 1024 * 1024


def _sounds_root() -> Path:
    return config.rmscript_tools_root() / "sounds"


def _stems(directory: Path) -> List[str]:
    """Sorted, de-duplicated stems of audio files in a directory."""
    if not directory.exists():
        return []
    names = {p.stem for p in directory.iterdir() if p.is_file() and p.suffix.lstrip(".").lower() in SOUND_EXTENSIONS}
    return sorted(names)


def list_user_sounds() -> List[str]:
    """Names (stems) of user-uploaded sounds."""
    return _stems(_sounds_root())


def list_builtin_sounds() -> List[str]:
    """Names (stems) of the robot's built-in SDK sounds."""
    return _stems(Path(ASSETS_ROOT_PATH))


def save_sound(filename: str, data: bytes) -> str:
    """Write an uploaded sound into the user library; return its sanitized stem.

    The extension comes from the upload and must be a supported audio type.
    """
    suffix = Path(filename).suffix.lstrip(".").lower()
    if suffix not in SOUND_EXTENSIONS:
        raise ValueError(f"unsupported sound format: {suffix!r}")
    if len(data) > MAX_SOUND_BYTES:
        raise ValueError(f"sound exceeds the {MAX_SOUND_BYTES // (1024 * 1024)} MB limit")
    stem = _sanitize_name(Path(filename).stem)
    if not stem:
        raise ValueError("invalid sound name")
    root = _sounds_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{stem}.{suffix}").write_bytes(data)
    return stem


def delete_sound(name: str) -> bool:
    """Delete a user sound by name (any supported extension); return whether removed."""
    root = _sounds_root()
    stem = _sanitize_name(name)
    removed = False
    for ext in SOUND_EXTENSIONS:
        path = root / f"{stem}.{ext}"
        if path.is_file():
            path.unlink()
            removed = True
    return removed
