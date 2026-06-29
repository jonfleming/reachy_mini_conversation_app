"""Tests for loading .rmscript files as conversation tools."""

import base64
import asyncio
from typing import Any, List
from unittest.mock import MagicMock

import numpy as np
import pytest


# Requires the standalone rmscript DSL compiler package.
pytest.importorskip("rmscript")

from reachy_mini_conversation_app.tools import rmscript_tool  # noqa: E402
from reachy_mini_conversation_app.dance_emotion_moves import GotoQueueMove  # noqa: E402
from reachy_mini_conversation_app.tools.rmscript_tool import make_rmscript_tool_class  # noqa: E402


def _make_deps(queued: List[Any]) -> MagicMock:
    """Mock ToolDependencies: identity head pose, antennas [right=0.1, left=0.2]."""
    deps = MagicMock()
    deps.reachy_mini.get_current_head_pose.return_value = np.eye(4)
    deps.reachy_mini.get_current_joint_positions.return_value = ([0.0] * 7, [0.1, 0.2])
    deps.movement_manager.queue_move.side_effect = queued.append
    deps.camera_enabled = False
    return deps


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the timeline sleeps so tests run instantly."""

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(rmscript_tool.asyncio, "sleep", _instant)


def _run(tool: Any, deps: Any) -> dict:
    """Run an async tool to completion."""
    return asyncio.run(tool(deps))


def test_make_tool_class_metadata() -> None:
    """A valid script compiles to a zero-argument tool with the first line as description."""
    cls = make_rmscript_tool_class('"Wave hello"\nlook left', "wave")
    assert cls is not None
    assert cls.name == "wave"
    assert cls.description == "Wave hello"
    assert cls().parameters_schema == {"type": "object", "properties": {}, "required": []}


def test_make_tool_class_compile_error_returns_none() -> None:
    """An invalid script logs the error and yields no tool class."""
    assert make_rmscript_tool_class('"bad"\nfloop the gleeb', "broken") is None


def test_execution_queues_moves_and_threads_start_state() -> None:
    """Each move (and the wait hold) starts from the previous move's target."""
    queued: List[Any] = []
    deps = _make_deps(queued)
    cls = make_rmscript_tool_class('"t"\nlook left\nwait 0.5s\nlook right', "t")
    assert cls is not None
    result = _run(cls(), deps)

    assert result["status"] == "ran t"
    # 2 look actions + 1 wait (hold) = 3 queued moves
    assert len(queued) == 3
    assert all(isinstance(m, GotoQueueMove) for m in queued)
    # The wait holds the previous target (start == target == look-left target).
    assert np.allclose(queued[1].start_head_pose, queued[0].target_head_pose)
    assert np.allclose(queued[1].target_head_pose, queued[1].start_head_pose)
    # The second look starts where the hold ended (threaded start state).
    assert np.allclose(queued[2].start_head_pose, queued[1].target_head_pose)


def test_single_antenna_keeps_other_in_place() -> None:
    """A single-antenna command holds the other antenna at its current position."""
    queued: List[Any] = []
    deps = _make_deps(queued)  # current antennas [right=0.1, left=0.2]
    cls = make_rmscript_tool_class('"t"\nantenna left down', "t")
    assert cls is not None
    _run(cls(), deps)

    move = queued[0]
    # left (index 1) -> 180deg; right (index 0) held at its current 0.1
    assert move.target_antennas[0] == pytest.approx(0.1)
    assert move.target_antennas[1] == pytest.approx(np.pi)


def test_prepare_preview_returns_tool_and_duration() -> None:
    """A valid script yields a runnable tool and the time its run will block."""
    tool, duration = rmscript_tool.prepare_preview('"t"\nlook left\nwait 0.5s')

    assert tool is not None
    assert duration == pytest.approx(1.5)  # look (default 1s) + wait 0.5s


def test_prepare_preview_compile_failure_returns_none() -> None:
    """An invalid script yields no tool and zero duration."""
    tool, duration = rmscript_tool.prepare_preview("floop the gleeb")

    assert tool is None
    assert duration == 0.0


def test_resolve_sound_prefers_library_sounds_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file in the library sounds/ dir resolves to its absolute path."""
    sounds = tmp_path / "sounds"
    sounds.mkdir()
    (sounds / "cheer.wav").write_bytes(b"")
    monkeypatch.setattr(rmscript_tool.config, "rmscript_tools_root", lambda: tmp_path)
    assert rmscript_tool._resolve_sound("cheer") == str(sounds / "cheer.wav")


def test_resolve_sound_falls_back_to_builtin_assets(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A built-in asset resolves to a bare `<name>.<ext>` for daemon-side lookup."""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "wake_up.wav").write_bytes(b"")
    monkeypatch.setattr(rmscript_tool.config, "rmscript_tools_root", lambda: tmp_path / "lib")
    monkeypatch.setattr(rmscript_tool, "ASSETS_ROOT_PATH", str(assets))
    assert rmscript_tool._resolve_sound("wake_up") == "wake_up.wav"


def test_resolve_sound_missing_returns_none(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown sound name resolves to None."""
    monkeypatch.setattr(rmscript_tool.config, "rmscript_tools_root", lambda: tmp_path / "lib")
    monkeypatch.setattr(rmscript_tool, "ASSETS_ROOT_PATH", str(tmp_path / "assets"))
    assert rmscript_tool._resolve_sound("nope") is None


def test_play_sound_resolves_and_plays(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `play` action resolves the name and calls media.play_sound with it."""
    queued: List[Any] = []
    deps = _make_deps(queued)
    monkeypatch.setattr(rmscript_tool, "_resolve_sound", lambda name: f"/abs/{name}.wav")
    cls = make_rmscript_tool_class('"t"\nplay cheer', "t")
    assert cls is not None
    _run(cls(), deps)
    deps.reachy_mini.media.play_sound.assert_called_once_with("/abs/cheer.wav")


def test_play_sound_missing_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unresolved sound is skipped without calling media.play_sound."""
    queued: List[Any] = []
    deps = _make_deps(queued)
    monkeypatch.setattr(rmscript_tool, "_resolve_sound", lambda name: None)
    cls = make_rmscript_tool_class('"t"\nplay cheer', "t")
    assert cls is not None
    _run(cls(), deps)
    deps.reachy_mini.media.play_sound.assert_not_called()


def test_picture_returns_b64(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `picture` action returns the latest camera frame as base64 JPEG."""
    queued: List[Any] = []
    deps = _make_deps(queued)
    deps.camera_enabled = True
    deps.reachy_mini.media.get_frame.return_value = np.zeros((4, 4, 3), dtype=np.uint8)
    monkeypatch.setattr(rmscript_tool, "save_debug_snapshot", lambda _frame, _label: b"jpegbytes")

    cls = make_rmscript_tool_class('"t"\npicture', "t")
    assert cls is not None
    result = _run(cls(), deps)
    assert result["b64_im"] == base64.b64encode(b"jpegbytes").decode("utf-8")
