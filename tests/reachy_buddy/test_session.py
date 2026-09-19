"""Tests for buddy session greet/farewell, recognition, and curiosity speech."""

import time
from dataclasses import replace
from unittest.mock import MagicMock
from collections.abc import Callable

import numpy as np

from reachy_buddy.session import (
    BREAK_INSTRUCTION,
    GREET_INSTRUCTION,
    FAREWELL_INSTRUCTION,
    BuddySession,
    checkin_instruction,
    named_greet_instruction,
    stuck_screen_instruction,
    speak_thought_instruction,
)
from reachy_buddy.animation.gaze import GazeController
from reachy_buddy.core.curiosity import CuriosityEngine
from reachy_buddy.core.monologue import ThoughtStream, ThoughtContext
from reachy_buddy.vision.presence import TrackedFace
from reachy_buddy.core.personality import Personality
from reachy_buddy.core.world_model import WorldModel
from reachy_buddy.animation.planner import AnimationPlanner
from reachy_buddy.conversation.flow import ConversationFlow, ConversationPhase
from reachy_buddy.vision.window_meta import window_meta_from_parts
from reachy_buddy.core.emotional_state import EmotionalState
from reachy_buddy.memory.relationships import TAG_ACTIVITY, CallbackCandidate
from reachy_buddy.animation.pose_buffer import PoseBuffer, PoseBufferSink
from reachy_buddy.vision.screen_presence import ScreenPresenceConfig, ScreenPresenceTracker


class _Tracker:
    """Presence tracker double exposing a public primary face."""

    def __init__(self, face: TrackedFace | None) -> None:
        self.primary = face
        self.landmarks: list[np.ndarray] = []


class _Loop:
    """Presence loop double."""

    def __init__(self, face: TrackedFace | None) -> None:
        self.tracker = _Tracker(face)
        self.latest_frame = np.zeros((16, 16, 3), dtype=np.uint8)


def _session(
    face: TrackedFace | None = None,
    *,
    recognizer: MagicMock | None = None,
    memory: MagicMock | None = None,
    break_after_s: float = 2700.0,
    reply_timeout_s: float = 90.0,
    screen_presence: ScreenPresenceTracker | None = None,
    clock: Callable[[], float] | None = None,
) -> tuple[BuddySession, list[str]]:
    mood = EmotionalState()
    buffer = PoseBuffer()
    personality = Personality()
    spoken: list[str] = []
    session = BuddySession(
        world_model=WorldModel(),
        curiosity=CuriosityEngine(personality=personality),
        mood=mood,
        flow=ConversationFlow(greet_after_seconds=0.0, farewell_after_seconds=0.0),
        gaze=GazeController(),
        personality=personality,
        drives=replace(personality.baseline),
        thoughts=ThoughtStream(personality=personality),
        planner=AnimationPlanner(mood, PoseBufferSink(buffer)),
        pose_buffer=buffer,
        handler=MagicMock(),
        movement_manager=MagicMock(),
        presence_loop=_Loop(face),
        recognizer=recognizer,
        memory=memory,
        break_after_s=break_after_s,
        reply_timeout_s=reply_timeout_s,
        screen_presence=screen_presence,
        clock=time.monotonic if clock is None else clock,
    )

    def begin(instruction: str, after: object, glance: object = None) -> None:
        spoken.append(instruction)
        if callable(after):
            after()

    session._begin_utterance = begin  # type: ignore[method-assign]
    return session, spoken


def test_greeting_fires_once_a_face_is_present() -> None:
    """Presence with zero dwell asks the voice loop to greet, then engages."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    session, spoken = _session(face)

    session.tick()

    assert spoken == [GREET_INSTRUCTION]
    assert session.flow.phase is ConversationPhase.ENGAGED


def test_named_greeting_uses_the_recognized_person() -> None:
    """A known face is greeted by name."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    recognizer = MagicMock()
    recognizer.identify.return_value = ["Jon"]
    session, spoken = _session(face, recognizer=recognizer)

    session.tick()

    assert spoken == [named_greet_instruction("Jon")]
    assert session._person_label == "Jon"


