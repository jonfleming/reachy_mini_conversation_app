"""Speech integration: utterances out, transcriptions in; backends plug in as callables."""

import logging
from collections.abc import Callable


logger = logging.getLogger(__name__)

SpeakFn = Callable[[str], None]
ListenFn = Callable[[float], str | None]


class SpeechInterface:
    """Routes speech through optional speak/listen backends."""

    def __init__(self, speak: SpeakFn | None = None, listen: ListenFn | None = None) -> None:
        """Initialize with optional backends; without them the interface is inert."""
        self._speak = speak
        self._listen = listen

    def say(self, text: str) -> None:
        """Speak text through the backend; log instead when none is connected."""
        if self._speak is None:
            logger.info("say (no speech backend): %s", text)
            return
        self._speak(text)

    def hear(self, timeout_seconds: float = 5.0) -> str | None:
        """Return a transcription from the backend; None when none is connected."""
        if self._listen is None:
            return None
        return self._listen(timeout_seconds)
