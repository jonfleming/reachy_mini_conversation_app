"""Tests for the world model."""

import time

from reachy_buddy.core.world_model import WorldModel


def test_record_stores_kind_and_salience() -> None:
    """Observations carry their kind and salience for stimulus and arbitration use."""
    model = WorldModel()
    model.record("jon", 0.9, kind="person_arrived", salience=0.8)
    observation = model.active()[0]

    assert observation.kind == "person_arrived"
    assert observation.salience == 0.8


def test_record_refresh_updates_existing_observation() -> None:
    """Re-recording a label refreshes confidence, kind, salience, and last-seen time."""
    model = WorldModel()
    model.record("jon", 0.4, kind="ambient")
    model.record("jon", 0.9, kind="person_arrived", salience=0.8)

    observations = model.active()
    assert len(observations) == 1
    assert observations[0].confidence == 0.9
    assert observations[0].kind == "person_arrived"


def test_stale_observations_are_forgotten() -> None:
    """Observations past the retention window stop being active."""
    model = WorldModel(retention_seconds=0.05)
    model.record("jon", 0.9)
    time.sleep(0.06)

    assert model.active() == []
    model.record("jon", 0.9)
    time.sleep(0.06)
    model.forget_stale()
    model.record("jon", 0.9)
    assert len(model.active()) == 1


def test_summary_text_renders_presence_with_age() -> None:
    """The prompt-ready summary names what is present and for how long."""
    model = WorldModel()
    model.record("jon", 0.9, kind="person_arrived")

    assert "jon" in model.summary_text()


def test_summary_text_for_an_empty_world() -> None:
    """An empty model says so plainly."""
    assert WorldModel().summary_text() == "Nothing observed yet."


def test_summary_text_respects_the_character_budget() -> None:
    """Long summaries are truncated to fit the prompt budget."""
    model = WorldModel()
    for index in range(50):
        model.record(f"observation number {index}", 0.5)

    assert len(model.summary_text(max_chars=120)) <= 120
