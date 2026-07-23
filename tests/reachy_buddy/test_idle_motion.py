"""Tests for the idle motion engine: styles, micro-motion bounds, and weighted menus."""

import random

import pytest

from reachy_buddy.animation.idle import EMOTION_STYLES, MotionStyle, IdleMotionEngine
from reachy_buddy.core.emotional_state import Emotion


def test_every_emotion_has_a_style() -> None:
    """The default personality styles all seven labels."""
    assert set(EMOTION_STYLES) == set(Emotion)


def test_micro_motion_stays_within_style_amplitudes() -> None:
    """Continuous motion never exceeds the style's breathing and sway amplitudes."""
    engine = IdleMotionEngine()
    for style in EMOTION_STYLES.values():
        for i in range(400):
            offset = engine.micro_motion(style, i * 0.37)
            assert abs(offset.pitch) <= style.breath_amplitude_deg + 1e-9
            assert abs(offset.antenna_left) <= style.sway_amplitude_rad + 1e-9
            assert abs(offset.antenna_right) <= style.sway_amplitude_rad + 1e-9
            assert abs(offset.yaw) <= 0.8 + 1e-9


def test_micro_motion_is_continuous() -> None:
    """Small time steps produce small pose changes; the idle layer never jitters."""
    engine = IdleMotionEngine()
    style = EMOTION_STYLES[Emotion.EXCITED]
    for i in range(200):
        t = i * 0.113
        delta = engine.micro_motion(style, t + 0.05)
        current = engine.micro_motion(style, t)
        assert abs(delta.pitch - current.pitch) < 0.15
        assert abs(delta.antenna_left - current.antenna_left) < 0.08


def test_choose_gesture_only_picks_menu_members() -> None:
    """Idle picks always come from the emotion's menu."""
    engine = IdleMotionEngine(rng=random.Random(3))
    for emotion in Emotion:
        menu_names = {name for name, _ in EMOTION_STYLES[emotion].menu}
        for _ in range(30):
            assert engine.choose_gesture(emotion) in menu_names


def test_excited_menu_favors_antenna_twitch() -> None:
    """Weighted menus express the emotion: excitement twitches often."""
    engine = IdleMotionEngine(rng=random.Random(11))
    picks = [engine.choose_gesture(Emotion.EXCITED) for _ in range(300)]
    assert picks.count("antenna_twitch") > picks.count("perk_up")


def test_next_interval_stays_in_range() -> None:
    """Idle cadence draws uniformly inside the style's window."""
    engine = IdleMotionEngine(rng=random.Random(5))
    for emotion in Emotion:
        low, high = EMOTION_STYLES[emotion].idle_interval_s
        for _ in range(30):
            assert low <= engine.next_interval(emotion) <= high


def test_style_lerp_blends_continuous_parameters() -> None:
    """Blending two styles interpolates pose and breathing but takes the target menu."""
    calm = EMOTION_STYLES[Emotion.CALM]
    excited = EMOTION_STYLES[Emotion.EXCITED]
    mid = calm.lerp(excited, 0.5)
    assert mid.breath_amplitude_deg == pytest.approx((calm.breath_amplitude_deg + excited.breath_amplitude_deg) / 2)
    assert mid.base_pose.antenna_left == pytest.approx(
        (calm.base_pose.antenna_left + excited.base_pose.antenna_left) / 2
    )
    assert mid.menu == excited.menu


def test_style_overrides_support_personality() -> None:
    """A personality can restyle an emotion without touching the defaults."""
    custom = MotionStyle(
        base_pose=EMOTION_STYLES[Emotion.CALM].base_pose,
        breath_amplitude_deg=0.1,
        breath_frequency_hz=0.05,
        sway_amplitude_rad=0.02,
        sway_frequency_hz=0.2,
        idle_interval_s=(60.0, 90.0),
        menu=(("scan", 1.0),),
    )
    engine = IdleMotionEngine(styles={**EMOTION_STYLES, Emotion.CALM: custom}, rng=random.Random(1))
    assert engine.style(Emotion.CALM).breath_amplitude_deg == 0.1
    assert 60.0 <= engine.next_interval(Emotion.CALM) <= 90.0
    assert engine.style(Emotion.EXCITED) == EMOTION_STYLES[Emotion.EXCITED]
