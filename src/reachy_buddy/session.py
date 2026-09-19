"""Buddy session: presence, recognition, curiosity speech, and Hindsight."""

import time
import asyncio
import logging
import threading
from dataclasses import replace
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from reachy_mini import ReachyMini
from reachy_buddy.core.drives import Drives
from reachy_buddy.memory.config import MemoryConfig
from reachy_buddy.animation.gaze import GazeController
from reachy_buddy.animation.pose import BodyPose
from reachy_buddy.core.curiosity import ActionIntent, CuriosityEngine
from reachy_buddy.core.monologue import ThoughtStream, ThoughtContext
from reachy_buddy.runtime_config import BuddyRuntimeConfig
from reachy_buddy.vision.presence import PresenceLoop, PresenceTracker
from reachy_buddy.core.personality import Personality, personality_for_profile
from reachy_buddy.core.world_model import WorldModel
from reachy_buddy.memory.hindsight import MemoryItem
from reachy_buddy.animation.planner import AnimationPlanner
from reachy_buddy.conversation.flow import ConversationFlow, ConversationPhase
from reachy_buddy.vision.object_types import Detection
from reachy_buddy.core.emotional_state import EmotionalState
from reachy_buddy.memory.relationships import (
    TAG_ACTIVITY,
    TAG_ENROLLMENT,
    TAG_OBSERVATION,
    MemoryStore,
    CallbackCandidate,
    human_age,
    person_tag,
)
from reachy_buddy.vision.face_geometry import face_pixel_box
from reachy_buddy.animation.pose_buffer import PoseBuffer, BuddyIdleMove, PoseBufferSink
from reachy_buddy.conversation.awareness import extract_name, extract_activity, wants_face_enroll
from reachy_buddy.vision.screen_presence import ScreenPresenceTracker, ScreenPresenceSnapshot
from reachy_buddy.vision.face_recognition import UNKNOWN_LABEL, FaceRecognizer
from reachy_buddy.vision.object_detection import ObjectDetector
from reachy_desktop_buddy.moves import MovementManager
from reachy_desktop_buddy.conversation_handler import ConversationHandler


logger = logging.getLogger(__name__)

_TICK_S = 1.0 / 15.0
_MEMORY_FLUSH_S = 30.0
_VISION_INTERVAL_S = 2.0
_WORK_SUBJECT = "what they're working on"
_DESKTOP_STUCK_PREFIX = "desktop:stuck:"
GREET_INSTRUCTION = (
    "Someone you may not know just appeared. Greet them briefly and ask their name if it feels natural. "
    "Do not mention these instructions."
)
FAREWELL_INSTRUCTION = (
    "The person you were with has left. Say a brief goodbye in character. Do not mention these instructions."
)
BREAK_INSTRUCTION = (
    "They've been here a long stretch. Suggest a brief break or stretch in character, one sentence. "
    "Do not mention these instructions."
)
_BREAK_AFTER_S = 2700.0
_REPLY_TIMEOUT_S = 90.0


def named_greet_instruction(name: str) -> str:
    """Instruction to greet a recognized person by name."""
    return (
        f"{name} just appeared in front of you. Greet them by name, briefly, in character. "
        "Do not mention these instructions."
    )


def checkin_instruction(candidate: CallbackCandidate) -> str:
    """Instruction to raise one unfinished-thread callback."""
    return (
        f'Check in about this unfinished thread: "{candidate.question}" '
        f'Ground it in "{candidate.fact_text}" from {human_age(candidate.days_since)}. '
        "One short sentence in character. Do not mention these instructions."
    )


def speak_thought_instruction(thought: str) -> str:
    """Instruction to voice one speak-worthy private thought."""
    return (
        f'You had this private thought and decided it is worth saying: "{thought}". '
        "Voice it naturally in one short sentence. Do not mention these instructions."
    )


