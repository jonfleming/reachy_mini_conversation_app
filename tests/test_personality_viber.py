"""Tests for vibe-creating a personality.

The LLM is always injected as a fake ``complete`` callable, so these run offline
and pin down the parts that matter: JSON parsing, the compile/repair loop, name
prefixing/dedup, tool filtering, and that commit persists exactly what compiles.
"""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


pytest.importorskip("rmscript")

from reachy_mini_conversation_app import personality_viber as pv  # noqa: E402
from reachy_mini_conversation_app.config import config  # noqa: E402
from reachy_mini_conversation_app.personality_routes import mount_personality_routes  # noqa: E402


# A behavior that compiles cleanly.
GOOD = "body left 90 fast\nwait 0.5s\nbody center fast"


def _fake(draft: dict, *, repair_to: str | None = None):
    """Build a fake ``complete``: first call returns ``draft`` JSON, repairs return ``repair_to``."""

    def complete(messages):
        system = messages[0]["content"]
        if system.startswith("You fix rmscript"):
            return repair_to or ""
        return json.dumps(draft)

    return complete


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def test_parse_draft_json_plain() -> None:
    """Plain JSON parses as-is."""
    assert pv.parse_draft_json('{"a": 1}') == {"a": 1}


def test_parse_draft_json_strips_fences_and_prose() -> None:
    """A fenced JSON object wrapped in chatter is still recovered."""
    text = 'Sure!\n```json\n{"a": 1}\n```\nhope that helps'
    assert pv.parse_draft_json(text) == {"a": 1}


def test_parse_draft_json_raises_on_garbage() -> None:
    """Non-JSON output raises VibeError rather than returning junk."""
    with pytest.raises(pv.VibeError):
        pv.parse_draft_json("not json at all")


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def test_generate_clean_draft() -> None:
    """A well-formed reply yields a sanitized name and a prefixed, compiling behavior."""
    draft = pv.generate_personality(
        "a pirate",
        complete=_fake(
            {
                "name": "Pirate Cap'n!",
                "instructions": "Talk like a pirate.",
                "greeting": "Arr!",
                "enable_tools": [],
                "new_behaviors": [{"name": "look out", "description": "Scan the horizon", "rmscript": GOOD}],
            }
        ),
    )
    assert draft.name == "Pirate_Capn"  # sanitized
    assert draft.new_behaviors[0].name == "Pirate_Capn_look_out"  # prefixed
    assert draft.new_behaviors[0].compiled_ok is True
    assert draft.new_behaviors[0].description == "Scan the horizon"


def test_enable_tools_filtered_to_catalog() -> None:
    """Tools the model names that don't exist are dropped; real ones survive."""
    draft = pv.generate_personality(
        "helper",
        complete=_fake(
            {
                "name": "helper",
                "instructions": "Be helpful.",
                "enable_tools": ["dance", "totally_made_up_tool"],
                "new_behaviors": [],
            }
        ),
    )
    assert "dance" in draft.enable_tools
    assert "totally_made_up_tool" not in draft.enable_tools


def test_duplicate_behavior_names_deduped() -> None:
    """Two behaviors with the same name get distinct, suffixed tool names."""
    draft = pv.generate_personality(
        "twins",
        complete=_fake(
            {
                "name": "twins",
                "instructions": "x",
                "new_behaviors": [
                    {"name": "wave", "description": "a", "rmscript": GOOD},
                    {"name": "wave", "description": "b", "rmscript": GOOD},
                ],
            }
        ),
    )
    names = [b.name for b in draft.new_behaviors]
    assert names == ["twins_wave", "twins_wave_2"]


def test_instructions_reference_prefixed_behavior_names() -> None:
    """Behavior names in the prompt are rewritten to the prefixed, registered names."""
    draft = pv.generate_personality(
        "kitten",
        complete=_fake(
            {
                "name": "kit",
                "instructions": "Use your look_around behavior when you hear something.",
                "greeting": "Hi! Let me look_around first.",
                "new_behaviors": [{"name": "look_around", "description": "Scan", "rmscript": GOOD}],
            }
        ),
    )
    assert draft.new_behaviors[0].name == "kit_look_around"
    assert "kit_look_around" in draft.instructions
    assert "kit_look_around" in draft.greeting
    # The bare name should no longer appear as a standalone word.
    import re

    assert not re.search(r"\blook_around\b", draft.instructions)


