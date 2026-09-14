"""Optional llama.cpp thought generator; falls back to templates on any failure."""

import logging

import httpx

from reachy_buddy.core.monologue import ThoughtContext, TemplateThoughtGenerator


logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are Reachy's private inner monologue. Write one short observation "
    "(under 20 words) about what you are seeing or how long it has been quiet. "
    "Do not address anyone. Do not use quotation marks."
)


class LlamaThoughtGenerator:
    """Drafts a thought via an OpenAI-compatible llama.cpp server."""

    def __init__(
        self,
        base_url: str,
        model: str = "local",
        timeout_s: float = 2.5,
        fallback: TemplateThoughtGenerator | None = None,
    ) -> None:
        """Initialize with the server origin (no trailing slash) and model id."""
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._timeout_s = timeout_s
        self._fallback = fallback or TemplateThoughtGenerator()
        self._client = httpx.Client(timeout=timeout_s)

    def generate(self, context: ThoughtContext) -> tuple[str, float]:
        """Return (text, salience); use the template generator if the server fails."""
        prompt = (
            f"World: {context.world_summary}\n"
            f"Mood: {context.emotion_label}\n"
            f"Silent for {context.seconds_since_speech:.0f}s\n"
            f"Present: {', '.join(context.present_labels) or 'nobody'}\n"
            f"Recent thoughts: {'; '.join(context.recent_thoughts) or 'none'}"
        )
        try:
            response = self._client.post(
                self._url,
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 48,
                    "temperature": 0.8,
                },
            )
            response.raise_for_status()
            payload = response.json()
            text = str(payload["choices"][0]["message"]["content"]).strip().strip('"')
            if not text:
                raise ValueError("empty thought")
            salience = 0.55
            if context.seconds_since_speech >= 60.0:
                salience = 0.7
            if context.present_labels:
                salience = max(salience, 0.5)
            return text, min(1.0, salience)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("llama.cpp thought failed; using template: %s", exc)
            return self._fallback.generate(context)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