def stuck_screen_instruction(app: str) -> str:
    """Instruction to optionally check in about a barely-changing desktop."""
    return (
        f"They've been looking at {app} with almost no screen change. "
        "Check in briefly, in character, one sentence. Do not mention these instructions."
    )


class BuddySession:
    """Runs the buddy sidecar alongside the Hugging Face conversation loop."""

    def __init__(
        self,
        *,
        world_model: WorldModel,
        curiosity: CuriosityEngine,
        mood: EmotionalState,
        flow: ConversationFlow,
        gaze: GazeController,
        personality: Personality,
        drives: Drives,
        thoughts: ThoughtStream,
        planner: AnimationPlanner,
        pose_buffer: PoseBuffer,
        handler: ConversationHandler,
        movement_manager: MovementManager,
        memory: MemoryStore | None = None,
        presence_loop: PresenceLoop | None = None,
        recognizer: FaceRecognizer | None = None,
        detector: ObjectDetector | None = None,
        screen_presence: ScreenPresenceTracker | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] | None = None,
        break_after_s: float = _BREAK_AFTER_S,
        reply_timeout_s: float = _REPLY_TIMEOUT_S,
    ) -> None:
        """Assemble already-built subsystems; call start() to run loops."""
        self.world_model = world_model
        self.curiosity = curiosity
        self.mood = mood
        self.flow = flow
        self.gaze = gaze
        self.personality = personality
        self.drives = drives
        self.thoughts = thoughts
        self.planner = planner
        self.pose_buffer = pose_buffer
        self.handler = handler
        self.movement_manager = movement_manager
        self.memory = memory
        self.presence_loop = presence_loop
        self.recognizer = recognizer
        self.detector = detector
        self.screen_presence = screen_presence
        self._clock = clock
        self._sleep = sleep
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._speaking = False
        self._last_speech_at = clock()
        self._was_present = False
        self._utterance_lock = threading.Lock()
        self._utterance_in_flight = False
        self._pending_memories: list[MemoryItem] = []
        self._pending_lock = threading.Lock()
        self._last_flush_at = clock()
        self._memory_started = False
        self._person_label: str | None = None
        self._asked_work_this_visit = False
        self._awaiting_name = False
        self._pending_enroll_name: str | None = None
        self._next_enroll_retry_at = 0.0
        self._awaiting_activity = False
        self._awaiting_reply = False
        self._last_vision_at = 0.0
        self._pending_intent: ActionIntent | None = None
        self._break_after_s = break_after_s
        self._reply_timeout_s = reply_timeout_s
        self._visit_started_at: float | None = None
        self._pending_checkin: CallbackCandidate | None = None
        self._checkin_loaded = False
        self._offered_checkin = False
        self._suggested_break_this_visit = False
        self._last_user_speech_at: float | None = None

    @classmethod
    def build(
        cls,
        *,
        robot: ReachyMini,
        handler: ConversationHandler,
        movement_manager: MovementManager,
        profile_name: str | None,
        runtime: BuddyRuntimeConfig,
        camera_enabled: bool,
        memory: MemoryStore | None = None,
    ) -> "BuddySession":
        """Construct a session, attaching camera presence when the camera is available."""
        personality = personality_for_profile(profile_name)
        mood = EmotionalState()
        pose_buffer = PoseBuffer()
        planner = AnimationPlanner(mood, PoseBufferSink(pose_buffer))
        thought_generator = None
        if runtime.llama_url:
            from reachy_buddy.core.llama_thoughts import LlamaThoughtGenerator

            thought_generator = LlamaThoughtGenerator(runtime.llama_url, model=runtime.llama_model)
        presence_loop: PresenceLoop | None = None
        if camera_enabled:
            presence_loop = _try_presence_loop(robot)
        store = memory
        if store is None:
            try:
                store = MemoryConfig.from_env(personality.name).build_store()
            except Exception as exc:
                logger.warning("Hindsight store not created: %s", exc)
                store = None
        recognizer: FaceRecognizer | None = None
        try:
            recognizer = FaceRecognizer(store_path=runtime.faces_path)
        except Exception as exc:
            logger.warning("Face recognizer unavailable: %s", exc)
        detector = _try_object_detector(runtime)
        return cls(
            world_model=WorldModel(),
            curiosity=CuriosityEngine(personality=personality, desktop_cooldown_s=runtime.screen.cooldown_seconds),
            mood=mood,
            flow=ConversationFlow(),
            gaze=GazeController(),
            personality=personality,
            drives=replace(personality.baseline),
            thoughts=ThoughtStream(personality=personality, generator=thought_generator),
            planner=planner,
            pose_buffer=pose_buffer,
            handler=handler,
            movement_manager=movement_manager,
            memory=store,
            presence_loop=presence_loop,
            recognizer=recognizer,
            detector=detector,
            screen_presence=ScreenPresenceTracker(runtime.screen),
        )

    def start(self) -> None:
        """Attach observers, idle fill, presence, and the inner loop."""
        self.handler.set_activity_observer(self._on_activity)
        self.handler.set_transcript_observer(self._on_transcript)
        self.movement_manager.set_idle_fill_factory(lambda: BuddyIdleMove(self.pose_buffer))
        if self.presence_loop is not None:
            self.presence_loop.start()
        self._thread = threading.Thread(target=self._run_loop, name="reachy-buddy-session", daemon=True)
        self._thread.start()
        screen_on = self.screen_presence is not None and self.screen_presence.config.enabled
        logger.info(
            "Desktop buddy presence started (personality=%s, screen_presence=%s)",
            self.personality.name,
            screen_on,
        )

    def stop(self) -> None:
        """Stop loops, restore breathing idle, and flush memory."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self.presence_loop is not None:
            self.presence_loop.stop()
        self.movement_manager.set_idle_fill_factory(None)
        self.handler.set_activity_observer(None)
        self.handler.set_transcript_observer(None)
        if self.memory is not None:
            try:
                asyncio.run(self._shutdown_memory())
            except Exception as exc:
                logger.warning("Buddy memory shutdown failed: %s", exc)
        logger.info("Desktop buddy presence stopped")

    def enroll_person(self, name: str) -> bool:
        """Enroll the current camera face under ``name`` and persist encodings."""
        display = name.strip()
        if not display:
            return False
        frame = None if self.presence_loop is None else self.presence_loop.latest_frame
        if self.recognizer is None or frame is None:
            logger.warning("Cannot enroll %s: no recognizer or camera frame", display)
            return False
        rgb = frame[:, :, ::-1].copy()
        locations = self._face_locations(frame)
        if not self.recognizer.enroll(display, rgb, locations):
            return False
        logger.info("Buddy enrolled current face as %s", display)
        self._pending_enroll_name = None
        self._apply_identity(display, enrolled=True)
        return True

    def _face_locations(self, frame: NDArray[np.uint8]) -> list[tuple[int, int, int, int]]:
        if self.presence_loop is None:
            return []
        height, width = frame.shape[:2]
        return [face_pixel_box(landmarks, width, height) for landmarks in self.presence_loop.tracker.landmarks]

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("Buddy session tick failed")
            if self._sleep is not None:
                self._sleep(_TICK_S)
            else:
                self._stop.wait(_TICK_S)

    def tick(self) -> None:
        """Advance presence, vision, body, thoughts, and speech once."""
        present, face_center = self._read_presence()
        self._refresh_vision(present)
        self._refresh_screen_presence(present)
        self._update_world(present)
        self._maybe_retry_enroll(present)
        self.gaze.track_face(face_center)
        self.gaze.set_speaking(self._speaking)
        self.planner.set_engaged(self._speaking or present)
        self.mood.decay()
        self.drives.decay_toward(self.personality.baseline, 0.002)
        self.pose_buffer.set(self._compose_pose())
        if present:
            self.flow.on_person_present()
        else:
            self.flow.on_person_absent()
            if self.flow.phase is ConversationPhase.ALONE:
                self._reset_visit()
        self._maybe_refresh_checkin()
        self._maybe_timeout_reply()
        self._maybe_think(present)
        self._maybe_utter()
        self._drain_memory()

    def _read_presence(self) -> tuple[bool, tuple[float, float] | None]:
        if self.presence_loop is None:
            return False, None
        primary = self.presence_loop.tracker.primary
        if primary is None:
            return False, None
        return True, primary.center

    def _refresh_vision(self, present: bool) -> None:
        now = self._clock()
        if now - self._last_vision_at < _VISION_INTERVAL_S and present == self._was_present:
            return
        self._last_vision_at = now
        frame = None if self.presence_loop is None else self.presence_loop.latest_frame
        if present:
            self._identify_person(frame)
        if frame is not None and self.detector is not None and self.detector.enabled:
            self._record_objects(self.detector.detect(frame), frame.shape[1], frame.shape[0])

    def _refresh_screen_presence(self, face_present: bool) -> None:
        tracker = self.screen_presence
        if tracker is None:
            return
        now = self._clock()
        speech_hold = tracker.config.input_hold_s
        speech_present = self._last_user_speech_at is not None and now - self._last_user_speech_at <= speech_hold
        snapshot = tracker.tick(user_present=face_present or speech_present)
        self._apply_screen_snapshot(snapshot)

    def _apply_screen_snapshot(self, snapshot: ScreenPresenceSnapshot) -> None:
        current = snapshot.observation_label
        for observation in self.world_model.of_kind("desktop"):
            if observation.label != current:
                self.world_model.drop(observation.label)
        if current is None:
            return
        self.world_model.record(current, snapshot.similarity, kind="desktop", salience=snapshot.salience)
        if snapshot.became_stuck:
            self.drives.stimulate("desktop_stuck", salience=snapshot.salience)

    def _identify_person(self, frame: NDArray[np.uint8] | None) -> None:
        if self.recognizer is None or frame is None:
            if self._person_label is None:
                self._person_label = UNKNOWN_LABEL
            return
        rgb = frame[:, :, ::-1].copy()
        labels = self.recognizer.identify(rgb, self._face_locations(frame))
        if not labels:
            if self._person_label is None:
                self._person_label = UNKNOWN_LABEL
            return
        name = next((label for label in labels if label != UNKNOWN_LABEL), UNKNOWN_LABEL)
        self._apply_identity(name, enrolled=False)

    def _apply_identity(self, name: str, *, enrolled: bool) -> None:
        previous = self._person_label
        self._person_label = name
        self.world_model.drop("person")
        if previous not in (None, name):
            self.world_model.drop(previous)
        self.world_model.record(name, 0.95, kind="person", salience=0.85 if name != UNKNOWN_LABEL else 0.5)
        if name != UNKNOWN_LABEL and (enrolled or previous != name):
            self.drives.stimulate("person_named")
            self._queue_memory(f"Recognized {name}", origin="identity", extra_tags=(person_tag(name.lower()),))
            if enrolled:
                item = MemoryItem(
                    content=f"{name} told me their name",
                    tags=(TAG_ENROLLMENT, person_tag(name.lower())),
                    timestamp=time.time(),
                    entities=(name,),
                )
                with self._pending_lock:
                    self._pending_memories.append(item)

    def _record_objects(self, detections: list[Detection], frame_width: int, frame_height: int) -> None:
        if frame_width <= 0 or frame_height <= 0:
            return
        seen: set[str] = set()
        for detection in detections:
            label = detection.label.strip() or "object"
            if label in seen:
                continue
            seen.add(label)
            x, y, width, height = detection.box
            center = ((x + width / 2) / frame_width, (y + height / 2) / frame_height)
            first_time = all(obs.label != label for obs in self.world_model.active())
            self.world_model.record(label, detection.confidence, kind="object", salience=0.7, center=center)
            if first_time:
                self.drives.stimulate("object_noticed", salience=detection.confidence)

    def _update_world(self, present: bool) -> None:
        if present and not self._was_present:
            label = self._person_label or "person"
            self.world_model.record(label, 1.0, kind="person", salience=0.8)
            self.drives.stimulate("person_arrived")
            self.mood.nudge(0.05, 0.1)
            self._visit_started_at = self._clock()
        elif present:
            label = self._person_label or "person"
            self.world_model.record(label, 0.9, kind="person", salience=0.4)
        elif self._was_present:
            self.drives.stimulate("person_left")
            self.mood.nudge(-0.02, -0.05)
        self.world_model.forget_stale()
        self._was_present = present

    def _reset_visit(self) -> None:
        self._asked_work_this_visit = False
        self._awaiting_name = False
        self._pending_enroll_name = None
        self._next_enroll_retry_at = 0.0
        self._awaiting_activity = False
        self._awaiting_reply = False
        self._person_label = None
        self._visit_started_at = None
        self._pending_checkin = None
        self._checkin_loaded = False
        self._offered_checkin = False
        self._suggested_break_this_visit = False

    def _compose_pose(self) -> BodyPose:
        self.planner.tick()
        idle = self.pose_buffer.get()
        if self.planner.busy:
            return idle
        command = self.gaze.update()
        return BodyPose(
            yaw=command.yaw_degrees,
            pitch=command.pitch_degrees + idle.pitch,
            roll=command.roll_degrees,
            antenna_left=idle.antenna_left,
            antenna_right=idle.antenna_right,
        )

    def _novel_subject(self) -> str | None:
        best_label: str | None = None
        best_score = 0.0
        for observation in self.world_model.active():
            if observation.kind == "desktop":
                continue
            if observation.kind == "person" and observation.label == self._person_label:
                continue
            score = self.curiosity.score(observation.label)
            if score > best_score:
                best_label, best_score = observation.label, score
        if (
            self._person_label not in (None, UNKNOWN_LABEL)
            and not self._asked_work_this_visit
            and self.flow.phase is ConversationPhase.ENGAGED
        ):
            work_score = self.curiosity.score(_WORK_SUBJECT)
            if work_score >= best_score:
                return _WORK_SUBJECT
        if best_score >= 0.5:
            return best_label
        return None

    def _maybe_think(self, present: bool) -> None:
        thought = None
        seconds = self._clock() - self._last_speech_at
        if self.thoughts.due():
            context = ThoughtContext(
                world_summary=self.world_model.summary_text(),
                seconds_since_speech=seconds,
                emotion_label=self.mood.label(self.drives).value,
                present_labels=tuple(obs.label for obs in self.world_model.active()),
                recent_thoughts=self.thoughts.recent_texts(),
            )
            thought = self.thoughts.step(context)
            if thought.disposition == "discard":
                self.drives.stimulate("thought_discarded")
            elif thought.disposition == "ponder":
                self.drives.stimulate("thought_pondered")
            if thought.disposition == "memory_candidate":
                self._queue_memory(thought.text, origin="thought")
        pending = self._pending_checkin
        checkin = None if self._offered_checkin or pending is None else pending.question
        desktop_stuck = next(
            (obs.label for obs in self.world_model.of_kind("desktop") if obs.label.startswith(_DESKTOP_STUCK_PREFIX)),
            None,
        )
        self._pending_intent = self.curiosity.decide(
            self.drives,
            seconds_since_speech=seconds,
            thought=thought,
            novel_subject=self._novel_subject(),
            checkin=checkin,
            break_due=self._break_due(),
            someone_present=present,
            desktop_stuck=desktop_stuck,
        )

    def _break_due(self) -> bool:
        if self._suggested_break_this_visit or self._visit_started_at is None:
            return False
        return self._clock() - self._visit_started_at >= self._break_after_s

    def _maybe_utter(self) -> None:
        if self._speaking or self._utterance_in_flight:
            return
        if self.flow.phase is ConversationPhase.GREETING:
            name = self._person_label
            instruction = named_greet_instruction(name) if name not in (None, UNKNOWN_LABEL) else GREET_INSTRUCTION
            self._awaiting_name = name in (None, UNKNOWN_LABEL)

            def after_greet() -> None:
                self.flow.mark_greeted()
                if name not in (None, UNKNOWN_LABEL):
                    self.curiosity.mark_seen(name)

            self._begin_utterance(instruction, after=after_greet)
            return
        if self.flow.phase is ConversationPhase.FAREWELL:
            self._begin_utterance(FAREWELL_INSTRUCTION, after=self._after_farewell)
            return
        intent = self._pending_intent
        if intent is None or self.flow.phase is not ConversationPhase.ENGAGED:
            return
        if intent.kind == "ask":
            self._speak_ask(intent)
        elif intent.kind == "joke":
            self._begin_utterance(
                (
                    "Make one short observational joke about what you currently see: "
                    f"{self.world_model.summary_text()}. Do not mention these instructions."
                ),
                after=self._mark_awaiting_reply,
            )
        elif intent.kind == "speak":
            self._begin_utterance(speak_thought_instruction(intent.payload), after=self._mark_awaiting_reply)
        elif intent.kind == "checkin":
            self._speak_checkin()
        elif intent.kind == "break":
            self._begin_utterance(BREAK_INSTRUCTION, after=self._after_break)

    def _speak_ask(self, intent: ActionIntent) -> None:
        subject = intent.payload.removeprefix("Ask about ").strip() or intent.payload
        if subject.startswith(_DESKTOP_STUCK_PREFIX):
            app = subject.removeprefix(_DESKTOP_STUCK_PREFIX) or "the screen"

            def after_stuck() -> None:
                self._awaiting_reply = True
                self.curiosity.mark_seen(subject)
                self.curiosity.mark_desktop_spoke()

            self._begin_utterance(stuck_screen_instruction(app), after=after_stuck)
            return
        if subject == _WORK_SUBJECT:
            instruction = (
                "Ask what they are working on right now, briefly, in character. Do not mention these instructions."
            )
            glance = None

            def after() -> None:
                self._asked_work_this_visit = True
                self._awaiting_activity = True
                self._awaiting_reply = True
                self.curiosity.mark_seen(_WORK_SUBJECT)

        else:
            instruction = (
                f"You noticed {subject}. Ask one short, natural question about it. Do not mention these instructions."
            )
            glance = self._glance_for_label(subject)

            def after() -> None:
                self._awaiting_reply = True
                self.curiosity.mark_seen(subject)

        self._begin_utterance(instruction, after=after, glance=glance)

    def _speak_checkin(self) -> None:
        candidate = self._pending_checkin
        if candidate is None:
            return

        def after() -> None:
            self._offered_checkin = True
            self._awaiting_reply = True
            self.curiosity.mark_seen(f"checkin:{candidate.fact_text}")
            self._pending_checkin = None

        self._begin_utterance(checkin_instruction(candidate), after=after)

    def _after_break(self) -> None:
        self._suggested_break_this_visit = True
        self._awaiting_reply = True

    def _after_farewell(self) -> None:
        self._schedule_digest(self._person_label, self.world_model.summary_text())
        self.flow.reset()

    def _glance_for_label(self, label: str) -> tuple[float, float] | None:
        for observation in self.world_model.active():
            if observation.label == label and observation.center is not None:
                return self.gaze.angles_for(observation.center)
        return None

    def _mark_awaiting_reply(self) -> None:
        self._awaiting_reply = True

    def _maybe_timeout_reply(self) -> None:
        if not self._awaiting_reply:
            return
        if self._clock() - self._last_speech_at < self._reply_timeout_s:
            return
        self.drives.apply(self.curiosity.outcome_stimulus(answered=False))
        self.drives.stimulate("ignored")
        self._awaiting_reply = False
        logger.info("Buddy prompt ignored after %.0fs of silence", self._reply_timeout_s)

    def _maybe_refresh_checkin(self) -> None:
        if self._checkin_loaded or self._offered_checkin:
            return
        name = self._person_label
        if name in (None, UNKNOWN_LABEL) or self.memory is None:
            return
        if self.flow.phase is not ConversationPhase.ENGAGED:
            return
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        self._checkin_loaded = True
        asyncio.run_coroutine_threadsafe(self._load_checkin(name), loop)

    async def _load_checkin(self, name: str) -> None:
        store = self.memory
        if store is None:
            return
        try:
            candidates = await store.suggest_callbacks(name.lower(), display_name=name, limit=1)
        except Exception as exc:
            logger.warning("Callback recall failed: %s", exc)
            return
        if candidates:
            self._pending_checkin = candidates[0]

    def _schedule_digest(self, person: str | None, summary: str) -> None:
        if self.memory is None or person in (None, UNKNOWN_LABEL):
            return
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        text = f"Visit with {person}: {summary}"
        asyncio.run_coroutine_threadsafe(
            self.memory.digest_session(text, person_ids=(person.lower(),)),
            loop,
        )

    def _begin_utterance(
        self,
        instruction: str,
        after: Callable[[], None],
        glance: tuple[float, float] | None = None,
    ) -> None:
        with self._utterance_lock:
            if self._utterance_in_flight:
                return
            self._utterance_in_flight = True
        if glance is not None:
            self.gaze.glance_at(glance[0], glance[1], dwell_seconds=0.5)
            wait = 0.5
        else:
            wait = self.gaze.prepare_speech()
        thread = threading.Thread(
            target=self._deliver_utterance,
            args=(instruction, wait, after),
            name="reachy-buddy-say",
            daemon=True,
        )
        thread.start()

    def _deliver_utterance(self, instruction: str, wait: float, after: Callable[[], None]) -> None:
        try:
            if wait > 0:
                time.sleep(wait)
            loop = self._loop
            if loop is None or not loop.is_running():
                logger.debug("Skipping buddy utterance; realtime loop not ready")
                return
            future = asyncio.run_coroutine_threadsafe(self.handler.say(instruction), loop)
            future.result(timeout=15.0)
            after()
            self.curiosity.mark_spoke()
            self.drives.stimulate("thought_spoken")
            self._last_speech_at = self._clock()
        except Exception as exc:
            logger.warning("Buddy utterance failed: %s", exc)
        finally:
            with self._utterance_lock:
                self._utterance_in_flight = False

    def _on_activity(self, reason: str) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        if reason == "response_created":
            self._speaking = True
            self.planner.set_engaged(True)
        elif reason in {"assistant_speech_done", "assistant_transcript_done"}:
            self._speaking = False
            self._last_speech_at = self._clock()

    def _on_transcript(self, role: str, text: str, final: bool) -> None:
        if not final or not text.strip():
            return
        self._queue_memory(f"{role}: {text.strip()}", origin="transcript")
        if role != "user":
            return
        self.drives.stimulate("conversation")
        self._last_speech_at = self._clock()
        self._last_user_speech_at = self._last_speech_at
        if self._awaiting_reply:
            self.drives.apply(self.curiosity.outcome_stimulus(answered=True))
            self._awaiting_reply = False
        self._maybe_capture_name(text)
        self._maybe_capture_activity(text)

    def _maybe_retry_enroll(self, present: bool) -> None:
        name = self._pending_enroll_name
        if name is None or not present or self._speaking:
            return
        now = self._clock()
        if now < self._next_enroll_retry_at:
            return
        self._next_enroll_retry_at = now + 2.0
        logger.info("Retrying face enroll for %s", name)
        self.enroll_person(name)

    def _maybe_capture_name(self, text: str) -> None:
        name = extract_name(text, allow_bare=self._awaiting_name)
        if name is not None:
            logger.info("Parsed spoken name %s from %r; attempting face enroll", name, text)
            self._remember_and_enroll(name)
            return
        if not wants_face_enroll(text):
            if self._awaiting_name:
                logger.info("Heard a reply while waiting for a name, but did not parse one from %r", text)
            return
        pending = self._pending_enroll_name
        if pending is None and self._person_label not in (None, UNKNOWN_LABEL):
            pending = self._person_label
        if pending is None:
            logger.info("Heard a face-enroll request without a name yet: %r", text)
            return
        logger.info("Retrying face enroll for %s after %r", pending, text)
        self._remember_and_enroll(pending)

    def _remember_and_enroll(self, name: str) -> None:
        if self.enroll_person(name):
            self._awaiting_name = False
            return
        logger.warning("Face enroll pending for %s; will retry while they stay in view", name)
        self._pending_enroll_name = name
        self._awaiting_name = False
        self._next_enroll_retry_at = self._clock() + 0.5
        if self._person_label != name:
            self._apply_identity(name, enrolled=False)

    def _maybe_capture_activity(self, text: str) -> None:
        activity = extract_activity(text)
        if activity is None and self._awaiting_activity:
            activity = text.strip()
        if not activity:
            return
        person_id = (self._person_label or "person").lower()
        item = MemoryItem(
            content=activity,
            tags=(TAG_ACTIVITY, person_tag(person_id)),
            timestamp=time.time(),
        )
        with self._pending_lock:
            self._pending_memories.append(item)
        self._awaiting_activity = False
        logger.info("Remembered activity for %s: %s", person_id, activity)

    def _queue_memory(self, text: str, origin: str, extra_tags: tuple[str, ...] = ()) -> None:
        item = MemoryItem(content=text, tags=(TAG_OBSERVATION, origin, *extra_tags), timestamp=time.time())
        with self._pending_lock:
            self._pending_memories.append(item)

    def _drain_memory(self) -> None:
        store = self.memory
        if store is None:
            return
        with self._pending_lock:
            items, self._pending_memories = self._pending_memories, []
        for item in items:
            store.queue(item)
        now = self._clock()
        due = not self._memory_started or now - self._last_flush_at >= _MEMORY_FLUSH_S
        if not due:
            return
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        self._last_flush_at = now
        asyncio.run_coroutine_threadsafe(self._flush_memory(), loop)

    async def _flush_memory(self) -> None:
        store = self.memory
        if store is None:
            return
        if not self._memory_started:
            await store.start()
            self._memory_started = True
        await store.flush()

    async def _shutdown_memory(self) -> None:
        store = self.memory
        if store is None:
            return
        with self._pending_lock:
            items, self._pending_memories = self._pending_memories, []
        for item in items:
            store.queue(item)
        await store.close()


def _try_presence_loop(robot: ReachyMini) -> PresenceLoop | None:
    try:
        from reachy_buddy.vision.frames import grab_bgr_frame
        from reachy_buddy.vision.face_tracking import FaceTracker, ensure_face_landmarker_model

        tracker = PresenceTracker(FaceTracker(ensure_face_landmarker_model()))
        return PresenceLoop(tracker, frame_source=lambda: grab_bgr_frame(robot))
    except Exception as exc:
        logger.warning("Buddy face tracking unavailable: %s", exc)
        return None


def _try_object_detector(runtime: BuddyRuntimeConfig) -> ObjectDetector | None:
    onnx = runtime.object_onnx
    labels = runtime.object_labels
    if onnx is None or labels is None or not onnx.is_file() or not labels.is_file():
        return ObjectDetector()
    try:
        return ObjectDetector(onnx, labels)
    except Exception as exc:
        logger.warning("Object detector failed to load: %s", exc)
        return ObjectDetector()
