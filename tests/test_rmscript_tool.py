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
    deps.camera_worker = None
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


def test_preview_clears_queue_and_brackets_head_tracking() -> None:
    """Preview clears the queue, pauses tracking, runs the script, then restores tracking."""
    queued: List[Any] = []
    deps = _make_deps(queued)
    deps.camera_worker = MagicMock()
    deps.camera_worker.is_head_tracking_enabled = True
    tracking_calls: List[bool] = []
    deps.camera_worker.set_head_tracking_enabled.side_effect = tracking_calls.append

    result = asyncio.run(rmscript_tool.run_rmscript_preview('"t"\nlook left', deps))

    assert result["ok"] is True
    deps.movement_manager.clear_move_queue.assert_called()
    assert tracking_calls[0] is False  # paused before playing
    assert tracking_calls[-1] is True  # restored to its prior state afterwards
    assert len(queued) == 1  # the look move was queued


def test_preview_compile_failure_does_not_touch_robot() -> None:
    """An invalid script returns compile_failed without clearing the queue or moving."""
    queued: List[Any] = []
    deps = _make_deps(queued)

    result = asyncio.run(rmscript_tool.run_rmscript_preview("floop the gleeb", deps))

    assert result == {"ok": False, "error": "compile_failed"}
    deps.movement_manager.clear_move_queue.assert_not_called()
    assert queued == []


def test_picture_returns_b64(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `picture` action returns the latest camera frame as base64 JPEG."""
    queued: List[Any] = []
    deps = _make_deps(queued)
    deps.camera_worker = MagicMock()
    deps.camera_worker.get_latest_frame.return_value = np.zeros((4, 4, 3), dtype=np.uint8)
    monkeypatch.setattr(rmscript_tool, "encode_bgr_frame_as_jpeg", lambda _frame: b"jpegbytes")

    cls = make_rmscript_tool_class('"t"\npicture', "t")
    assert cls is not None
    result = _run(cls(), deps)
    assert result["b64_im"] == base64.b64encode(b"jpegbytes").decode("utf-8")
