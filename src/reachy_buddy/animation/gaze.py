"""Gaze behavior: idle wander, face tracking, pre-speech shifts, and expressive posture."""

import time
import random
import logging
import threading
from enum import Enum
from dataclasses import dataclass
from collections.abc import Callable

from reachy_buddy.animation.eye_contact import EyeContactController


logger = logging.getLogger(__name__)

PRE_SPEECH_SHIFT_SECONDS = 0.3

_TRACKING_RATE = 5.0
_SPEAKING_TRACKING_RATE = 3.0
_SHIFT_RATE = 10.0
_IDLE_RATE = 2.0


class GazeMode(Enum):
    """Which behavior currently owns the gaze target."""

    IDLE = "idle"
    TRACKING = "tracking"
    PRE_SPEECH = "pre_speech"
    GLANCE = "glance"


@dataclass(frozen=True)
class GazeCommand:
    """One head-movement instruction: look angles, posture offsets, and move duration."""

    yaw_degrees: float
    pitch_degrees: float
    roll_degrees: float
    forward_m: float
    duration_seconds: float


class GazeController:
    """Arbitrates idle wander, face tracking, and speech glances into one smooth gaze."""

    def __init__(
        self,
        eye_contact: EyeContactController | None = None,
        rng: random.Random | None = None,
        idle_yaw_range: float = 25.0,
        idle_pitch_range: float = 12.0,
    ) -> None:
        """Initialize with the eye-contact mapper, an optional seeded RNG, and idle ranges."""
        self._eye_contact = eye_contact or EyeContactController()
        self._rng = rng or random.Random()
        self.idle_yaw_range = idle_yaw_range
        self.idle_pitch_range = idle_pitch_range
        self.mode = GazeMode.IDLE
        self._yaw = 0.0
        self._pitch = 0.0
        self._target_yaw = 0.0
        self._target_pitch = 0.0
        self._face_center: tuple[float, float] | None = None
        self._speaking = False
        self._next_saccade_at = 0.0
        self._pre_speech_ready_at = 0.0
        self._glance_until = 0.0
        self._resume_after_glance: tuple[GazeMode, float, float] | None = None
        self._roll = 0.0
        self._roll_until = 0.0
        self._forward = 0.0
        self._forward_until = 0.0
        self._last_update: float | None = None

    def track_face(self, face_center: tuple[float, float] | None) -> None:
        """Update the currently visible face position, or None when no face is seen."""
        self._face_center = face_center

    def set_speaking(self, speaking: bool) -> None:
        """Mark whether the buddy is speaking; speaking calms tracking into eye contact."""
        self._speaking = speaking

    def prepare_speech(self, face_center: tuple[float, float] | None = None, now: float | None = None) -> float:
        """Shift gaze toward the listener before speaking; return the wait before speech."""
        now = time.monotonic() if now is None else now
        target = face_center or self._face_center
        if target is not None:
            self._target_yaw, self._target_pitch = self._eye_contact.gaze_angles(target)
        else:
            self._target_yaw, self._target_pitch = 0.0, 0.0
        self._set_mode(GazeMode.PRE_SPEECH)
        self._pre_speech_ready_at = now + PRE_SPEECH_SHIFT_SECONDS
        return PRE_SPEECH_SHIFT_SECONDS

    def speech_ready(self, now: float | None = None) -> bool:
        """Whether the pre-speech shift has landed and speech may start."""
        now = time.monotonic() if now is None else now
        return self.mode is not GazeMode.PRE_SPEECH or now >= self._pre_speech_ready_at

    def glance_at(
        self, yaw_degrees: float, pitch_degrees: float, dwell_seconds: float = 0.7, now: float | None = None
    ) -> None:
        """Glance at a direction (e.g. an object about to be mentioned), then resume."""
        now = time.monotonic() if now is None else now
        if self.mode is not GazeMode.GLANCE:
            resume_mode = GazeMode.TRACKING if self._face_center is not None else GazeMode.IDLE
            self._resume_after_glance = (resume_mode, self._target_yaw, self._target_pitch)
        self._set_mode(GazeMode.GLANCE)
        self._target_yaw = yaw_degrees
        self._target_pitch = pitch_degrees
        self._glance_until = now + dwell_seconds

    def express_uncertainty(
        self, roll_degrees: float = 14.0, hold_seconds: float = 2.0, now: float | None = None
    ) -> None:
        """Tilt the head for a while, the way people do when unsure."""
        now = time.monotonic() if now is None else now
        self._roll = roll_degrees
        self._roll_until = now + hold_seconds

    def express_interest(self, forward_m: float = 0.02, hold_seconds: float = 2.5, now: float | None = None) -> None:
        """Lean toward the speaker for a while to signal engagement."""
        now = time.monotonic() if now is None else now
        self._forward = forward_m
        self._forward_until = now + hold_seconds

    def update(self, now: float | None = None) -> GazeCommand:
        """Advance the gaze state machine and return the head command for this tick."""
        now = time.monotonic() if now is None else now
        dt = 0.05 if self._last_update is None else min(0.5, max(0.0, now - self._last_update))
        self._last_update = now
        self._tick_mode(now)
        blend = min(1.0, self._smoothing_rate() * dt)
        self._yaw += (self._target_yaw - self._yaw) * blend
        self._pitch += (self._target_pitch - self._pitch) * blend
        return GazeCommand(self._yaw, self._pitch, self._posture_roll(now), self._posture_forward(now), max(dt, 0.02))

    def _tick_mode(self, now: float) -> None:
        if self.mode is GazeMode.PRE_SPEECH:
            if now >= self._pre_speech_ready_at:
                self._set_mode(GazeMode.TRACKING if self._face_center is not None else GazeMode.IDLE)
        elif self.mode is GazeMode.GLANCE:
            if now >= self._glance_until and self._resume_after_glance is not None:
                resume_mode, self._target_yaw, self._target_pitch = self._resume_after_glance
                self._resume_after_glance = None
                self._set_mode(resume_mode)
        elif self._face_center is not None:
            self._set_mode(GazeMode.TRACKING)
            self._target_yaw, self._target_pitch = self._eye_contact.gaze_angles(self._face_center)
        else:
            self._set_mode(GazeMode.IDLE)
            self._idle_saccade(now)

    def _idle_saccade(self, now: float) -> None:
        if now < self._next_saccade_at:
            return
        self._target_yaw = self._rng.uniform(-self.idle_yaw_range, self.idle_yaw_range)
        self._target_pitch = self._rng.uniform(-self.idle_pitch_range, self.idle_pitch_range)
        self._next_saccade_at = now + self._rng.uniform(1.2, 3.5)

    def _smoothing_rate(self) -> float:
        if self.mode in (GazeMode.PRE_SPEECH, GazeMode.GLANCE):
            return _SHIFT_RATE
        if self.mode is GazeMode.TRACKING:
            return _SPEAKING_TRACKING_RATE if self._speaking else _TRACKING_RATE
        return _IDLE_RATE

    def _posture_roll(self, now: float) -> float:
        if now >= self._roll_until:
            self._roll = 0.0
        return self._roll

    def _posture_forward(self, now: float) -> float:
        if now >= self._forward_until:
            self._forward = 0.0
        return self._forward

    def _set_mode(self, mode: GazeMode) -> None:
        if mode is not self.mode:
            logger.debug("gaze mode %s -> %s", self.mode.value, mode.value)
            self.mode = mode


class GazeLoop:
    """Background thread issuing GazeController commands to a sink at a fixed rate."""

    def __init__(
        self,
        controller: GazeController,
        command_sink: Callable[[GazeCommand], None],
        updates_per_second: float = 15.0,
    ) -> None:
        """Initialize with the controller, the command sink, and the update rate."""
        self._controller = controller
        self._command_sink = command_sink
        self._interval = 1.0 / updates_per_second
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="reachy-buddy-gaze", daemon=True)

    def start(self) -> None:
        """Start the update thread."""
        self._thread.start()

    def stop(self) -> None:
        """Signal the update thread to stop and wait for it to exit."""
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._command_sink(self._controller.update())
            self._stop.wait(self._interval)
