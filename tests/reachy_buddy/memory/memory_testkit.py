"""Shared helpers for memory subsystem tests: scripted MockTransport clients."""

import json
from collections.abc import Callable

import httpx

from reachy_buddy.memory.hindsight import HindsightClient


Handler = Callable[[httpx.Request], httpx.Response]
# (method, path, json body, status code or "error" when the handler raised)
RecordedRequest = tuple[str, str, dict[str, object], object]


def make_client(handler: Handler, recorded: list[RecordedRequest]) -> HindsightClient:
    """Build a client whose requests are recorded and answered by handler."""

    def route(request: httpx.Request) -> httpx.Response:
        body: dict[str, object] = {}
        if request.content:
            body = json.loads(request.content.decode())
        try:
            response = handler(request)
        except Exception:
            recorded.append((request.method, request.url.path, body, "error"))
            raise
        recorded.append((request.method, request.url.path, body, response.status_code))
        return response

    return HindsightClient(client=httpx.AsyncClient(transport=httpx.MockTransport(route), base_url="http://test"))


def ok_json(payload: dict[str, object], status: int = 200) -> httpx.Response:
    """Build a JSON response for MockTransport handlers."""
    return httpx.Response(status, json=payload)
