"""Tests for screen fingerprints and the stuck-on-screen FSM (no real desktop)."""

from pathlib import Path
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from reachy_buddy.vision.presence import present_for_desktop
from reachy_buddy.vision.window_meta import WindowMeta, window_meta_from_parts
from reachy_buddy.vision.screen_presence import (
    ScreenFingerprint,
    ScreenPresenceConfig,
    ScreenPresenceTracker,
)


class _Clock:
    """Monotonic clock the tests can step."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _frame(value: int) -> NDArray[np.uint8]:
    return np.full((90, 160, 3), value, dtype=np.uint8)


def _code_window() -> WindowMeta:
    return window_meta_from_parts("Code.exe", "app.py — workspace")


def _tracker(
    grabber: Callable[[], NDArray[np.uint8] | None],
    *,
    enabled: bool = True,
    stuck_min: float = 1.0 / 60.0,
    interval_sec: float = 0.0,
    debug_save: bool = False,
    debug_dir: Path | None = None,
    window_meta_fn: Callable[[], WindowMeta] | None = None,
    secure: bool = False,
    input_age: float | None = None,
) -> tuple[ScreenPresenceTracker, _Clock]:
    clock = _Clock()
    tracker = ScreenPresenceTracker(
        ScreenPresenceConfig(
            enabled=enabled,
            interval_sec=interval_sec,
            stuck_min=stuck_min,
            similarity=0.92,
            indicator=False,
            debug_save=debug_save,
            debug_dir=debug_dir,
        ),
        grabber=grabber,
        window_meta_fn=window_meta_fn or _code_window,
        input_age_fn=lambda: input_age,
        secure_fn=lambda: secure,
        clock=clock,
    )
    return tracker, clock


def test_identical_frames_hash_as_similar() -> None:
    """A static frame matches itself; a different gray level does not."""
    left = ScreenFingerprint.from_frame(_frame(40))
    right = ScreenFingerprint.from_frame(_frame(40))
    other = ScreenFingerprint.from_frame(_frame(200))

    assert left.similarity(right) >= 0.99
    assert other.similarity(left) < 0.5


def test_changing_frames_are_not_stuck() -> None:
    """A screen that keeps changing never crosses the stuck threshold."""
    values = [20, 80, 140, 200, 40]
    index = {"i": 0}

    def grabber() -> NDArray[np.uint8]:
        frame = _frame(values[index["i"] % len(values)])
        index["i"] += 1
        return frame

    tracker, clock = _tracker(grabber)
    for _ in range(8):
        snapshot = tracker.tick(user_present=True)
        clock.advance(1.0)

    assert not snapshot.stuck
    assert snapshot.observation_label is None


def test_static_screen_with_presence_becomes_stuck_after_t() -> None:
    """Enabled + static fingerprints + presence for T emits desktop:stuck:Code."""
    tracker, clock = _tracker(lambda: _frame(48))

    first = tracker.tick(user_present=True)
    assert not first.stuck
    clock.advance(1.0)
    stuck = tracker.tick(user_present=True)

    assert stuck.stuck
    assert stuck.became_stuck
    assert stuck.observation_label == "desktop:stuck:Code"
    assert stuck.salience > 0.0
    assert tracker.capture_count == 2


def test_absent_user_does_not_count_as_stuck() -> None:
    """A static screen with nobody present does not emit an observation."""
    tracker, clock = _tracker(lambda: _frame(48), input_age=None)
    tracker.tick(user_present=False)
    clock.advance(1.0)
    snapshot = tracker.tick(user_present=False)

    assert not snapshot.stuck
    assert snapshot.observation_label is None


def test_disabled_tracker_never_captures() -> None:
    """BUDDY_SCREEN_PRESENCE off means the grabber is never called."""
    calls = {"n": 0}

    def grabber() -> NDArray[np.uint8]:
        calls["n"] += 1
        return _frame(10)

    tracker, _clock = _tracker(grabber, enabled=False)
    snapshot = tracker.tick(user_present=True)

    assert calls["n"] == 0
    assert tracker.capture_count == 0
    assert snapshot.observation_label is None


def test_locked_desktop_emits_no_observation() -> None:
    """Locked or secure desktops are skipped and never counted as stuck."""
    tracker, clock = _tracker(lambda: _frame(48), secure=True)
    tracker.tick(user_present=True)
    clock.advance(1.0)
    snapshot = tracker.tick(user_present=True)

    assert tracker.capture_count == 0
    assert snapshot.observation_label is None


def test_denied_title_is_not_stuck() -> None:
    """Password / 2FA titles do not produce a desktop:stuck observation."""
    tracker, clock = _tracker(
        lambda: _frame(48),
        window_meta_fn=lambda: window_meta_from_parts("chrome.exe", "Enter your password"),
    )
    tracker.tick(user_present=True)
    clock.advance(1.0)
    snapshot = tracker.tick(user_present=True)

    assert snapshot.observation_label is None
    assert tracker.capture_count == 0


def test_debug_save_off_writes_no_files(tmp_path: Path) -> None:
    """Default debug save is off, so no screenshot files are created."""
    tracker, _clock = _tracker(lambda: _frame(48), debug_save=False, debug_dir=tmp_path)
    tracker.tick(user_present=True)

    assert list(tmp_path.iterdir()) == []
    assert tracker.debug_saves == 0


def test_present_for_desktop_uses_face_or_recent_signal() -> None:
    """Desk occupancy is a face or a still-warm speech/input signal."""
    assert present_for_desktop(face_present=True, seconds_since_user_signal=None)
    assert present_for_desktop(face_present=False, seconds_since_user_signal=10.0, hold_s=180.0)
    assert not present_for_desktop(face_present=False, seconds_since_user_signal=400.0, hold_s=180.0)
    assert not present_for_desktop(face_present=False, seconds_since_user_signal=None)
