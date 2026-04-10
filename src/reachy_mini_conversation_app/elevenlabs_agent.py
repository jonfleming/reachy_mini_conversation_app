"""ElevenLabs conversational AI integration for Reachy Mini.

Provides a custom AudioInterface and stream manager for ElevenLabs agents,
using the robot's built-in microphone and speaker.
"""

import re
import json
import time
import logging
import threading
from typing import Any, Callable, Optional
from dataclasses import dataclass

import numpy as np
from fastrtc import audio_to_int16, audio_to_float32
from scipy.signal import resample

from reachy_mini import ReachyMini
from reachy_mini_conversation_app.tools.core_tools import ALL_TOOLS, ToolDependencies, dispatch_tool_call
from reachy_mini_conversation_app.audio.head_wobbler import HeadWobbler


try:
    from elevenlabs.client import ElevenLabs
    from elevenlabs.conversational_ai.conversation import ClientTools, Conversation, AudioInterface

    ELEVENLABS_AVAILABLE = True
except ImportError:
    ELEVENLABS_AVAILABLE = False
    AudioInterface = object  # type: ignore[misc,assignment]

# Tools that require the BackgroundToolManager (used only with OpenAI).
_UNSUPPORTED_TOOLS = {"task_status", "task_cancel"}

# Regex to extract [tags] from agent response text.
_TAG_RE = re.compile(r"\[([^\]]+)\]")

# Tags that control voice delivery/pacing — should not trigger body emotions.
_DELIVERY_TAGS = {
    "pause", "slow", "fast", "rushed", "whispers", "whispering", "quietly", "loudly",
    "stammers", "hesitates", "pauses", "emphasized", "understated", "drawn out",
    "rapid-fire", "timidly", "deliberate", "matter-of-fact", "conversational tone",
    "shouts", "shouting", "laughs softly", "laughs harder", "laughs hard",
    "continues after a beat", "continues softly", "interrupting", "overlapping",
}

# Mapping from ElevenLabs tags to robot emotion names.
# Direct matches (tag == robot emotion name) are handled automatically.
_TAG_TO_EMOTION: dict[str, str] = {
    "happy": "proud2",
    "happily": "proud2",
    "excited": "enthusiastic1",
    "playful": "cheerful1",
    "playfully": "cheerful1",
    "lighthearted": "cheerful1",
    "cheerfully": "cheerful1",
    "sad": "sad1",
    "sorrowful": "sad2",
    "crying": "sad2",
    "downcast": "downcast1",
    "angry": "irritated1",
    "annoyed": "irritated1",
    "frustrated": "frustrated1",
    "furious": "furious1",
    "rage": "rage1",
    "nervous": "anxiety1",
    "calm": "serenity1",
    "curious": "curious1",
    "surprised": "surprised1",
    "awe": "amazed1",
    "amazed": "amazed1",
    "laughs": "laughing1",
    "laughing": "laughing1",
    "light chuckle": "laughing2",
    "giggle": "laughing2",
    "giggles": "laughing2",
    "sighs": "resigned1",
    "sigh": "resigned1",
    "sighing": "resigned1",
    "sigh of relief": "relief1",
    "tired": "tired1",
    "yawning": "tired1",
    "exhausted": "exhausted1",
    "thoughtful": "thoughtful1",
    "reflective": "thoughtful1",
    "wistful": "thoughtful1",
    "casual": "indifferent1",
    "deadpan": "indifferent1",
    "flatly": "indifferent1",
    "regretful": "sad1",
    "resigned tone": "resigned1",
    "sarcastic tone": "contempt1",
    "hesitant": "uncomfortable1",
    "flustered": "oops1",
    "gasps": "surprised1",
    "gasp": "surprised1",
    "welcoming": "welcoming1",
    "grateful": "grateful1",
    "proud": "proud1",
    "confused": "confused1",
    "lost": "lost1",
    "scared": "scared1",
    "fear": "fear1",
    "dramatic tone": "enthusiastic1",
    "serious tone": "attentive1",
}


def _trigger_emotion_from_tags(text: str, deps: ToolDependencies) -> None:
    """Parse [tags] in agent text and trigger the first matching robot emotion."""
    try:
        from reachy_mini_conversation_app.tools.play_emotion import RECORDED_MOVES, EMOTION_AVAILABLE
        from reachy_mini_conversation_app.dance_emotion_moves import EmotionQueueMove

        if not EMOTION_AVAILABLE or RECORDED_MOVES is None:
            return

        robot_emotions: set[str] = set(RECORDED_MOVES.list_moves())

        for match in _TAG_RE.finditer(text):
            tag = match.group(1).lower().strip()

            if tag in _DELIVERY_TAGS:
                continue

            # Direct match with a robot emotion name
            if tag in robot_emotions:
                emotion = tag
            # Known alias
            elif tag in _TAG_TO_EMOTION and _TAG_TO_EMOTION[tag] in robot_emotions:
                emotion = _TAG_TO_EMOTION[tag]
            else:
                continue

            logger.debug("Tag [%s] → emotion %s", tag, emotion)
            deps.movement_manager.queue_move(EmotionQueueMove(emotion, RECORDED_MOVES))
            return  # first match only

    except Exception as e:
        logger.debug("Emotion tag parsing failed: %s", e)


