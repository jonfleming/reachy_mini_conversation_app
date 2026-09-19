"""Periodic local screen fingerprints and a stuck-on-screen state machine."""

import sys
import time
import ctypes
import logging
from ctypes import wintypes
from pathlib import Path
from dataclasses import dataclass
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from reachy_buddy.vision.presence import present_for_desktop
from reachy_buddy.vision.window_meta import (
    WindowMeta,
    _win_dll,
    desktop_is_secure,
    seconds_since_input,
    read_foreground_window,
)


logger = logging.getLogger(__name__)

ScreenGrabber = Callable[[], NDArray[np.uint8] | None]
WindowMetaFn = Callable[[], WindowMeta]
InputAgeFn = Callable[[], float | None]

_MAX_GRAY_WIDTH = 320
_HASH_WIDTH = 32
_HASH_HEIGHT = 18
_INPUT_HOLD_S = 180.0
_STUCK_PREFIX = "desktop:stuck:"


@dataclass(frozen=True)
class ScreenPresenceConfig:
    """Env-facing knobs for screen fingerprinting and the stuck FSM."""

    enabled: bool = False
    interval_sec: float = 20.0
    stuck_min: float = 12.0
    cooldown_min: float = 30.0
    similarity: float = 0.92
    indicator: bool = True
    debug_save: bool = False
    require_same_window: bool = True
    max_gray_width: int = _MAX_GRAY_WIDTH
    input_hold_s: float = _INPUT_HOLD_S
    debug_dir: Path | None = None

    @property
    def stuck_seconds(self) -> float:
        """Stuck duration T in seconds."""
        return max(0.0, self.stuck_min) * 60.0

    @property
    def cooldown_seconds(self) -> float:
        """Proactive cool-down C in seconds."""
        return max(0.0, self.cooldown_min) * 60.0


@dataclass(frozen=True)
class ScreenFingerprint:
    """Compact perceptual fingerprint; never a displayable screenshot."""

    grid: bytes
    ahash: int

    @classmethod
    def from_frame(cls, frame: NDArray[np.uint8], max_gray_width: int = _MAX_GRAY_WIDTH) -> "ScreenFingerprint":
        """Downscale to gray, hash, and drop the source pixels."""
        gray = downscale_gray(frame, max_gray_width)
        grid = _resize_gray(gray, _HASH_WIDTH, _HASH_HEIGHT)
        return cls(grid=grid.tobytes(), ahash=_average_hash(grid))

    def similarity(self, other: "ScreenFingerprint") -> float:
        """Mean-absolute-difference similarity of the two hash grids, in [0, 1]."""
        if len(self.grid) != len(other.grid) or not self.grid:
            return 0.0
        left = np.frombuffer(self.grid, dtype=np.uint8)
        right = np.frombuffer(other.grid, dtype=np.uint8)
        return float(1.0 - np.mean(np.abs(left.astype(np.int16) - right.astype(np.int16))) / 255.0)


@dataclass(frozen=True)
class ScreenPresenceSnapshot:
    """Latest stuck-state view for the session tick; contains no pixels."""

    stuck: bool = False
    became_stuck: bool = False
    observation_label: str | None = None
    salience: float = 0.0
    similarity: float = 0.0
    duration_s: float = 0.0
    window: WindowMeta | None = None
    captured: bool = False


def downscale_gray(frame: NDArray[np.uint8], max_width: int = _MAX_GRAY_WIDTH) -> NDArray[np.uint8]:
    """Convert a BGR or gray frame to grayscale and cap width."""
    if frame.ndim == 3:
        gray = np.ascontiguousarray(
            (0.114 * frame[:, :, 0] + 0.587 * frame[:, :, 1] + 0.299 * frame[:, :, 2]).astype(np.uint8)
        )
    else:
        gray = np.ascontiguousarray(frame)
    height, width = gray.shape[:2]
    if width <= max_width or max_width <= 0:
        return gray
    new_height = max(1, int(round(height * max_width / width)))
    return _resize_gray(gray, max_width, new_height)


def grab_primary_monitor() -> NDArray[np.uint8] | None:
    """Capture the primary monitor; None when the platform cannot (no file write)."""
    if sys.platform != "win32":
        return None
    return _grab_win32_primary()


def observation_label_for(window: WindowMeta | None) -> str:
    """Build a WorldModel label such as desktop:stuck:Code."""
    app = window.app_label if window is not None and window.app_label else "screen"
    return f"{_STUCK_PREFIX}{app}"


