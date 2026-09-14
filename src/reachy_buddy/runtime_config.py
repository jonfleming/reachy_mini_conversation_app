"""Env-driven flags for the desktop-buddy sidecar."""

import os
from pathlib import Path
from dataclasses import dataclass
from collections.abc import Mapping


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BuddyRuntimeConfig:
    """Whether the sidecar runs, and optional llama.cpp thought generation."""

    enabled: bool = False
    llama_url: str | None = None
    llama_model: str = "local"
    faces_path: Path = Path.home() / ".reachy_buddy" / "faces.npz"
    object_onnx: Path | None = None
    object_labels: Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BuddyRuntimeConfig":
        """Build from BUDDY_ENABLED / BUDDY_LLAMA_* / vision path variables."""
        source = os.environ if env is None else env
        llama_url = source.get("BUDDY_LLAMA_URL", "").strip() or None
        faces = source.get("BUDDY_FACES_PATH", "").strip()
        onnx = source.get("BUDDY_OBJECT_ONNX", "").strip()
        labels = source.get("BUDDY_OBJECT_LABELS", "").strip()
        return cls(
            enabled=_truthy(source.get("BUDDY_ENABLED")),
            llama_url=llama_url.rstrip("/") if llama_url else None,
            llama_model=source.get("BUDDY_LLAMA_MODEL", "local").strip() or "local",
            faces_path=Path(faces) if faces else Path.home() / ".reachy_buddy" / "faces.npz",
            object_onnx=Path(onnx) if onnx else None,
            object_labels=Path(labels) if labels else None,
        )
