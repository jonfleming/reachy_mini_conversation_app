"""Blocking dream phase executed at app boot.

Ties the dreamer to the robot's affordances: it queues the ``dizzy_spin``
dance on a background ticker while ``Dreamer.run()`` grinds through
``logs/pending/``. Conversation app startup waits on this function before
accepting connections.

See §8 of ``docs/memory-rework-dreaming-spec.md``.
"""

from __future__ import annotations
import time
import logging
import threading
from typing import Any

from reachy_mini_conversation_app.memory.dreamer import Dreamer, DreamLogStats
from reachy_mini_conversation_app.memory.memory_manager import MemoryManager


logger = logging.getLogger(__name__)


class _DizzySpinLoop:
    """Background ticker that keeps ``dizzy_spin`` queued while dreaming."""

    def __init__(self, movement_manager: Any) -> None:
        self._movement_manager = movement_manager
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Queue the first dizzy_spin and keep the ticker running."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="dream-dizzy-spin", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop queueing new spins and clear any outstanding ones."""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        try:
            self._movement_manager.clear_move_queue()
        except Exception as e:
            logger.warning("Failed to clear move queue after dream phase: %s", e)
        self._thread = None

    def _loop(self) -> None:
        # Imported lazily so unit tests can skip the whole dance stack.
        try:
            from reachy_mini_conversation_app.dance_emotion_moves import DanceQueueMove
        except Exception as e:  # pragma: no cover - optional dep
            logger.warning("Dance library unavailable; skipping dizzy-spin animation: %s", e)
            return

        while not self._stop_event.is_set():
            try:
                move = DanceQueueMove("dizzy_spin")
                self._movement_manager.queue_move(move)
                duration = max(float(move.duration) - 0.1, 0.5)
            except Exception as e:
                logger.warning("dizzy_spin queueing failed: %s", e)
                duration = 1.0
            # Sleep in small increments so stop() is responsive.
            end_at = time.monotonic() + duration
            while not self._stop_event.is_set() and time.monotonic() < end_at:
                time.sleep(0.1)


def run_dream_phase(
    memory_manager: MemoryManager,
    *,
    model: str,
    api_key: str | None,
    movement_manager: Any | None = None,
    base_url: str | None = None,
) -> list[DreamLogStats]:
    """Run the blocking dream phase and return the per-log stats list.

    If ``movement_manager`` is provided, ``dizzy_spin`` is queued on a
    ticker thread for the duration of the dream pass. If there are no
    pending logs, returns immediately with no animation.
    """
    pending = memory_manager.list_pending_logs(exclude_session=True)
    if not pending:
        logger.info("[DREAM] Skipping dream phase: no pending logs.")
        return []

    spinner: _DizzySpinLoop | None = None
    if movement_manager is not None:
        spinner = _DizzySpinLoop(movement_manager)
        spinner.start()

    try:
        dreamer = Dreamer(memory_manager, model=model, api_key=api_key, base_url=base_url)
        return dreamer.run()
    finally:
        if spinner is not None:
            spinner.stop()
