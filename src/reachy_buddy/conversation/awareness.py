"""Parse names and stated activities from user transcripts."""

import re


_STOP_NAMES = frozenset(
    {
        "fine",
        "good",
        "here",
        "back",
        "just",
        "going",
        "working",
        "stuck",
        "okay",
        "ok",
        "busy",
        "done",
        "there",
        "ready",
        "sorry",
        "hello",
        "hi",
    }
)

_NAME_RE = re.compile(
    r"\b(?:my name is|i am|i'm|i’m|call me|this is|it's|it is)\s+([A-Za-z][A-Za-z'-]{1,30})\b",
    re.IGNORECASE,
)
_BARE_NAME_RE = re.compile(r"^([A-Za-z][A-Za-z'-]{1,30})[.!?]?$")
_ACTIVITY_RE = re.compile(
    r"\b(?:i(?:'m| am) working on|working on|i(?:'m| am) building|i(?:'m| am) debugging|debugging)\s+(.+)$",
    re.IGNORECASE,
)
_FACE_ENROLL_RE = re.compile(
    r"\b(?:try again|remember (?:my )?face|enrol+l(?: me)?|look at my face|recognize (?:my face|me))\b",
    re.IGNORECASE,
)


def extract_name(text: str, *, allow_bare: bool = False) -> str | None:
    """Return a display name if the user introduces themselves."""
    stripped = text.strip()
    match = _NAME_RE.search(stripped)
    if match is None and allow_bare:
        match = _BARE_NAME_RE.fullmatch(stripped)
    if match is None:
        return None
    name = match.group(1).strip("-'")
    if name.lower() in _STOP_NAMES:
        return None
    return name[:1].upper() + name[1:]


def extract_activity(text: str) -> str | None:
    """Return a stated activity, or None when the utterance is not about work."""
    stripped = text.strip()
    if not stripped:
        return None
    match = _ACTIVITY_RE.search(stripped)
    if match is None:
        return None
    activity = match.group(1).strip().rstrip(".")
    return activity or None


def wants_face_enroll(text: str) -> bool:
    """Whether the utterance asks to (re)enroll the face currently in view."""
    return _FACE_ENROLL_RE.search(text.strip()) is not None
