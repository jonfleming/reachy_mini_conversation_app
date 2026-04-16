"""ElevenLabs conversational AI integration for Reachy Mini.

Provides a custom AudioInterface and stream manager for ElevenLabs agents,
using the robot's built-in microphone and speaker.
"""

import re
import json
import time
import queue
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
    from elevenlabs.conversational_ai.conversation import (
        ClientTools,
        Conversation,
        AudioInterface,
        ConversationInitiationData,
    )

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
    "pause",
    "slow",
    "fast",
    "rushed",
    "whispers",
    "whispering",
    "quietly",
    "loudly",
    "stammers",
    "hesitates",
    "pauses",
    "emphasized",
    "understated",
    "drawn out",
    "rapid-fire",
    "timidly",
    "deliberate",
    "matter-of-fact",
    "conversational tone",
    "shouts",
    "shouting",
    "laughs softly",
    "laughs harder",
    "laughs hard",
    "continues after a beat",
    "continues softly",
    "interrupting",
    "overlapping",
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
    no_emotion_tags: bool = False


class ReachyAudioInterface(AudioInterface):  # type: ignore[misc]
    """Audio interface bridging ElevenLabs to Reachy Mini's speaker and mic."""

    def __init__(
        self,
        robot: ReachyMini,
        head_wobbler: Optional[HeadWobbler] = None,
        deps: Optional["ToolDependencies"] = None,
    ) -> None:
        """Initialize with robot hardware."""
        self.robot = robot
        self.head_wobbler = head_wobbler
        self.deps = deps
        self.input_sample_rate: int = robot.media.get_input_audio_samplerate()
        self.output_sample_rate: int = robot.media.get_output_audio_samplerate()
        self.should_stop = threading.Event()
        self.input_thread: Optional[threading.Thread] = None
        self.output_thread: Optional[threading.Thread] = None
        self.input_callback: Optional[Callable[[bytes], None]] = None
        self.output_queue: queue.Queue[bytes] = queue.Queue()

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
        self.output_thread = threading.Thread(target=self._output_loop, daemon=True)
        self.input_thread.start()
        self.output_thread.start()
        logger.info("Audio streams started")

    def stop(self) -> None:
        """Stop audio streams."""
        logger.info("Stopping audio streams")
        self.should_stop.set()
        # Never join the current thread — stop() may be called from within _capture_loop
        # (via ElevenLabs' error handler calling end_session() → audio_interface.stop())
        if self.input_thread and self.input_thread.is_alive() and self.input_thread is not threading.current_thread():
            self.input_thread.join(timeout=2.0)
        if self.output_thread and self.output_thread.is_alive():
            self.output_thread.join(timeout=2.0)
        self.robot.media.stop_recording()
        self.robot.media.stop_playing()

    def output(self, audio: bytes) -> None:
        """Queue audio from ElevenLabs for playback through the robot speaker."""
        if self.should_stop.is_set():
            return
        if self.deps is not None and self.deps.is_sleeping:
            return
        self.output_queue.put(audio)

    def interrupt(self) -> None:
        """Interrupt current playback by clearing queued audio and flushing the robot pipeline."""
        dropped = 0
        try:
            while True:
                self.output_queue.get(block=False)
                dropped += 1
        except queue.Empty:
            pass
        self._flush_robot_audio()
        logger.info("Audio interrupt: dropped %d queued chunks, flushed robot pipeline", dropped)

    # -- internal -----------------------------------------------------------------

    def _flush_robot_audio(self) -> None:
        """Flush the robot's audio pipeline to stop playback immediately."""
        audio = getattr(self.robot.media, "audio", None)
        if audio is None:
            return
        if hasattr(audio, "clear_player") and callable(audio.clear_player):
            audio.clear_player()
        elif hasattr(audio, "clear_output_buffer") and callable(audio.clear_output_buffer):
            audio.clear_output_buffer()

    def _output_loop(self) -> None:
        """Drain the output queue and push audio to the robot speaker."""
        while not self.should_stop.is_set():
            try:
                audio = self.output_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                audio_array = np.frombuffer(audio, dtype=np.int16)

                if self.head_wobbler is not None:
                    now = time.monotonic()
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


