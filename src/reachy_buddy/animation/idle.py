"""Idle motion: per-emotion motion styles, continuous micro-motion, and idle gesture menus."""

import math
import random
from dataclasses import dataclass
from collections.abc import Mapping

from reachy_buddy.animation.pose import BodyPose
from reachy_buddy.core.emotional_state import Emotion


@dataclass(frozen=True)
class MotionStyle:
    """Per-emotion body language: base pose, breathing, antenna sway, idle cadence, gesture menu."""

    base_pose: BodyPose
    breath_amplitude_deg: float
    breath_frequency_hz: float
    sway_amplitude_rad: float
    sway_frequency_hz: float
    idle_interval_s: tuple[float, float]
    menu: tuple[tuple[str, float], ...]

    def lerp(self, other: "MotionStyle", t: float) -> "MotionStyle":
        """Blend continuous parameters toward another style; cadence and menu switch to other."""
        x = min(1.0, max(0.0, t))
        return MotionStyle(
            base_pose=self.base_pose.lerp(other.base_pose, x),
            breath_amplitude_deg=self.breath_amplitude_deg
            + (other.breath_amplitude_deg - self.breath_amplitude_deg) * x,
            breath_frequency_hz=self.breath_frequency_hz + (other.breath_frequency_hz - self.breath_frequency_hz) * x,
            sway_amplitude_rad=self.sway_amplitude_rad + (other.sway_amplitude_rad - self.sway_amplitude_rad) * x,
            sway_frequency_hz=self.sway_frequency_hz + (other.sway_frequency_hz - self.sway_frequency_hz) * x,
            idle_interval_s=other.idle_interval_s,
            menu=other.menu,
        )


# The default personality: how each emotion looks on the body when nothing is being said.
EMOTION_STYLES: dict[Emotion, MotionStyle] = {
    Emotion.CALM: MotionStyle(
        base_pose=BodyPose(),
        breath_amplitude_deg=0.8,
        breath_frequency_hz=0.10,
        sway_amplitude_rad=0.12,
        sway_frequency_hz=0.45,
        idle_interval_s=(25.0, 50.0),
        menu=(("scan", 0.5), ("glance_down", 0.3), ("perk_up", 0.2)),
    ),
    Emotion.CURIOUS: MotionStyle(
        base_pose=BodyPose(pitch=2.0, antenna_left=0.35, antenna_right=-0.35),
        breath_amplitude_deg=1.0,
        breath_frequency_hz=0.12,
        sway_amplitude_rad=0.18,
        sway_frequency_hz=0.6,
        idle_interval_s=(12.0, 25.0),
        menu=(("scan", 0.5), ("perk_up", 0.3), ("glance_down", 0.2)),
    ),
    Emotion.EXCITED: MotionStyle(
        base_pose=BodyPose(pitch=3.0, antenna_left=0.6, antenna_right=-0.6),
        breath_amplitude_deg=1.4,
        breath_frequency_hz=0.16,
        sway_amplitude_rad=0.22,
        sway_frequency_hz=0.9,
        idle_interval_s=(8.0, 18.0),
        menu=(("antenna_twitch", 0.6), ("perk_up", 0.4)),
    ),
    Emotion.SLEEPY: MotionStyle(
        base_pose=BodyPose(pitch=-8.0, antenna_left=-0.55, antenna_right=0.55),
        breath_amplitude_deg=0.5,
        breath_frequency_hz=0.06,
        sway_amplitude_rad=0.05,
        sway_frequency_hz=0.25,
        idle_interval_s=(30.0, 60.0),
        menu=(("droop", 0.7), ("glance_down", 0.3)),
    ),
    Emotion.PROUD: MotionStyle(
        base_pose=BodyPose(pitch=5.0, antenna_left=0.5, antenna_right=-0.5),
        breath_amplitude_deg=0.9,
        breath_frequency_hz=0.10,
        sway_amplitude_rad=0.14,
        sway_frequency_hz=0.4,
        idle_interval_s=(20.0, 40.0),
        menu=(("perk_up", 0.6), ("scan", 0.4)),
    ),
    Emotion.CONCERNED: MotionStyle(
        base_pose=BodyPose(pitch=-4.0, antenna_left=-0.3, antenna_right=0.3),
        breath_amplitude_deg=0.7,
        breath_frequency_hz=0.09,
        sway_amplitude_rad=0.08,
        sway_frequency_hz=0.35,
        idle_interval_s=(20.0, 45.0),
        menu=(("glance_down", 0.5), ("scan", 0.5)),
    ),
    Emotion.PLAYFUL: MotionStyle(
        base_pose=BodyPose(roll=4.0, antenna_left=0.4, antenna_right=-0.4),
        breath_amplitude_deg=1.1,
        breath_frequency_hz=0.13,
        sway_amplitude_rad=0.2,
        sway_frequency_hz=0.7,
        idle_interval_s=(10.0, 22.0),
        menu=(("antenna_twitch", 0.4), ("scan", 0.3), ("perk_up", 0.3)),
    ),
}


class IdleMotionEngine:
    """Produces continuous micro-motion offsets and picks occasional idle gestures."""

    def __init__(self, styles: Mapping[Emotion, MotionStyle] | None = None, rng: random.Random | None = None) -> None:
        """Initialize with optional per-personality style overrides and a random source."""
        self._styles = dict(styles) if styles is not None else EMOTION_STYLES
        self._rng = rng if rng is not None else random.Random()

    def style(self, emotion: Emotion) -> MotionStyle:
        """Return the motion style for an emotion."""
        return self._styles[emotion]

    def micro_motion(self, style: MotionStyle, t: float) -> BodyPose:
        """Return the breathing, antenna-sway, and wander offset pose at time t."""
        breath = style.breath_amplitude_deg * math.sin(2.0 * math.pi * style.breath_frequency_hz * t)
        sway = style.sway_amplitude_rad * math.sin(2.0 * math.pi * style.sway_frequency_hz * t + 1.3)
        wander = 0.8 * math.sin(2.0 * math.pi * 0.045 * t + 2.1)
        return BodyPose(yaw=wander, pitch=breath, roll=0.0, antenna_left=sway, antenna_right=-sway)

    def choose_gesture(self, emotion: Emotion) -> str:
        """Pick an idle gesture name from the emotion's weighted menu."""
        menu = self._styles[emotion].menu
        names = [name for name, _ in menu]
        weights = [weight for _, weight in menu]
        return self._rng.choices(names, weights=weights, k=1)[0]

    def next_interval(self, emotion: Emotion) -> float:
        """Draw the seconds until the next idle gesture for an emotion."""
        low, high = self._styles[emotion].idle_interval_s
        return self._rng.uniform(low, high)
