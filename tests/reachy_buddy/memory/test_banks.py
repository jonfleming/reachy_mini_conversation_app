"""Tests for per-personality bank provisioning."""

import httpx
import pytest

from reachy_buddy.memory.banks import DEFAULT_DISPOSITION, BankManager
from reachy_buddy.memory.hindsight import Disposition
from .memory_testkit import ok_json, make_client


def test_profile_for_slugifies_personality_names(recorded_requests) -> None:
    """Bank ids are reachy-<slug>, with unsafe characters folded to dashes."""
    banks = BankManager(make_client(lambda request: ok_json({}), recorded_requests))

    assert banks.profile_for("default").bank_id == "reachy-default"
    assert banks.profile_for("Noir Detective!").bank_id == "reachy-noir-detective"
    assert banks.profile_for("mars_rover").bank_id == "reachy-mars_rover"
    assert banks.profile_for("!!!").bank_id == "reachy-default"


def test_profile_for_applies_per_personality_overrides(recorded_requests) -> None:
    """A personality can override mission and disposition; defaults fill the rest."""
    banks = BankManager(make_client(lambda request: ok_json({}), recorded_requests))
    noir = Disposition(skepticism=5, literalism=4, empathy=2)

    profile = banks.profile_for("noir", mission="Notice inconsistencies", disposition=noir)
    plain = banks.profile_for("hype")

    assert profile.mission == "Notice inconsistencies"
    assert profile.disposition == noir
    assert plain.disposition == DEFAULT_DISPOSITION
    assert plain.mission


@pytest.mark.asyncio
async def test_ensure_provisions_each_bank_once(recorded_requests) -> None:
    """Repeated ensure calls for the same bank issue a single PUT."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        return ok_json({"bank_id": "ok"})

    banks = BankManager(make_client(handler, recorded_requests))
    profile = banks.profile_for("default")

    await banks.ensure(profile)
    await banks.ensure(profile)
    await banks.ensure(banks.profile_for("noir"))

    puts = [entry for entry in recorded_requests if entry[0] == "PUT"]
    assert len(puts) == 2
    assert {entry[1] for entry in puts} == {"/v1/default/banks/reachy-default", "/v1/default/banks/reachy-noir"}
