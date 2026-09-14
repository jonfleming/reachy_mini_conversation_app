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
    r"\b(?:my name is|i am|i'm|call me|this is)\s+([A-Za-z][A-Za-z'-]{1,30})\b",
    re.IGNORECASE,
)
_ACTIVITY_RE = re.compile(
    r"\b(?:i(?:'m| am) working on|working on|i(?:'m| am) building|i(?:'m| am) debugging|debugging)\s+(.+)$",
    re.IGNORECASE,
)


def extract_name(text: str) -> str | None:
    """Return a display name if the user introduces themselves."""
    match = _NAME_RE.search(text.strip())
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