def _resize_gray(gray: NDArray[np.uint8], width: int, height: int) -> NDArray[np.uint8]:
    src_h, src_w = gray.shape[:2]
    if src_h == height and src_w == width:
        return np.ascontiguousarray(gray)
    row_idx = np.linspace(0, src_h, height, endpoint=False).astype(np.intp)
    col_idx = np.linspace(0, src_w, width, endpoint=False).astype(np.intp)
    return np.ascontiguousarray(gray[row_idx][:, col_idx])


def _average_hash(grid: NDArray[np.uint8]) -> int:
    small = _resize_gray(grid, 8, 8)
    bits = small >= small.mean()
    value = 0
    for bit in bits.reshape(-1):
        value = (value << 1) | int(bit)
    return value


class _BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _grab_win32_primary() -> NDArray[np.uint8] | None:
    user32 = _win_dll("user32")
    gdi32 = _win_dll("gdi32")
    width = int(user32.GetSystemMetrics(0))
    height = int(user32.GetSystemMetrics(1))
    if width <= 0 or height <= 0:
        return None
    hwnd_desktop = user32.GetDesktopWindow()
    hdc_src = user32.GetWindowDC(hwnd_desktop)
    if not hdc_src:
        return None
    hdc_dst = gdi32.CreateCompatibleDC(hdc_src)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_src, width, height)
    if not hdc_dst or not hbmp:
        if hbmp:
            gdi32.DeleteObject(hbmp)
        if hdc_dst:
            gdi32.DeleteDC(hdc_dst)
        user32.ReleaseDC(hwnd_desktop, hdc_src)
        return None
    gdi32.SelectObject(hdc_dst, hbmp)
    if not gdi32.BitBlt(hdc_dst, 0, 0, width, height, hdc_src, 0, 0, 0x00CC0020):
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_dst)
        user32.ReleaseDC(hwnd_desktop, hdc_src)
        return None
    info = _BitmapInfo()
    info.biSize = ctypes.sizeof(_BitmapInfo)
    info.biWidth = width
    info.biHeight = -height
    info.biPlanes = 1
    info.biBitCount = 32
    buffer = (ctypes.c_char * (width * height * 4))()
    got = gdi32.GetDIBits(hdc_dst, hbmp, 0, height, buffer, ctypes.byref(info), 0)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_dst)
    user32.ReleaseDC(hwnd_desktop, hdc_src)
    if not got:
        return None
    bgra = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
    return np.ascontiguousarray(bgra[:, :, :3])


