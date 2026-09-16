"""Tests for name and activity extraction from transcripts."""

from reachy_buddy.conversation.awareness import extract_name, extract_activity, wants_face_enroll


def test_extract_name_from_introduction() -> None:
    """A spoken introduction yields a capitalized display name."""
    assert extract_name("hi my name is jon") == "Jon"
    assert extract_name("I'm Alex") == "Alex"
    assert extract_name("call me Sam") == "Sam"
    assert extract_name("it's Maya") == "Maya"


def test_extract_name_bare_only_when_requested() -> None:
    """A lone name is accepted only when the caller is already waiting for one."""
    assert extract_name("Jon") is None
    assert extract_name("Jon", allow_bare=True) == "Jon"
    assert extract_name("hello", allow_bare=True) is None


def test_extract_name_ignores_common_false_positives() -> None:
    """Everyday 'I am stuck' does not become a name."""
    assert extract_name("I'm stuck") is None
    assert extract_name("hello there") is None


def test_extract_activity_from_working_on() -> None:
    """A stated project is captured as an activity string."""
    assert extract_activity("I'm working on the CAD mount") == "the CAD mount"
    assert extract_activity("working on docker") == "docker"


def test_extract_activity_ignores_unrelated_speech() -> None:
    """Small talk is not treated as a project."""
    assert extract_activity("pretty quiet in here") is None


def test_wants_face_enroll_from_retry_phrases() -> None:
    """Retry and remember-my-face phrasing is recognized."""
    assert wants_face_enroll("Let's try again my face.")
    assert wants_face_enroll("remember my face")
    assert not wants_face_enroll("okay")
