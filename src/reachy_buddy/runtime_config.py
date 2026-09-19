"""Env-driven flags for the desktop-buddy sidecar."""

import os
import logging
from pathlib import Path
from dataclasses import field, dataclass
from collections.abc import Mapping

from reachy_buddy.vision.screen_presence import ScreenPresenceConfig


logger = logging.getLogger(__name__)


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(source: Mapping[str, str], key: str, default: float) -> float:
    raw = source.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using %s", key, raw, default)
        return default


@dataclass(frozen=True)
class BuddyRuntimeConfig:
    """Whether the sidecar runs, and optional llama.cpp thought generation."""

    enabled: bool = False
    llama_url: str | None = None
    llama_model: str = "local"
    faces_path: Path = Path.home() / ".reachy_buddy" / "faces.npz"
    object_onnx: Path | None = None
    object_labels: Path | None = None
    screen: ScreenPresenceConfig = field(default_factory=ScreenPresenceConfig)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BuddyRuntimeConfig":
        """Build from BUDDY_ENABLED / BUDDY_LLAMA_* / vision path variables."""
        source = os.environ if env is None else env
        llama_url = source.get("BUDDY_LLAMA_URL", "").strip() or None
        faces = source.get("BUDDY_FACES_PATH", "").strip()
        onnx = source.get("BUDDY_OBJECT_ONNX", "").strip()
        labels = source.get("BUDDY_OBJECT_LABELS", "").strip()
        debug_dir = source.get("BUDDY_SCREEN_DEBUG_DIR", "").strip()
        similarity = min(1.0, max(0.0, _env_float(source, "BUDDY_SCREEN_SIMILARITY", 0.92)))
        return cls(
            enabled=_truthy(source.get("BUDDY_ENABLED")),
            llama_url=llama_url.rstrip("/") if llama_url else None,
            llama_model=source.get("BUDDY_LLAMA_MODEL", "local").strip() or "local",
            faces_path=Path(faces) if faces else Path.home() / ".reachy_buddy" / "faces.npz",
            object_onnx=Path(onnx) if onnx else None,
            object_labels=Path(labels) if labels else None,
            screen=ScreenPresenceConfig(
                enabled=_truthy(source.get("BUDDY_SCREEN_PRESENCE")),
                interval_sec=max(0.0, _env_float(source, "BUDDY_SCREEN_INTERVAL_SEC", 20.0)),
                stuck_min=max(0.0, _env_float(source, "BUDDY_SCREEN_STUCK_MIN", 12.0)),
                cooldown_min=max(0.0, _env_float(source, "BUDDY_SCREEN_COOLDOWN_MIN", 30.0)),
                similarity=similarity,
                indicator=_truthy(source.get("BUDDY_SCREEN_INDICATOR", "1")),
                debug_save=_truthy(source.get("BUDDY_SCREEN_DEBUG_SAVE")),
                debug_dir=Path(debug_dir) if debug_dir else None,
            ),
        )