class ScreenPresenceTracker:
    """Samples the primary monitor on an interval and reports stuck-on-screen state."""

    def __init__(
        self,
        config: ScreenPresenceConfig | None = None,
        *,
        grabber: ScreenGrabber | None = None,
        window_meta_fn: WindowMetaFn | None = None,
        input_age_fn: InputAgeFn | None = None,
        secure_fn: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Assemble grabber, window-meta, and timing; capture stays off until enabled."""
        self.config = config or ScreenPresenceConfig()
        self._grabber = grabber if grabber is not None else grab_primary_monitor
        self._window_meta_fn = window_meta_fn if window_meta_fn is not None else read_foreground_window
        self._input_age_fn = input_age_fn if input_age_fn is not None else seconds_since_input
        self._secure_fn = secure_fn if secure_fn is not None else desktop_is_secure
        self._clock = clock
        self._baseline: ScreenFingerprint | None = None
        self._stable_since: float | None = None
        self._window_key: tuple[str, str] | None = None
        self._stuck = False
        self._last_capture_at = 0.0
        self._last_snapshot = ScreenPresenceSnapshot()
        self._capture_count = 0
        self._debug_saves = 0
        self._announced = False

    @property
    def capture_count(self) -> int:
        """How many times the grabber has been invoked."""
        return self._capture_count

    @property
    def debug_saves(self) -> int:
        """How many debug frames were written; stays 0 unless debug_save is on."""
        return self._debug_saves

    def tick(self, *, user_present: bool, now: float | None = None) -> ScreenPresenceSnapshot:
        """Advance the FSM; captures only when enabled and the interval has elapsed."""
        if not self.config.enabled:
            self._reset()
            self._last_snapshot = ScreenPresenceSnapshot()
            return self._last_snapshot
        now = self._clock() if now is None else now
        occupied = present_for_desktop(
            face_present=user_present,
            seconds_since_user_signal=self._input_age_fn(),
            hold_s=self.config.input_hold_s,
        )
        if now - self._last_capture_at < self.config.interval_sec and self._last_capture_at > 0.0:
            snapshot = self._last_snapshot
            if snapshot.stuck and occupied:
                return ScreenPresenceSnapshot(
                    stuck=True,
                    became_stuck=False,
                    observation_label=snapshot.observation_label,
                    salience=_salience(snapshot.duration_s + (now - self._last_capture_at), self.config.stuck_seconds),
                    similarity=snapshot.similarity,
                    duration_s=snapshot.duration_s + (now - self._last_capture_at),
                    window=snapshot.window,
                    captured=False,
                )
            return snapshot
        snapshot = self._sample(occupied=occupied, now=now)
        self._last_snapshot = snapshot
        return snapshot

    def _sample(self, *, occupied: bool, now: float) -> ScreenPresenceSnapshot:
        self._announce_once()
        if self._secure_fn():
            self._reset()
            return ScreenPresenceSnapshot()
        window = self._window_meta_fn()
        if window.skip:
            self._reset()
            return ScreenPresenceSnapshot(window=window)
        if not occupied:
            self._reset()
            return ScreenPresenceSnapshot(window=window)
        frame = self._grabber()
        self._capture_count += 1
        self._last_capture_at = now
        if frame is None:
            logger.warning("Screen presence capture returned no frame")
            return ScreenPresenceSnapshot(window=window, captured=True)
        self._maybe_debug_save(frame)
        fingerprint = ScreenFingerprint.from_frame(frame, self.config.max_gray_width)
        del frame
        return self._update_fsm(fingerprint, window, now)

    def _update_fsm(self, fingerprint: ScreenFingerprint, window: WindowMeta, now: float) -> ScreenPresenceSnapshot:
        similarity = 1.0
        window_changed = (
            self.config.require_same_window and self._window_key is not None and window.identity != self._window_key
        )
        if self._baseline is None or window_changed:
            self._baseline = fingerprint
            self._stable_since = now
            self._window_key = window.identity
            self._stuck = False
            similarity = 1.0
        else:
            similarity = fingerprint.similarity(self._baseline)
            if similarity < self.config.similarity:
                self._baseline = fingerprint
                self._stable_since = now
                self._window_key = window.identity
                self._stuck = False
        duration = 0.0 if self._stable_since is None else now - self._stable_since
        was_stuck = self._stuck
        self._stuck = duration >= self.config.stuck_seconds
        label = observation_label_for(window) if self._stuck else None
        if self._stuck and not was_stuck:
            logger.info("Screen presence stuck on %s (%.0fs, similarity %.3f)", label, duration, similarity)
        return ScreenPresenceSnapshot(
            stuck=self._stuck,
            became_stuck=self._stuck and not was_stuck,
            observation_label=label,
            salience=_salience(duration, self.config.stuck_seconds) if self._stuck else 0.0,
            similarity=similarity,
            duration_s=duration,
            window=window,
            captured=True,
        )

    def _reset(self) -> None:
        self._baseline = None
        self._stable_since = None
        self._window_key = None
        self._stuck = False

    def _announce_once(self) -> None:
        if self._announced or not self.config.indicator:
            return
        self._announced = True
        logger.info("Screen presence monitoring on (fingerprints only; no frames stored)")

    def _maybe_debug_save(self, frame: NDArray[np.uint8]) -> None:
        if not self.config.debug_save:
            return
        directory = self.config.debug_dir
        if directory is None:
            logger.warning("Screen debug save enabled without a directory; skipping")
            return
        try:
            import cv2
        except ImportError:
            logger.warning("Screen debug save skipped: OpenCV is not installed")
            return
        try:
            directory.mkdir(parents=True, exist_ok=True)
            gray = downscale_gray(frame, self.config.max_gray_width)
            path = directory / f"screen_{int(self._clock())}.png"
            if not cv2.imwrite(str(path), gray):
                logger.warning("Screen debug save failed to write %s", path)
                return
            self._debug_saves += 1
        except Exception as exc:
            logger.warning("Screen debug save failed: %s", exc)


def _salience(duration_s: float, stuck_seconds: float) -> float:
    if stuck_seconds <= 0:
        return 1.0
    return min(1.0, 0.45 + 0.55 * min(duration_s / stuck_seconds, 2.0) / 2.0)
