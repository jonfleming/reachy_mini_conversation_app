"""SpeechOutput protocol and a queue-backed implementation for the cascade backend."""

from __future__ import annotations
import re
import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

import numpy as np
from fastrtc import AdditionalOutputs
from numpy.typing import NDArray


if TYPE_CHECKING:
    from reachy_mini_conversation_app.cascade.handler import CascadeHandler


logger = logging.getLogger(__name__)


class SpeechOutput(Protocol):
    """Protocol for TTS playback backends."""

    async def speak(self, text: str) -> None:
        """Synthesize and play speech."""
        ...


class QueueSpeechOutput:
    """Synthesize TTS and push audio frames onto the handler's output queue.

    The fastrtc stream drains the queue via emit() and plays audio in the browser.
    In Gradio mode the samples are additionally tapped to the daemon so the head
    wobbler moves. Each spoken segment is also surfaced as an assistant chat message.
    """

    def __init__(self, handler: "CascadeHandler") -> None:
        """Bind to the owning handler (whose output_queue/tts are used)."""
        self.handler = handler

    async def speak(self, text: str) -> None:
        """Stream TTS audio for `text` onto the handler's output queue.

        The text is split into sentence-like chunks. The first sentence streams
        live for fast time-to-first-audio; each subsequent sentence is synthesized
        in the background while the previous one's audio is queued, so generation
        overlaps playback (a win for network TTS) without hammering a local model —
        at most two sentences are in flight. Chunks are always queued in order.
        """
        from reachy_mini_conversation_app.cascade.timing import tracker

        if not text.strip():
            return

        handler = self.handler
        await handler.output_queue.put(AdditionalOutputs({"role": "assistant", "content": text}))

        sample_rate = handler.tts.sample_rate
        sentences = split_into_sentences(text)
        first_chunk = True

        async def push(frame: NDArray[np.int16]) -> None:
            """Queue one int16 frame for playback (+ daemon wobbler in Gradio mode)."""
            nonlocal first_chunk
            if first_chunk:
                tracker.mark("audio_playback_started")
                first_chunk = False
            # Browser plays the audio via emit(); in Gradio mode the daemon never sees
            # it, so tap the same samples to drive the head wobbler (robot speaker muted).
            if handler.gradio_mode:
                handler._tap_audio_for_daemon_wobbler(frame)
            await handler.output_queue.put((sample_rate, frame))

        async def synthesize_frames(sentence: str) -> list[NDArray[np.int16]]:
            """Synthesize one sentence fully into int16 frames (for look-ahead)."""
            frames: list[NDArray[np.int16]] = []
            async for chunk in handler.tts.synthesize(sentence, voice=handler._voice):
                samples = np.frombuffer(chunk, dtype=np.int16)
                if samples.size:
                    frames.append(samples.reshape(1, -1))
            return frames

        # Prefetch sentence 1 so it generates while sentence 0 streams live.
        pending = asyncio.create_task(synthesize_frames(sentences[1])) if len(sentences) > 1 else None
        for i, sentence in enumerate(sentences):
            if i == 0:
                async for chunk in handler.tts.synthesize(sentence, voice=handler._voice):
                    samples = np.frombuffer(chunk, dtype=np.int16)
                    if samples.size:
                        await push(samples.reshape(1, -1))
            else:
                assert pending is not None
                frames = await pending
                # Kick off the next sentence before draining this one, to keep one ahead.
                pending = asyncio.create_task(synthesize_frames(sentences[i + 1])) if i + 1 < len(sentences) else None
                for frame in frames:
                    await push(frame)


def split_into_sentences(text: str, min_length: int = 8) -> list[str]:
    """Split text into sentence-like chunks for streaming TTS.

    Splits on: . ! ? , ; — (but keeps punctuation with the sentence). Fragments
    shorter than ``min_length`` are merged with neighbours so the TTS never gets
    tiny, choppy inputs.
    """
    pattern = r"([.!?,;—]\s+)"
    parts = re.split(pattern, text)

    raw_sentences: list[str] = []
    current = ""
    for part in parts:
        current += part
        if re.match(pattern, part):
            if current.strip():
                raw_sentences.append(current.strip())
            current = ""

    if current.strip():
        raw_sentences.append(current.strip())

    if not raw_sentences:
        return [text]

    merged_sentences: list[str] = []
    accumulator = ""

    for sentence in raw_sentences:
        if accumulator:
            accumulator += " " + sentence
        else:
            accumulator = sentence

        if len(accumulator) >= min_length:
            merged_sentences.append(accumulator)
            accumulator = ""

    if accumulator:
        if merged_sentences and len(merged_sentences[-1]) < min_length * 2:
            merged_sentences[-1] += " " + accumulator
        else:
            merged_sentences.append(accumulator)

    return merged_sentences if merged_sentences else [text]