logger = logging.getLogger(__name__)

# ElevenLabs uses 16kHz PCM16 mono for both input and output.
ELEVENLABS_SAMPLE_RATE = 16000
INPUT_FRAMES_PER_BUFFER = 4000  # 250ms @ 16kHz


@dataclass
class ElevenLabsConfig:
    """Configuration for ElevenLabs agent."""

    agent_id: str
    api_key: Optional[str] = None
    requires_auth: bool = False


class ReachyAudioInterface(AudioInterface):  # type: ignore[misc]
    """Audio interface bridging ElevenLabs to Reachy Mini's speaker and mic."""

    def __init__(self, robot: ReachyMini, head_wobbler: Optional[HeadWobbler] = None) -> None:
        """Initialize with robot hardware."""
        self.robot = robot
        self.head_wobbler = head_wobbler
        self.input_sample_rate: int = robot.media.get_input_audio_samplerate()
        self.output_sample_rate: int = robot.media.get_output_audio_samplerate()
        self.should_stop = threading.Event()
        self.input_thread: Optional[threading.Thread] = None
        self.input_callback: Optional[Callable[[bytes], None]] = None

        # Buffer for accumulating mic frames to the chunk size ElevenLabs expects
        self._audio_buffer: list[bytes] = []
        self._buffer_samples = 0

        # Track last audio output time to detect new speech bursts
        self._last_audio_output_time: Optional[float] = None

        logger.info(
            "ReachyAudioInterface: input=%dHz output=%dHz, elevenlabs=%dHz",
            self.input_sample_rate,
            self.output_sample_rate,
            ELEVENLABS_SAMPLE_RATE,
        )

    # -- AudioInterface protocol --------------------------------------------------

    def start(self, input_callback: Callable[[bytes], None]) -> None:
        """Start audio capture and playback."""
        self.input_callback = input_callback
        self.should_stop.clear()

        self.robot.media.start_recording()
        self.robot.media.start_playing()
        time.sleep(1.0)  # let pipelines initialize

        self.input_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.input_thread.start()
        logger.info("Audio streams started")

    def stop(self) -> None:
        """Stop audio streams."""
        logger.info("Stopping audio streams")
        self.should_stop.set()
        # Never join the current thread — stop() may be called from within _capture_loop
        # (via ElevenLabs' error handler calling end_session() → audio_interface.stop())
        if (
            self.input_thread
            and self.input_thread.is_alive()
            and self.input_thread is not threading.current_thread()
        ):
            self.input_thread.join(timeout=2.0)
        self.robot.media.stop_recording()
        self.robot.media.stop_playing()

    def output(self, audio: bytes) -> None:
        """Play audio from ElevenLabs through the robot speaker."""
        if self.should_stop.is_set():
            return
        try:
            audio_array = np.frombuffer(audio, dtype=np.int16)

            if self.head_wobbler is not None:
                now = time.monotonic()
                # Reset wobbler timing only on clear silence between separate utterances.
                # ElevenLabs can have sub-second gaps within a single sentence, so use a
                # conservative threshold to avoid draining queued wobble data mid-speech.
                if self._last_audio_output_time is None or (now - self._last_audio_output_time) > 3.0:
                    self.head_wobbler.reset()
                self._last_audio_output_time = now
                self.head_wobbler.feed_pcm(audio_array, ELEVENLABS_SAMPLE_RATE)

            audio_float = audio_to_float32(audio_array)

            if ELEVENLABS_SAMPLE_RATE != self.output_sample_rate:
                n_samples = int(len(audio_float) * self.output_sample_rate / ELEVENLABS_SAMPLE_RATE)
                audio_float = resample(audio_float, n_samples).astype(np.float32)

            self.robot.media.push_audio_sample(audio_float)
        except Exception as e:
            if not self.should_stop.is_set():
                logger.error("Error playing audio: %s", e)

    def interrupt(self) -> None:
        """Interrupt current playback (best-effort)."""
        logger.debug("Audio interrupt requested")

    # -- internal -----------------------------------------------------------------

    def _capture_loop(self) -> None:
        """Continuously read mic frames, buffer, and forward to ElevenLabs."""
        chunks_sent = 0
        while not self.should_stop.is_set():
            try:
                frame = self.robot.media.get_audio_sample()
                if frame is None:
                    time.sleep(0.01)
                    continue

                # Stereo → mono, convert to int16 bytes
                mono = frame.T[0]
                pcm_bytes = audio_to_int16(mono).tobytes()

                self._audio_buffer.append(pcm_bytes)
                self._buffer_samples += len(mono)

                if self._buffer_samples >= INPUT_FRAMES_PER_BUFFER:
                    combined = b"".join(self._audio_buffer)
                    self._audio_buffer = []
                    self._buffer_samples = 0

                    if self.input_callback:
                        self.input_callback(combined)
                        chunks_sent += 1
                        if chunks_sent % 100 == 0:
                            logger.debug("Sent %d audio chunks to ElevenLabs", chunks_sent)

            except Exception as e:
                logger.error("Error in capture loop: %s", e, exc_info=True)
                break

        logger.info("Capture loop ended (%d chunks sent)", chunks_sent)


