"""Tests for the motivation drives and their stimulus dynamics."""

import pytest

from reachy_buddy.core.drives import STIMULUS_BY_KIND, Drives, Stimulus


def test_apply_clamps_to_unit_interval() -> None:
    """Stimuli can never push a drive outside [0, 1]."""
    drives = Drives(curiosity=0.95, confidence=0.05)
    drives.apply(Stimulus(curiosity=0.2, confidence=-0.2))

    assert drives.curiosity == 1.0
    assert drives.confidence == 0.0


def test_stimulate_scales_table_entry_by_salience() -> None:
    """A known observation kind moves the drives by its table entry times salience."""
    drives = Drives(curiosity=0.5)
    drives.stimulate("person_arrived", salience=0.5)

    assert drives.curiosity == pytest.approx(0.6)


def test_stimulate_unknown_kind_leaves_drives_unchanged() -> None:
    """An unmapped kind logs a warning instead of moving anything."""
    drives = Drives()
    before = Drives(**vars(drives))
    drives.stimulate("does_not_exist")

    assert vars(drives) == vars(before)


def test_decay_toward_baseline_moves_without_overshoot() -> None:
    """Each decay step closes part of the gap to the baseline and never crosses it."""
    drives = Drives(curiosity=0.9)
    drives.decay_toward(Drives(curiosity=0.5), rate=0.25)

    assert drives.curiosity == pytest.approx(0.8)
    for _ in range(100):
        drives.decay_toward(Drives(curiosity=0.5), rate=0.25)
    assert drives.curiosity == pytest.approx(0.5)


@pytest.mark.parametrize("kind", list(STIMULUS_BY_KIND))
def test_every_observation_kind_changes_motivation_safely(kind: str) -> None:
    """Every table entry is applicable and keeps all drives inside [0, 1]."""
    drives = Drives()
    drives.stimulate(kind, salience=5.0)

    for value in vars(drives).values():
        assert 0.0 <= value <= 1.0