def test_farewell_fires_after_the_face_leaves_engagement() -> None:
    """Once engaged, a lost face produces a single goodbye instruction."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    session, spoken = _session(face)
    session.tick()
    spoken.clear()
    assert session.presence_loop is not None
    session.presence_loop.tracker.primary = None

    session.tick()
    session.tick()

    assert spoken == [FAREWELL_INSTRUCTION]
    assert session.flow.phase is ConversationPhase.ALONE


def test_thoughts_do_not_speak_when_alone() -> None:
    """Private thoughts stay internal when nobody is present."""
    session, spoken = _session()
    session.thoughts._next_due_at = 0.0

    session.tick()

    assert spoken == []


def test_curiosity_asks_about_a_novel_object_once_engaged() -> None:
    """After greeting, a new object can become a spoken question."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    session, spoken = _session(face)
    session.tick()
    spoken.clear()
    session.world_model.record("mug", 0.9, kind="object", salience=0.8, center=(0.2, 0.4))
    session.drives.curiosity = 0.95
    session.curiosity._last_proactive_at = time.time() - 999.0

    session.tick()

    assert any("mug" in line for line in spoken)


def _quiet_after_greet(session: BuddySession) -> None:
    session._asked_work_this_visit = True
    session.curiosity.mark_seen("what they're working on")
    session.drives.curiosity = 0.4
    session.drives.playfulness = 0.3
    session.curiosity._last_proactive_at = time.time() - 999.0
    session.thoughts._next_due_at = time.time() + 10_000


def test_stated_activity_is_queued_for_hindsight() -> None:
    """An answer about current work is tagged as an activity memory."""
    session, _spoken = _session()
    session._person_label = "Jon"
    session._awaiting_activity = True

    session._on_transcript("user", "the CAD mount", True)

    activities = [item for item in session._pending_memories if TAG_ACTIVITY in item.tags]
    assert len(activities) == 1
    assert activities[0].content == "the CAD mount"


def test_spoken_name_is_kept_when_face_enroll_fails() -> None:
    """A parsed name still labels the visit if the camera cannot enroll."""
    session, _spoken = _session()
    session._awaiting_name = True
    session._person_label = "unknown"

    session._on_transcript("user", "my name is Jon", True)

    assert session._person_label == "Jon"
    assert session._awaiting_name is False
    assert session._pending_enroll_name == "Jon"


def test_failed_enroll_retries_while_the_face_stays() -> None:
    """A missed encoding is retried on later ticks while presence holds."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    recognizer = MagicMock()
    recognizer.identify.return_value = []
    recognizer.enroll.side_effect = [False, True]
    session, _spoken = _session(face, recognizer=recognizer)
    session.tick()
    session._on_transcript("user", "my name is John", True)
    assert session._pending_enroll_name == "John"
    session._speaking = False
    session._next_enroll_retry_at = 0.0

    session.tick()

    assert recognizer.enroll.call_count == 2
    assert session._pending_enroll_name is None


def test_try_again_retries_pending_face_enroll() -> None:
    """Asking to try again re-attempts enroll with the name we already have."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    recognizer = MagicMock()
    recognizer.identify.return_value = []
    recognizer.enroll.side_effect = [False, True]
    session, _spoken = _session(face, recognizer=recognizer)
    session._on_transcript("user", "My name is John.", True)
    assert session._pending_enroll_name == "John"

    session._on_transcript("user", "Let's try again my face.", True)

    assert recognizer.enroll.call_count == 2
    assert session._pending_enroll_name is None


def test_unfinished_project_checkin_is_spoken_when_engaged() -> None:
    """A named visit can raise one Hindsight callback as a check-in."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    recognizer = MagicMock()
    recognizer.identify.return_value = ["Jon"]
    session, spoken = _session(face, recognizer=recognizer)
    session.tick()
    spoken.clear()
    _quiet_after_greet(session)
    session._pending_checkin = CallbackCandidate(
        fact_text="CAD mount",
        days_since=3,
        question="Did the CAD mount work?",
        origin="template",
    )

    session.tick()

    assert spoken == [
        checkin_instruction(
            CallbackCandidate("CAD mount", 3, "Did the CAD mount work?", "template"),
        )
    ]
    assert session._offered_checkin is True


def test_speak_worthy_thought_can_be_voiced_when_engaged() -> None:
    """A high-salience thought is spoken in character once someone is present."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    session, spoken = _session(face)
    session.tick()
    spoken.clear()
    _quiet_after_greet(session)

    class _HighThought:
        def generate(self, context: ThoughtContext) -> tuple[str, float]:
            return "You've been at that terminal a while", 0.95

    session.thoughts = ThoughtStream(personality=session.personality, generator=_HighThought())
    session.thoughts._next_due_at = 0.0
    session._last_speech_at = session._clock() - 900.0

    session.tick()

    assert spoken == [speak_thought_instruction("You've been at that terminal a while")]


