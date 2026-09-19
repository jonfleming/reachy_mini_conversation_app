"""Tests for env-driven buddy sidecar flags."""

from pathlib import Path

from reachy_buddy.runtime_config import BuddyRuntimeConfig


def test_from_env_defaults_disabled() -> None:
    """Buddy is off until BUDDY_ENABLED is set."""
    config = BuddyRuntimeConfig.from_env(env={})

    assert config.enabled is False
    assert config.llama_url is None
    assert config.llama_model == "local"
    assert config.screen.enabled is False
    assert config.screen.debug_save is False


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
    assert config.screen.enabled is False
    assert config.screen.interval_sec == 20.0
    assert config.screen.stuck_min == 12.0
    assert config.screen.cooldown_min == 30.0
    assert config.screen.similarity == 0.92
    assert config.screen.indicator is True
    assert config.screen.debug_save is False


def test_from_env_reads_screen_presence_flags() -> None:
    """BUDDY_SCREEN_* wires the stuck-on-screen fingerprint loop."""
    config = BuddyRuntimeConfig.from_env(
        env={
            "BUDDY_SCREEN_PRESENCE": "1",
            "BUDDY_SCREEN_INTERVAL_SEC": "15",
            "BUDDY_SCREEN_STUCK_MIN": "8",
            "BUDDY_SCREEN_COOLDOWN_MIN": "45",
            "BUDDY_SCREEN_SIMILARITY": "0.88",
            "BUDDY_SCREEN_INDICATOR": "0",
            "BUDDY_SCREEN_DEBUG_SAVE": "1",
        }
    )

    assert config.screen.enabled is True
    assert config.screen.interval_sec == 15.0
    assert config.screen.stuck_min == 8.0
    assert config.screen.cooldown_min == 45.0
    assert config.screen.similarity == 0.88
    assert config.screen.indicator is False
    assert config.screen.debug_save is True


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
