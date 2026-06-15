"""HTTP client for the Reachy Mini daemon's NFC reader API.

The daemon owns the serial link to the Arduino NFC module and exposes it at
``/api/nfc``. This module wraps those endpoints so the conversation app never
touches the serial port directly.

write_tag() is non-blocking: it starts a background thread and enqueues the
``(success, raw_msg)`` result. Call drain_write_results() (e.g. in a poll
loop) to consume those results.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class NfcTagSnapshot:
    """Point-in-time state of the NFC reader."""

    present: bool
    uid: Optional[str]
    content: Optional[str]   # text content; None if blank or no tag
    blank: bool               # tag present but no content written


class NfcDaemonClient:
    """HTTP client wrapping the daemon's /api/nfc routes.

    Usage::

        client = NfcDaemonClient()          # default http://localhost:8000
        tag = client.get_tag()
        if tag.present and not tag.blank:
            print("Code:", tag.content)
        client.write_tag("HELLO")           # non-blocking; result via drain_write_results()
    """

    def __init__(
        self, base_url: str = "http://localhost:8000", timeout: float = 5.0
    ) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._write_queue: queue.SimpleQueue[tuple[bool, str]] = queue.SimpleQueue()

    # -- Tag state ----------------------------------------------------------------

    def get_tag(self) -> NfcTagSnapshot:
        """Return the current tag state (never raises; returns absent on error)."""
        try:
            r = requests.get(f"{self.base}/api/nfc/tag", timeout=self.timeout)
            r.raise_for_status()
            d = r.json()
            return NfcTagSnapshot(
                present=bool(d.get("present")),
                uid=d.get("uid"),
                content=d.get("content") or None,
                blank=bool(d.get("blank")),
            )
        except Exception as exc:
            logger.debug("NFC get_tag error: %s", exc)
            return NfcTagSnapshot(present=False, uid=None, content=None, blank=False)

    # -- Reader status ------------------------------------------------------------

    def get_status(self) -> dict:
        """Return the daemon NFC reader status (never raises; returns disconnected on error)."""
        try:
            r = requests.get(f"{self.base}/api/nfc/status", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            logger.debug("NFC get_status error: %s", exc)
            return {
                "connected": False,
                "module_detected": False,
                "port": None,
                "last_line": None,
                "error": str(exc),
            }

    def is_connected(self) -> bool:
        """Return True if the daemon reports the NFC reader as connected."""
        return bool(self.get_status().get("connected"))

    # -- Write --------------------------------------------------------------------

    def write_tag(self, code: str) -> str:
        """Start an async write of ``code`` onto the next presented tag.

        Returns a human-readable status string immediately. The write result
        (``WRITE_OK`` or ``WRITE_FAIL:<reason>``) is enqueued and available via
        :meth:`drain_write_results`.
        """
        text = code[:12]

        def _worker() -> None:
            try:
                r = requests.post(
                    f"{self.base}/api/nfc/write",
                    json={"text": text},
                    timeout=max(self.timeout, 12.0),
                )
                if r.status_code == 503:
                    detail = r.json().get("detail", "unavailable")
                    self._write_queue.put((False, f"WRITE_FAIL:{detail}"))
                    return
                r.raise_for_status()
                d = r.json()
                if d.get("success"):
                    self._write_queue.put((True, "WRITE_OK"))
                else:
                    self._write_queue.put((False, f"WRITE_FAIL:{d.get('error', 'unknown')}"))
            except Exception as exc:
                logger.warning("NFC write_tag error: %s", exc)
                self._write_queue.put((False, f"WRITE_FAIL:{exc}"))

        threading.Thread(target=_worker, daemon=True).start()
        return f"Bring a tag close to write '{text}'…"

    def write_tag_sync(self, code: str, timeout: float = 12.0) -> tuple[bool, str]:
        """Write ``code`` synchronously (tag must already be on the reader).

        Returns ``(True, "WRITE_OK")`` on success or ``(False, reason)`` on failure.
        """
        text = code[:12]
        try:
            r = requests.post(
                f"{self.base}/api/nfc/write",
                json={"text": text},
                timeout=timeout,
            )
            if r.status_code == 503:
                return False, r.json().get("detail", "unavailable")
            r.raise_for_status()
            d = r.json()
            if d.get("success"):
                return True, "WRITE_OK"
            return False, d.get("error", "unknown")
        except Exception as exc:
            logger.warning("NFC write_tag_sync error: %s", exc)
            return False, str(exc)

    def drain_write_results(self) -> list[tuple[bool, str]]:
        """Drain and return all pending write results (non-blocking)."""
        results: list[tuple[bool, str]] = []
        try:
            while True:
                results.append(self._write_queue.get_nowait())
        except queue.Empty:
            pass
        return results