def test_long_visit_suggests_a_break() -> None:
    """After a long stretch of presence, Reachy suggests a stretch."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    session, spoken = _session(face, break_after_s=0.0)
    session.tick()
    spoken.clear()
    _quiet_after_greet(session)
    session._visit_started_at = session._clock() - 1.0

    session.tick()

    assert spoken == [BREAK_INSTRUCTION]
    assert session._suggested_break_this_visit is True


def test_ignored_prompt_lowers_engagement() -> None:
    """Silence after a prompt is treated as ignored, not as an answer."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    session, spoken = _session(face, reply_timeout_s=1.0)
    session.tick()
    spoken.clear()
    _quiet_after_greet(session)
    session._awaiting_reply = True
    session._last_speech_at = session._clock() - 2.0
    before = session.curiosity.engagement

    session.tick()

    assert session._awaiting_reply is False
    assert session.curiosity.engagement < before
    assert spoken == []


def test_farewell_digests_a_named_visit() -> None:
    """Leaving after a named visit retains a session digest when memory is available."""
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    recognizer = MagicMock()
    recognizer.identify.return_value = ["Jon"]
    session, spoken = _session(face, recognizer=recognizer, memory=MagicMock())
    session.tick()
    spoken.clear()
    digested: list[tuple[str | None, str]] = []
    session._schedule_digest = lambda person, summary: digested.append((person, summary))  # type: ignore[method-assign]
    assert session.presence_loop is not None
    session.presence_loop.tracker.primary = None

    session.tick()
    session.tick()

    assert spoken == [FAREWELL_INSTRUCTION]
    assert len(digested) == 1
    assert digested[0][0] == "Jon"
    assert digested[0][1]


class _Clock:
    """Session/screen clock the tests can step."""

    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _screen_tracker(clock: _Clock, enabled: bool = True) -> ScreenPresenceTracker:
    return ScreenPresenceTracker(
        ScreenPresenceConfig(
            enabled=enabled,
            interval_sec=0.0,
            stuck_min=1.0 / 60.0,
            indicator=False,
        ),
        grabber=lambda: np.full((90, 160, 3), 48, dtype=np.uint8),
        window_meta_fn=lambda: window_meta_from_parts("Code.exe", "app.py — workspace"),
        input_age_fn=lambda: None,
        secure_fn=lambda: False,
        clock=clock,
    )


def test_session_records_stuck_desktop_observation() -> None:
    """Enabled + static screen + presence for T writes desktop:stuck:Code."""
    clock = _Clock()
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    session, _spoken = _session(face, screen_presence=_screen_tracker(clock), clock=clock)

    session.tick()
    assert session.world_model.of_kind("desktop") == []
    clock.advance(1.0)
    session.tick()

    labels = [obs.label for obs in session.world_model.of_kind("desktop")]
    assert labels == ["desktop:stuck:Code"]
    assert session.screen_presence is not None
    assert session.screen_presence.capture_count >= 1


def test_session_can_check_in_about_a_stuck_screen() -> None:
    """Curiosity may voice one stuck-screen check-in, then cools down."""
    clock = _Clock()
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    session, spoken = _session(face, screen_presence=_screen_tracker(clock), clock=clock)
    session.tick()
    spoken.clear()
    _quiet_after_greet(session)
    session.drives.playfulness = 0.0
    clock.advance(1.0)
    session.tick()

    assert spoken == [stuck_screen_instruction("Code")]
    spoken.clear()
    session.curiosity._last_proactive_at = time.time() - 999.0
    session.tick()
    assert spoken == []


def test_disabled_screen_presence_never_captures_or_records() -> None:
    """Toggle off means zero captures and no desktop observations."""
    clock = _Clock()
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    tracker = _screen_tracker(clock, enabled=False)
    session, spoken = _session(face, screen_presence=tracker, clock=clock)
    session.tick()
    clock.advance(1.0)
    session.tick()

    assert tracker.capture_count == 0
    assert session.world_model.of_kind("desktop") == []
    assert all("screen change" not in line for line in spoken)


def test_stuck_screen_does_not_queue_hindsight_images() -> None:
    """Screen fingerprints stay local; Hindsight only ever sees text memories."""
    clock = _Clock()
    face = TrackedFace(center=(0.5, 0.5), size=0.2, last_seen=1.0)
    session, _spoken = _session(face, screen_presence=_screen_tracker(clock), clock=clock)
    session.tick()
    clock.advance(1.0)
    session.tick()

    assert session.world_model.of_kind("desktop")
    assert all(isinstance(item.content, str) for item in session._pending_memories)
    assert all("desktop:stuck" not in item.content for item in session._pending_memories)
    assert session.screen_presence is not None
    assert session.screen_presence.debug_saves == 0
