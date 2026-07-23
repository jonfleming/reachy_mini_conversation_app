"""Tests for the personality parameter sets."""

from reachy_buddy.core.personality import PERSONALITIES, Personality


def test_default_personality_is_sane() -> None:
    """Default thresholds and cadence stay in range and order."""
    personality = Personality()

    assert 0.0 <= personality.chattiness <= 1.0
    assert 0.0 <= personality.quiet_confidence <= 1.0
    assert 0.0 <= personality.quiet_social_energy <= 1.0
    low_s, high_s = personality.monologue_cadence_s
    assert 0.0 < low_s <= high_s
    assert personality.speak_cooldown_s > 0.0


def test_registry_offers_distinct_characters() -> None:
    """The registry ships a default and a noir detective who is chattier-shy and more curious."""
    assert set(PERSONALITIES) >= {"default", "noir_detective"}
    noir = PERSONALITIES["noir_detective"]
    default = PERSONALITIES["default"]

    assert noir.chattiness < default.chattiness
    assert noir.baseline.curiosity > default.baseline.curiosity
    assert noir.speak_cooldown_s > default.speak_cooldown_s


def test_personalities_do_not_share_baseline_state() -> None:
    """Each registered personality owns an independent baseline drives object."""
    PERSONALITIES["default"].baseline.curiosity = 0.99

    assert PERSONALITIES["noir_detective"].baseline.curiosity != 0.99
