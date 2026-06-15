"""RFID tag data persistence.

Maps RFID codes to personality names (profile paths such as
``user_personalities/my_bot`` or ``(built-in default)``).
Stored as a JSON dict: ``{code_id: personality_name}``.
The file lives in ``external_content/rfid_data/data.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


# Default: external_content/rfid_data/ (sibling of this package's parent dir)
_DEFAULT_DATA_DIR = Path(__file__).parent.parent / "rfid_data"


class RFIDStore:
    """JSON-backed store mapping RFID tag codes to personality names."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = data_dir if data_dir is not None else _DEFAULT_DATA_DIR
        self._data_file = self._data_dir / "data.json"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, str] = {}
        self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def all(self) -> dict[str, str]:
        """Return a copy of all mappings ``{code: personality_name}``."""
        return dict(self._data)

    def get(self, code: str) -> str | None:
        """Return the personality name for *code*, or None if unknown."""
        return self._data.get(code)

    def save(self, code: str, personality: str) -> None:
        """Create or update the code→personality mapping and persist."""
        self._data[code] = personality
        self._persist()

    def delete(self, code: str) -> None:
        """Remove *code* from the store (no-op if absent)."""
        self._data.pop(code, None)
        self._persist()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._data_file.exists():
            try:
                with open(self._data_file, encoding="utf-8") as fh:
                    loaded = json.load(fh)
                    if isinstance(loaded, dict):
                        # Accept only str→str mappings (new schema)
                        self._data = {k: v for k, v in loaded.items() if isinstance(v, str)}
            except Exception:
                self._data = {}

    def _persist(self) -> None:
        with open(self._data_file, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)
