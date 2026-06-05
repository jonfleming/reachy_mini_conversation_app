"""Optional latency probes for the full conversation app."""

from __future__ import annotations
import os

import numpy as np
from numpy.typing import NDArray


POST_ASSISTANT_BEEP_ROLE = "latency_probe"
POST_ASSISTANT_BEEP_CONTENT = "post_assistant_beep"
POST_ASSISTANT_BEEP_ENV = "REACHY_MINI_LATENCY_PROBE_BEEP"
RECORDING_STATS_ENV = "REACHY_MINI_LATENCY_PROBE_RECORDING"


def _env_flag(name: str) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def post_assistant_beep_enabled() -> bool:
    """Return whether to play a diagnostic beep after assistant audio is queued."""
    return _env_flag(POST_ASSISTANT_BEEP_ENV)


def recording_stats_enabled() -> bool:
    """Return whether to log record-loop timing diagnostics."""
    return _env_flag(RECORDING_STATS_ENV)


def make_probe_beep(sample_rate: int, *, channels: int = 1) -> NDArray[np.float32]:
    """Build a short two-beep pulse for audible latency checks."""
    beep_s = 0.08
    gap_s = 0.12
    amplitude = 0.35
    frequency_hz = 1000.0

    t = np.arange(int(sample_rate * beep_s), dtype=np.float32) / sample_rate
    beep = amplitude * np.sin(2 * np.pi * frequency_hz * t)
    gap = np.zeros(int(sample_rate * gap_s), dtype=np.float32)
    mono = np.concatenate([beep, gap, beep]).astype(np.float32)
    if channels <= 1:
        return mono
    return np.repeat(mono[:, None], channels, axis=1)