def test_repair_loop_fixes_broken_behavior() -> None:
    """A non-compiling behavior is repaired via a follow-up model call."""
    draft = pv.generate_personality(
        "fixer",
        complete=_fake(
            {
                "name": "fixer",
                "instructions": "x",
                "new_behaviors": [{"name": "b", "description": "d", "rmscript": "!!! not valid !!!"}],
            },
            repair_to=GOOD,
        ),
    )
    assert draft.new_behaviors[0].compiled_ok is True


def test_unrepairable_behavior_flagged_not_dropped() -> None:
    """A behavior that never compiles is kept in the draft, flagged compiled_ok=False."""
    draft = pv.generate_personality(
        "broken",
        complete=_fake(
            {
                "name": "broken",
                "instructions": "x",
                "new_behaviors": [{"name": "b", "description": "d", "rmscript": "!!! garbage !!!"}],
            },
            repair_to="!!! still garbage !!!",
        ),
    )
    assert len(draft.new_behaviors) == 1
    assert draft.new_behaviors[0].compiled_ok is False


# --------------------------------------------------------------------------- #
# Commit
# --------------------------------------------------------------------------- #
def test_commit_writes_behaviors_and_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Commit writes only compiling behaviors and a profile that enables them."""
    monkeypatch.setattr(config, "INSTANCE_PATH", tmp_path)
    # Isolate the shared rmscript library so the test doesn't touch the repo's profiles/.
    monkeypatch.setattr(config, "PROFILES_DIRECTORY", tmp_path)

    value = pv.commit_draft(
        {
            "name": "buccaneer",
            "instructions": "Be a pirate.",
            "greeting": "Arr!",
            "enable_tools": ["dance"],
            "new_behaviors": [
                {"name": "buccaneer_look", "description": "Look", "source": GOOD},
                {"name": "buccaneer_bad", "description": "Bad", "source": "!!! nope !!!"},
            ],
        }
    )

    assert value == "user_personalities/buccaneer"
    profile = tmp_path / "user_personalities" / "buccaneer"
    assert (profile / "instructions.txt").read_text().strip() == "Be a pirate."
    tools = (profile / "tools.txt").read_text().split()
    assert tools == ["dance", "buccaneer_look"]  # non-compiling behavior dropped
    assert (tmp_path / "rmscript_tools" / "buccaneer_look.rmscript").is_file()
    assert not (tmp_path / "rmscript_tools" / "buccaneer_bad.rmscript").exists()


def test_commit_rejects_empty_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A name that sanitizes to nothing is rejected."""
    monkeypatch.setattr(config, "INSTANCE_PATH", tmp_path)
    with pytest.raises(pv.VibeError):
        pv.commit_draft({"name": "!!!", "instructions": "x"})


# --------------------------------------------------------------------------- #
# Route guard
# --------------------------------------------------------------------------- #
def test_generate_route_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an HF token the generate route fails fast with a friendly code."""
    monkeypatch.setattr(pv, "has_token", lambda: False)
    app = FastAPI()
    mount_personality_routes(app, handler=object(), get_loop=lambda: None)  # type: ignore[arg-type]
    resp = TestClient(app).post("/personalities/vibe/generate", json={"description": "a pirate"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "no_hf_token"


def test_generate_then_commit_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The generate and commit routes wire together: draft out, files + profile in."""
    monkeypatch.setattr(config, "INSTANCE_PATH", tmp_path)
    monkeypatch.setattr(config, "PROFILES_DIRECTORY", tmp_path)
    monkeypatch.setattr(pv, "has_token", lambda: True)
    monkeypatch.setattr(
        pv,
        "generate_personality",
        lambda description: pv.VibeDraft(
            name="captain",
            instructions="Be a captain.",
            greeting="Ahoy!",
            enable_tools=["dance"],
            new_behaviors=[pv.NewBehavior("captain_salute", "Salute", GOOD, True)],
        ),
    )
    app = FastAPI()
    mount_personality_routes(app, handler=object(), get_loop=lambda: None)  # type: ignore[arg-type]
    client = TestClient(app)

    gen = client.post("/personalities/vibe/generate", json={"description": "a sea captain"})
    assert gen.status_code == 200
    draft = gen.json()["draft"]
    assert draft["name"] == "captain"

    commit = client.post("/personalities/vibe/commit", json={"draft": draft})
    assert commit.status_code == 200
    assert commit.json()["value"] == "user_personalities/captain"
    assert (tmp_path / "user_personalities" / "captain" / "instructions.txt").is_file()
    assert (tmp_path / "rmscript_tools" / "captain_salute.rmscript").is_file()
