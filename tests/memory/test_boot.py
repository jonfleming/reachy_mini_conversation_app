"""Tests for the blocking dream-phase wrapper."""

from __future__ import annotations
import time
import threading
from typing import Any
from pathlib import Path
from unittest.mock import patch

import pytest

from reachy_mini_conversation_app.memory.boot import run_dream_phase
from reachy_mini_conversation_app.memory.memory_manager import MemoryManager


class _FakeMovementManager:
    """Records every queued move + clear_move_queue for assertions."""

    def __init__(self) -> None:
        self.queued: list[Any] = []
        self.cleared: int = 0
        self._lock = threading.Lock()

    def queue_move(self, move: Any) -> None:
        with self._lock:
            self.queued.append(move)

    def clear_move_queue(self) -> None:
        with self._lock:
            self.cleared += 1


@pytest.fixture
def manager(tmp_path: Path) -> MemoryManager:
    """Manager with one queued pending log (aside from the live one)."""
    mgr = MemoryManager(tmp_path / "data")
    (mgr.pending_logs_dir / "2026-04-14_09-15.log").write_text("log body", encoding="utf-8")
    return mgr


def test_skipped_when_no_pending_logs(tmp_path: Path) -> None:
    """No pending logs → no animation, no LLM attempt."""
    mgr = MemoryManager(tmp_path / "data")
    movement = _FakeMovementManager()
    result = run_dream_phase(mgr, model="fake", api_key=None, movement_manager=movement)
    assert result == []
    assert movement.queued == []
    assert movement.cleared == 0


def test_runs_dreamer_and_animates(manager: MemoryManager) -> None:
    """With pending logs and a movement manager, the dizzy spin ticks."""
    movement = _FakeMovementManager()

    call_log: list[float] = []

    def fake_run(self: Any) -> list[Any]:  # noqa: ARG001
        # Simulate enough dream work for the ticker to load the dance
        # library and queue at least one move. DanceMove() first-load is
        # non-trivial, so give it >500ms of breathing room.
        time.sleep(1.0)
        call_log.append(time.monotonic())
        return []

    with patch("reachy_mini_conversation_app.memory.boot.Dreamer") as DreamerCls:
        DreamerCls.return_value.run = lambda: fake_run(None)
        result = run_dream_phase(
            manager,
            model="fake",
            api_key=None,
            movement_manager=movement,
        )

    assert result == []
    assert len(call_log) == 1
    # At least one move was queued and the queue was cleared on exit.
    assert movement.queued, "Expected at least one dizzy_spin queued"
    assert movement.cleared >= 1


def test_works_without_movement_manager(manager: MemoryManager) -> None:
    """Pass no movement manager — the dreamer still runs."""
    with patch("reachy_mini_conversation_app.memory.boot.Dreamer") as DreamerCls:
        DreamerCls.return_value.run = lambda: []
        run_dream_phase(manager, model="fake", api_key=None, movement_manager=None)