class SystemAudioInterface(AudioInterface):  # type: ignore[misc]
    """Audio interface using macOS system default mic/speakers via sounddevice."""

    INPUT_FRAMES_PER_BUFFER = 4000  # 250ms @ 16kHz
    OUTPUT_FRAMES_PER_BUFFER = 1000  # 62.5ms @ 16kHz

    def __init__(
        self,
        head_wobbler: Optional[HeadWobbler] = None,
        deps: Optional["ToolDependencies"] = None,
    ) -> None:
        """Initialize with optional head wobbler for speech-sync animation."""
        try:
            import sounddevice as sd
        except ImportError:
            raise ImportError("sounddevice is required for --system-audio. Run: uv add sounddevice")
        self.sd = sd
        self.head_wobbler = head_wobbler
        self.deps = deps
        self._last_audio_output_time: Optional[float] = None

        logger.info(
            "SystemAudioInterface: using system default input=%s output=%s",
            sd.query_devices(sd.default.device[0])["name"],
            sd.query_devices(sd.default.device[1])["name"],
        )

    def start(self, input_callback: Callable[[bytes], None]) -> None:
        """Start audio capture and playback using system devices."""
        self.input_callback = input_callback
        self.output_queue: queue.Queue[bytes] = queue.Queue()
        self.should_stop = threading.Event()

        self.in_stream = self.sd.RawInputStream(
            samplerate=ELEVENLABS_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=self.INPUT_FRAMES_PER_BUFFER,
            callback=self._in_callback,
        )
        self.out_stream = self.sd.RawOutputStream(
            samplerate=ELEVENLABS_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=self.OUTPUT_FRAMES_PER_BUFFER,
        )

        self.output_thread = threading.Thread(target=self._output_thread, daemon=True)
        self.in_stream.start()
        self.out_stream.start()
        self.output_thread.start()
        logger.info("System audio streams started")

    def stop(self) -> None:
        """Stop audio streams."""
        logger.info("Stopping system audio streams")
        self.should_stop.set()
        self.output_thread.join(timeout=2.0)
        self.in_stream.stop()
        self.in_stream.close()
        self.out_stream.stop()
        self.out_stream.close()

    def output(self, audio: bytes) -> None:
        """Play audio through system speakers and feed head wobbler."""
        if self.should_stop.is_set():
            return
        if self.deps is not None and self.deps.is_sleeping:
            return

        if self.head_wobbler is not None:
            audio_array = np.frombuffer(audio, dtype=np.int16)
            now = time.monotonic()
            if self._last_audio_output_time is None or (now - self._last_audio_output_time) > 3.0:
                self.head_wobbler.reset()
            self._last_audio_output_time = now
            self.head_wobbler.feed_pcm(audio_array, ELEVENLABS_SAMPLE_RATE)

        self.output_queue.put(audio)

    def interrupt(self) -> None:
        """Clear output queue to stop current playback."""
        dropped = 0
        try:
            while True:
                self.output_queue.get(block=False)
                dropped += 1
        except queue.Empty:
            pass
        logger.info("Audio interrupt: dropped %d queued chunks", dropped)

    def _output_thread(self) -> None:
        while not self.should_stop.is_set():
            try:
                audio = self.output_queue.get(timeout=0.25)
                self.out_stream.write(audio)
            except queue.Empty:
                pass

    def _in_callback(
        self,
        indata: bytes,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        if status:
            logger.debug("Input stream status: %s", status)
        if self.input_callback:
            self.input_callback(bytes(indata))


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
                    # ElevenLabs can only consume text results; tell tools that
                    # would otherwise return binary data to produce a description.
                    if name == "camera":
                        tool_params["_text_only"] = True
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
        *,
        system_audio: bool = False,
    ) -> None:
        """Initialize the stream."""
        if not ELEVENLABS_AVAILABLE:
            raise ImportError("ElevenLabs SDK not installed. Run: uv add elevenlabs")

        self.config = el_config
        self.robot = robot
        self.deps = deps

        self.client = ElevenLabs(api_key=el_config.api_key) if el_config.api_key else ElevenLabs()
        if system_audio:
            self.audio_interface: AudioInterface = SystemAudioInterface(head_wobbler=deps.head_wobbler, deps=deps)  # type: ignore[assignment]
        else:
            self.audio_interface = ReachyAudioInterface(robot, head_wobbler=deps.head_wobbler, deps=deps)  # type: ignore[assignment]
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

        conversation_config_override: dict[str, Any] = {
            "turn": {
                "turn_eagerness": "eager",
            },
        }
        if self.config.no_emotion_tags:
            conversation_config_override["agent"] = {
                "prompt": {
                    "prompt": (
                        "IMPORTANT: Never include bracketed emotion or delivery tags "
                        "like [happy], [excited], [pause] etc. in your text responses. "
                        "They will be read aloud by the text-to-speech engine. "
                        "Use the play_emotion tool to express emotions instead."
                    ),
                },
            }

        config = ConversationInitiationData(
            conversation_config_override=conversation_config_override,
        )

        self.conversation = Conversation(
            self.client,
            self.config.agent_id,
            requires_auth=self.config.requires_auth,
            config=config,
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
