"""Optional llama.cpp thought generator; falls back to templates on any failure."""

import re
import logging

import httpx

from reachy_buddy.core.monologue import ThoughtContext, TemplateThoughtGenerator


logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are Reachy's private inner monologue. Write one short observation "
    "(under 20 words) about what you are seeing or how long it has been quiet. "
    "Do not address anyone. Do not use quotation marks. Do not write a chain of thought."
)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_MAX_THOUGHT_WORDS = 24


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
                    "max_tokens": 96,
                    "temperature": 0.8,
                    # Gemma/Qwen thinking templates often spend the whole budget
                    # in a hidden channel and leave message.content empty.
                    "chat_template_kwargs": {"enable_thinking": False},
                    "enable_thinking": False,
                },
            )
            response.raise_for_status()
            text = thought_text_from_payload(response.json())
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


def thought_text_from_payload(payload: object) -> str:
    """Pull a thought line out of an OpenAI-compatible chat completion body."""
    if not isinstance(payload, dict):
        raise ValueError("empty thought")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("empty thought")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        message = {}
    text = _as_text(message.get("content"))
    if not text:
        text = _as_text(message.get("reasoning_content")) or _as_text(message.get("reasoning"))
    if not text:
        text = _as_text(choice.get("text"))
    text = _THINK_RE.sub("", text).strip().strip('"')
    if not text:
        raise ValueError(f"empty thought keys={sorted(message)}")
    words = text.split()
    if len(words) > _MAX_THOUGHT_WORDS:
        text = " ".join(words[:_MAX_THOUGHT_WORDS])
    return text


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                for key in ("text", "content", "thinking", "reasoning"):
                    chunk = item.get(key)
                    if isinstance(chunk, str) and chunk.strip():
                        parts.append(chunk.strip())
                        break
        return " ".join(parts)
    return ""