def _build_client_tools(deps: ToolDependencies) -> "ClientTools":
    """Register all supported robot tools with ElevenLabs ClientTools."""
    client_tools = ClientTools()
    registered = []

    for tool_name, tool in ALL_TOOLS.items():
        if tool_name in _UNSUPPORTED_TOOLS:
            continue

        # Capture tool_name in the closure
        def make_handler(name: str) -> Callable[[dict[str, Any]], Any]:
            async def handler(params: dict[str, Any]) -> str:
                try:
                    # Strip tool_call_id injected by the SDK — not a tool argument
                    tool_params = {k: v for k, v in params.items() if k != "tool_call_id"}
                    result = await dispatch_tool_call(name, json.dumps(tool_params), deps)
                    logger.info("Tool %s result: %s", name, result)
                    # ElevenLabs expects result to be a string, not a dict
                    return json.dumps(result)
                except Exception as e:
                    logger.error("Tool %s raised unexpectedly: %s", name, e)
                    return json.dumps({"error": str(e)})

            return handler

        client_tools.register(tool_name, make_handler(tool_name), is_async=True)
        registered.append(tool_name)

    logger.info("Registered %d client tools: %s", len(registered), registered)
    return client_tools


class ElevenLabsStream:
    """Stream manager for ElevenLabs agent, drop-in replacement for LocalStream/Blocks."""

    def __init__(
        self,
        el_config: ElevenLabsConfig,
        robot: ReachyMini,
        deps: ToolDependencies,
    ) -> None:
        """Initialize the stream."""
        if not ELEVENLABS_AVAILABLE:
            raise ImportError("ElevenLabs SDK not installed. Run: uv add elevenlabs")

        self.config = el_config
        self.robot = robot
        self.deps = deps

        self.client = ElevenLabs(api_key=el_config.api_key) if el_config.api_key else ElevenLabs()
        self.audio_interface = ReachyAudioInterface(robot, head_wobbler=deps.head_wobbler)
        self.client_tools = _build_client_tools(deps)
        self.conversation: Optional[Conversation] = None
        self._conversation_id: Optional[str] = None

    # -- callbacks ----------------------------------------------------------------

    def _on_agent_response(self, response: str) -> None:
        logger.info("Agent: %s", response)

    def _on_agent_response_correction(self, original: str, corrected: str) -> None:
        logger.info("Agent correction: %s -> %s", original, corrected)

    def _on_user_transcript(self, transcript: str) -> None:
        logger.info("User: %s", transcript)

    def _on_latency(self, latency: int) -> None:
        logger.debug("Latency: %dms", latency)

    # -- lifecycle (matches LocalStream / gr.Blocks interface) --------------------

    def launch(self) -> None:
        """Start the conversation and block until it ends."""
        logger.info("Starting ElevenLabs conversation (agent=%s)", self.config.agent_id)

        self.conversation = Conversation(
            self.client,
            self.config.agent_id,
            requires_auth=self.config.requires_auth,
            audio_interface=self.audio_interface,
            client_tools=self.client_tools,
            callback_agent_response=self._on_agent_response,
            callback_agent_response_correction=self._on_agent_response_correction,
            callback_user_transcript=self._on_user_transcript,
            callback_latency_measurement=self._on_latency,
        )

        self.conversation.start_session()
        self._conversation_id = self.conversation.wait_for_session_end()
        logger.info("Conversation ended (id=%s)", self._conversation_id)

    def close(self) -> None:
        """End the conversation and release resources."""
        logger.info("Closing ElevenLabs stream")
        if self.conversation:
            try:
                self.conversation.end_session()
            except Exception as e:
                logger.warning("Error ending session: %s", e)
        self.audio_interface.stop()
