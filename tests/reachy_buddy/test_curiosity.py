"""Tests for the curiosity engine's arbitration."""

import time

from reachy_buddy.core.drives import Drives
from reachy_buddy.core.curiosity import CuriosityEngine
from reachy_buddy.core.monologue import Thought
from reachy_buddy.core.personality import Personality


def speakable_thought(salience: float = 0.9) -> Thought:
    """Build a speak-worthy thought with the given salience."""
    return Thought("Jon looks stuck on that terminal", time.time(), salience, "speak_candidate", "test")


def test_novelty_decays_after_attention() -> None:
    """Never-seen things are fully novel; attention resets the clock."""
    engine = CuriosityEngine()
    assert engine.score("coffee cup") == 1.0

    engine.mark_seen("coffee cup")
    assert engine.score("coffee cup") < 0.05


def test_low_confidence_quietly_watches() -> None:
    """Below the confidence threshold the engine chooses deliberate stillness."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(confidence=0.1), seconds_since_speech=999.0, novel_subject="anything")

    assert intent.kind == "quiet"


def test_low_social_energy_quietly_watches() -> None:
    """A drained buddy stops initiating even with something novel in view."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(social_energy=0.1), seconds_since_speech=999.0, novel_subject="anything")

    assert intent.kind == "quiet"


def test_nobody_present_means_attend_not_speak() -> None:
    """With nobody around there is no one to talk to, so the engine just keeps watching."""
    engine = CuriosityEngine()
    intent = engine.decide(
        Drives(curiosity=0.95, playfulness=0.95),
        seconds_since_speech=999.0,
        novel_subject="mystery object",
        thought=speakable_thought(),
        someone_present=False,
    )

    assert intent.kind == "attend"


def test_high_curiosity_asks_about_the_novel_thing() -> None:
    """Curiosity past the threshold becomes a question about the novel subject."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(curiosity=0.9), seconds_since_speech=999.0, novel_subject="coffee cup")

    assert intent.kind == "ask"
    assert "coffee cup" in intent.payload


def test_high_playfulness_makes_a_joke() -> None:
    """Playfulness past the threshold becomes a joke."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(playfulness=0.9), seconds_since_speech=999.0)

    assert intent.kind == "joke"


def test_below_thresholds_the_engine_keeps_watching() -> None:
    """Ordinary internal state produces attendance, not noise."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(), seconds_since_speech=10.0)

    assert intent.kind == "attend"


def test_speak_worthy_thought_can_become_dialogue() -> None:
    """A strong thought plus long enough silence crosses the speak threshold."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(), seconds_since_speech=900.0, thought=speakable_thought())

    assert intent.kind == "speak"
    assert intent.payload == "Jon looks stuck on that terminal"


def test_recent_speech_keeps_a_good_thought_internal() -> None:
    """The same thought stays private when the buddy spoke moments ago."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(), seconds_since_speech=5.0, thought=speakable_thought(salience=0.7))

    assert intent.kind == "attend"


def test_cooldown_suppresses_back_to_back_outbursts() -> None:
    """After speaking up once, the engine goes quiet until the cooldown elapses."""
    engine = CuriosityEngine(personality=Personality(speak_cooldown_s=45.0))
    engine.mark_spoke()
    intent = engine.decide(
        Drives(curiosity=0.95), seconds_since_speech=999.0, novel_subject="coffee cup", thought=speakable_thought()
    )

    assert intent.kind == "attend"
    assert "cooldown" in intent.reason


def test_answered_outcome_encourages_and_rewards() -> None:
    """An answered utterance raises engagement and returns a rewarding stimulus."""
    engine = CuriosityEngine()
    stimulus = engine.outcome_stimulus(answered=True)

    assert engine.engagement > 1.0
    assert stimulus.confidence > 0.0


def test_ignored_outcome_discourages_and_dents_confidence() -> None:
    """An ignored utterance lowers engagement and returns a punishing stimulus."""
    engine = CuriosityEngine()
    stimulus = engine.outcome_stimulus(answered=False)

    assert engine.engagement < 1.0
    assert stimulus.confidence < 0.0


def test_unfinished_callback_can_win_arbitration() -> None:
    """A check-in candidate is chosen when nothing more urgent is on the table."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(), seconds_since_speech=30.0, checkin="Did the CAD mount work?")

    assert intent.kind == "checkin"
    assert intent.payload == "Did the CAD mount work?"


def test_long_visit_can_suggest_a_break() -> None:
    """A due break becomes an intent when focus is not keeping the buddy quiet."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(focus=0.2), seconds_since_speech=30.0, break_due=True)

    assert intent.kind == "break"


def test_desktop_stuck_can_become_a_checkin() -> None:
    """A stuck-screen observation may become an ask; it is not forced speech."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(), seconds_since_speech=30.0, desktop_stuck="desktop:stuck:Code")

    assert intent.kind == "ask"
    assert "desktop:stuck:Code" in intent.payload


def test_desktop_stuck_stays_quiet_when_drives_are_low() -> None:
    """Low confidence still refuses a stuck-screen check-in."""
    engine = CuriosityEngine()
    intent = engine.decide(Drives(confidence=0.1), seconds_since_speech=30.0, desktop_stuck="desktop:stuck:Code")

    assert intent.kind == "quiet"


def test_desktop_stuck_cooldown_allows_only_one_proactive() -> None:
    """After one stuck-screen comment, the longer cool-down blocks another."""
    engine = CuriosityEngine(desktop_cooldown_s=1800.0)
    first = engine.decide(Drives(), seconds_since_speech=30.0, desktop_stuck="desktop:stuck:Code")
    assert first.kind == "ask"
    engine.mark_desktop_spoke()
    engine._last_proactive_at = time.time() - 999.0
    second = engine.decide(Drives(curiosity=0.95), seconds_since_speech=999.0, desktop_stuck="desktop:stuck:Code")

    assert second.kind != "ask"


def test_engagement_stays_bounded() -> None:
    """Repeated outcomes can never push engagement outside its learned range."""
    engine = CuriosityEngine()
    for _ in range(100):
        engine.outcome_stimulus(answered=False)
    assert engine.engagement == 0.5
    for _ in range(100):
        engine.outcome_stimulus(answered=True)
    assert engine.engagement == 1.5
