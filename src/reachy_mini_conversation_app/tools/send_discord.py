import json
import logging
from typing import Any, Dict

from reachy_mini_conversation_app.config import config
from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies
from reachy_mini_conversation_app.camera_frame_encoding import encode_bgr_frame_as_jpeg


logger = logging.getLogger(__name__)


_MAX_DISCORD_CONTENT_LEN = 2000


class SendDiscord(Tool):
    """Send a notification to the user via a configured Discord webhook."""

    name = "send_discord"
    description = (
        "Send a text notification to the user via Discord. "
        "Optionally attach the current camera view as an image. "
        "Use this when the user asks you to send them a message or a picture."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Text content of the message (max 2000 chars; will be truncated).",
            },
            "include_picture": {
                "type": "boolean",
                "description": "If true, attach the current camera frame as a JPEG image.",
                "default": False,
            },
        },
        "required": ["message"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Post the message (and optional camera frame) to the configured Discord webhook."""
        webhook_url = (config.DISCORD_WEBHOOK_URL or "").strip()
        if not webhook_url:
            logger.warning("send_discord: DISCORD_WEBHOOK_URL not configured")
            return {"status": "error", "reason": "Discord webhook URL not configured"}

        message = (kwargs.get("message") or "").strip()
        if not message:
            return {"status": "error", "reason": "message must be a non-empty string"}
        message = message[:_MAX_DISCORD_CONTENT_LEN]

        include_picture = bool(kwargs.get("include_picture", False))
        jpeg_bytes: bytes | None = None
        picture_skipped_reason: str | None = None

        if include_picture:
            jpeg_bytes, picture_skipped_reason = _capture_jpeg(deps)

        logger.info(
            "Tool call: send_discord len(message)=%d include_picture=%s sent_picture=%s",
            len(message),
            include_picture,
            jpeg_bytes is not None,
        )

        # Deferred import: httpx ships transitively via openai; mirrors console.py.
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if jpeg_bytes is not None:
                    files = {"files[0]": ("reachy_view.jpg", jpeg_bytes, "image/jpeg")}
                    data = {"payload_json": json.dumps({"content": message})}
                    response = await client.post(webhook_url, data=data, files=files)
                else:
                    response = await client.post(webhook_url, json={"content": message})
        except httpx.HTTPError as exc:
            logger.exception("send_discord: HTTP request failed")
            return {"status": "error", "reason": f"HTTP error: {exc}"}

        if response.status_code in (200, 204):
            result: Dict[str, Any] = {
                "status": "sent",
                "included_picture": jpeg_bytes is not None,
            }
            if picture_skipped_reason is not None:
                result["picture_skipped_reason"] = picture_skipped_reason
            return result

        if response.status_code == 429:
            retry_after: Any = None
            try:
                retry_after = response.json().get("retry_after")
            except Exception:
                pass
            return {"status": "error", "reason": "rate limited", "retry_after": retry_after}

        return {
            "status": "error",
            "reason": f"Discord returned HTTP {response.status_code}: {response.text[:200]}",
        }


def _capture_jpeg(deps: ToolDependencies) -> tuple[bytes | None, str | None]:
    """Grab the latest camera frame and JPEG-encode it; return (bytes, skip_reason)."""
    if deps.camera_worker is None:
        return None, "camera worker not available"
    frame = deps.camera_worker.get_latest_frame()
    if frame is None:
        return None, "no camera frame available"
    try:
        return encode_bgr_frame_as_jpeg(frame), None
    except RuntimeError as exc:
        return None, f"failed to encode frame as JPEG: {exc}"
