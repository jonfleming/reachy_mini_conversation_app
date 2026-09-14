"""Tests for env-driven buddy sidecar flags."""

from pathlib import Path

from reachy_buddy.runtime_config import BuddyRuntimeConfig


def test_from_env_defaults_disabled() -> None:
    """Buddy is off until BUDDY_ENABLED is set."""
    config = BuddyRuntimeConfig.from_env(env={})

    assert config.enabled is False
    assert config.llama_url is None
    assert config.llama_model == "local"


def test_from_env_reads_enable_and_llama() -> None:
    """BUDDY_ENABLED and BUDDY_LLAMA_* wire the inner thought backend."""
    config = BuddyRuntimeConfig.from_env(
        env={
            "BUDDY_ENABLED": "1",
            "BUDDY_LLAMA_URL": "http://localhost:8080/v1/",
            "BUDDY_LLAMA_MODEL": "gemma",
        }
    )

    assert config.enabled is True
    assert config.llama_url == "http://localhost:8080/v1"
    assert config.llama_model == "gemma"
    assert config.object_onnx is None


def test_from_env_reads_vision_paths(tmp_path: Path) -> None:
    """Face and object-model paths come from BUDDY_* files."""
    config = BuddyRuntimeConfig.from_env(
        env={
            "BUDDY_FACES_PATH": str(tmp_path / "faces.npz"),
            "BUDDY_OBJECT_ONNX": str(tmp_path / "yolo.onnx"),
            "BUDDY_OBJECT_LABELS": str(tmp_path / "labels.txt"),
        }
    )

    assert config.faces_path == tmp_path / "faces.npz"
    assert config.object_onnx == tmp_path / "yolo.onnx"
    assert config.object_labels == tmp_path / "labels.txt"
