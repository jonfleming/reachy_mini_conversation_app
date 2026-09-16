"""Tests for llama.cpp thought generation falling back to templates."""

import httpx

from reachy_buddy.core.monologue import ThoughtContext
from reachy_buddy.core.llama_thoughts import LlamaThoughtGenerator


def _context() -> ThoughtContext:
    return ThoughtContext(world_summary="Jon (just now)", seconds_since_speech=120.0, emotion_label="curious")


def test_llama_returns_server_text() -> None:
    """A successful chat completion becomes the thought line."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json={"choices": [{"message": {"content": "The mug has been there a while."}}]})

    generator = LlamaThoughtGenerator("http://llama.test/v1")
    generator._client = httpx.Client(transport=httpx.MockTransport(handler))
    text, salience = generator.generate(_context())

    assert "mug" in text
    assert 0.0 < salience <= 1.0
    generator.close()


def test_llama_uses_reasoning_content_when_message_is_empty() -> None:
    """Gemma-style thinking replies put the line in reasoning_content, not content."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "The mug has been sitting there a while.",
                        }
                    }
                ]
            },
        )

    generator = LlamaThoughtGenerator("http://llama.test/v1")
    generator._client = httpx.Client(transport=httpx.MockTransport(handler))
    text, _salience = generator.generate(_context())

    assert "mug" in text
    generator.close()


def test_llama_reads_list_content_parts() -> None:
    """Some servers return assistant content as a list of typed parts."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [{"type": "text", "text": "Quiet room, nothing new yet."}],
                        }
                    }
                ]
            },
        )

    generator = LlamaThoughtGenerator("http://llama.test/v1")
    generator._client = httpx.Client(transport=httpx.MockTransport(handler))
    text, _salience = generator.generate(_context())

    assert "Quiet room" in text
    generator.close()


def test_llama_falls_back_when_the_server_fails() -> None:
    """HTTP failures use the template generator instead of raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    generator = LlamaThoughtGenerator("http://llama.test/v1")
    generator._client = httpx.Client(transport=httpx.MockTransport(handler))
    text, salience = generator.generate(_context())

    assert text
    assert 0.0 <= salience <= 1.0
    generator.close()
