"""Reaction callback: play a 'yummy' sound when a food entity is detected via NER.

Entity (GLiNER) triggers only work in the gliner install config — `cascade_gliner`
with MLX ASR and WITHOUT the local vision extra (transformers 5.1.x). With the
local VLM (transformers 5.3.0) the entity analyzer is disabled and this never
fires. See MIGRATION_GAPS.md.
"""

import os
import wave
import asyncio
import logging

import numpy as np
import sounddevice as sd

from reachy_mini_conversation_app.tools.core_tools import ToolDependencies
from reachy_mini_conversation_app.cascade.transcript_analysis.base import TriggerMatch


logger = logging.getLogger(__name__)


async def react_to_food(deps: ToolDependencies, match: TriggerMatch, **kwargs: object) -> None:
    """Play a yummy sound when a food entity is detected."""
    entity = match.entities[0]
    logger.info(f"FOOD detected: '{entity.text}' (confidence: {entity.confidence:.2f}) — playing reaction")

    audio_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yummy.wav")
    try:
        with wave.open(audio_file, "rb") as wf:
            sample_rate = wf.getframerate()
            audio_data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    except FileNotFoundError:
        logger.error(f"Audio file not found: {audio_file}")
        return

    # Play through the robot speaker when the default output is a robot device,
    # otherwise fall back to sounddevice (simulation / laptop).
    status = deps.reachy_mini.client.get_status()
    robot_available = hasattr(deps.reachy_mini, "media") and not getattr(status, "simulation_enabled", False)

    use_robot_media = False
    if robot_available:
        try:
            device_name = sd.query_devices(kind="output")["name"].lower()
            use_robot_media = any(k in device_name for k in ("respeaker", "xvf3800", "reachy"))
        except Exception as e:
            logger.warning(f"Failed to detect default audio device: {e}")

    if use_robot_media:
        logger.info("Playing through robot.media")
        audio_float = audio_data.astype(np.float32) / 32768.0
        device_sample_rate = deps.reachy_mini.media.get_audio_samplerate()
        if device_sample_rate != sample_rate:
            import librosa

            audio_float = librosa.resample(audio_float, orig_sr=sample_rate, target_sr=device_sample_rate)
        deps.reachy_mini.media.push_audio_sample(audio_float)
        await asyncio.sleep(len(audio_data) / sample_rate)
    else:
        logger.info("Playing through sounddevice")
        sd.play(audio_data, samplerate=sample_rate)
        sd.wait()

    logger.info("Audio playback complete")
