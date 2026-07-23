"""Animation planner: maps emotional state to continuous, smooth body motion."""

import math
import time
import logging
from collections import deque
from dataclasses import dataclass
from collections.abc import Callable

from reachy_buddy.animation.idle import IdleMotionEngine
from reachy_buddy.animation.pose import BodyPose
from reachy_buddy.animation.sink import PoseSink
from reachy_buddy.animation.program import GestureProgram
from reachy_buddy.animation.gestures import GestureLibrary
from reachy_buddy.core.emotional_state import Emotion, EmotionalState


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GestureCue:
    """A named gesture request; yaw/pitch aim the targeted gestures."""

    name: str
    yaw_degrees: float = 0.0
    pitch_degrees: float = 0.0


def _approach(current: float, target: float, max_delta: float) -> float:
    """Move current toward target by at most max_delta."""
    return current + min(max_delta, max(-max_delta, target - current))


class AnimationPlanner:
    """Owns non-conversation motion: idle micro-motion, gesture queue, and state transitions."""

    def __init__(
        self,
        mood: EmotionalState,
        sink: PoseSink | None = None,
        *,
        library: GestureLibrary | None = None,
        idle: IdleMotionEngine | None = None,
        transition_tau_s: float = 0.7,
        max_slew_deg_s: float = 170.0,
        max_slew_rad_s: float = 4.0,
        max_queue: int = 4,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize around a shared emotional state and an optional pose sink."""
        self._mood = mood
        self._sink = sink
        self._library = library if library is not None else GestureLibrary()
        self._idle = idle if idle is not None else IdleMotionEngine()
        self._transition_tau_s = transition_tau_s
        self._max_slew_deg_s = max_slew_deg_s
        self._max_slew_rad_s = max_slew_rad_s
        self._max_queue = max_queue
        self._clock = clock

        self._style = self._idle.style(mood.emotion)
        self._running: GestureProgram | None = None
        self._started_at = 0.0
        self._queue: deque[GestureProgram] = deque()
        self._engaged = False
        self._last_tick: float | None = None
        self._next_idle_at = self._clock() + self._idle.next_interval(mood.emotion)
        self.current_pose = BodyPose()

    @property
    def busy(self) -> bool:
        """True while a gesture is playing or queued, so speech can wait for the body."""
        return self._running is not None or bool(self._queue)

    def set_engaged(self, engaged: bool) -> None:
        """Mark active conversation: idle gestures pause while micro-motion continues."""
        self._engaged = engaged

    def play(self, cue: GestureCue) -> float:
        """Play a gesture now or queue it behind the running one; return its duration."""
        program = self._library.build(cue.name, cue.yaw_degrees, cue.pitch_degrees)
        if self._running is None:
            self._running = program
            self._started_at = self._clock()
        elif len(self._queue) < self._max_queue:
            self._queue.append(program)
        else:
            logger.warning("Gesture queue full; dropping %s", cue.name)
        return program.duration

    def tick(self) -> None:
        """Advance the animation state and emit the current pose to the sink."""
        now = self._clock()
        dt = 0.0 if self._last_tick is None else max(0.0, now - self._last_tick)
        self._last_tick = now

        emotion = self._mood.emotion
        target_style = self._idle.style(emotion)
        blend = 1.0 - math.exp(-dt / self._transition_tau_s) if dt > 0.0 else 0.0
        self._style = self._style.lerp(target_style, blend)

        self.current_pose = self._limit_slew(self._active_pose(now, emotion), dt)
        if self._sink is not None:
            self._sink.apply(self.current_pose, max(dt, 0.05))

    def _active_pose(self, now: float, emotion: Emotion) -> BodyPose:
        """Compute the pose target from the gesture state machine or the idle style."""
        if self._running is not None and now - self._started_at >= self._running.duration:
            self._running = None
            self._next_idle_at = now + self._idle.next_interval(emotion)
        if self._running is None and self._queue:
            self._running = self._queue.popleft()
            self._started_at = now
        if self._running is None and not self._engaged and now >= self._next_idle_at:
            self._running = self._library.build(self._idle.choose_gesture(emotion))
            self._started_at = now
            self._next_idle_at = now + self._idle.next_interval(emotion)
        if self._running is not None:
            return self._running.evaluate(now - self._started_at)
        return self._style.base_pose + self._idle.micro_motion(self._style, now)

    def _limit_slew(self, target: BodyPose, dt: float) -> BodyPose:
        """Rate-limit the output pose so no transition ever jumps."""
        if dt <= 0.0:
            return target
        max_deg = self._max_slew_deg_s * dt
        max_rad = self._max_slew_rad_s * dt
        pose = self.current_pose
        return BodyPose(
            yaw=_approach(pose.yaw, target.yaw, max_deg),
            pitch=_approach(pose.pitch, target.pitch, max_deg),
            roll=_approach(pose.roll, target.roll, max_deg),
            antenna_left=_approach(pose.antenna_left, target.antenna_left, max_rad),
            antenna_right=_approach(pose.antenna_right, target.antenna_right, max_rad),
        )
