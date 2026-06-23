"""Compile .rmscript files into zero-argument, LLM-callable tools.

Each ``<tool_name>.rmscript`` in the shared library is compiled at load time into
a ``RmscriptTool`` subclass whose description is the script's first-line string.
Running the tool queues the compiled moves on the MovementManager in order,
holding pose during ``wait``, capturing pictures, and playing sounds. Because
moves are queued (not driven live), each move's start is threaded from the
previous move's target; async sleeps keep pictures/sounds aligned with the
motion timeline, so the tool blocks for the script's total duration.
"""

from __future__ import annotations
import base64
import asyncio
import logging
from typing import Any, Dict, List, Tuple, ClassVar

import numpy.typing as npt
from rmscript import (
    IRAction,
    IRWaitAction,
    IRPictureAction,
    IRPlaySoundAction,
    compile_script,
)

from reachy_mini_conversation_app.tools.core_tools import Tool, ToolDependencies
from reachy_mini_conversation_app.dance_emotion_moves import GotoQueueMove
from reachy_mini_conversation_app.camera_frame_encoding import encode_bgr_frame_as_jpeg


logger = logging.getLogger(__name__)

Antennas = Tuple[float, float]


class RmscriptTool(Tool):
    """A conversation tool whose behavior is defined by a compiled .rmscript file."""

    _auto_register: ClassVar[bool] = False
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    # Populated per subclass by make_rmscript_tool_class().
    _ir: ClassVar[List[Any]] = []

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> Dict[str, Any]:
        """Queue the compiled moves in order, capturing pictures and playing sounds."""
        mini = deps.reachy_mini
        head: npt.NDArray[Any] = mini.get_current_head_pose()
        head_joints, antenna_joints = mini.get_current_joint_positions()
        antennas: Antennas = (antenna_joints[0], antenna_joints[1])  # [right, left]
        body_yaw: float = head_joints[0]
        images: List[str] = []

        for action in self._ir:
            if isinstance(action, IRAction):
                head, antennas, body_yaw = self._queue_action(deps, action, head, antennas, body_yaw)
                await asyncio.sleep(action.duration)
            elif isinstance(action, IRWaitAction):
                self._queue_move(deps, head, antennas, body_yaw, action.duration)
                await asyncio.sleep(action.duration)
            elif isinstance(action, IRPictureAction):
                image = self._capture(deps)
                if image is not None:
                    images.append(image)
            elif isinstance(action, IRPlaySoundAction):
                mini.media.play_sound(action.sound_name)
                if action.blocking and action.duration:
                    await asyncio.sleep(action.duration)

        result: Dict[str, Any] = {"status": f"ran {self.name}"}
        if images:
            result["b64_im"] = images[-1]
        return result

    def _queue_action(
        self,
        deps: ToolDependencies,
        action: IRAction,
        head: npt.NDArray[Any],
        antennas: Antennas,
        body_yaw: float,
    ) -> Tuple[npt.NDArray[Any], Antennas, float]:
        """Queue one movement, threading the previous target as the start state."""
        target_head = action.head_pose if action.head_pose is not None else head
        if action.antennas is None:
            target_antennas = antennas
        else:
            # Per-element None means "leave that antenna in place".
            target_antennas = (
                antennas[0] if action.antennas[0] is None else action.antennas[0],
                antennas[1] if action.antennas[1] is None else action.antennas[1],
            )
        target_body_yaw = action.body_yaw if action.body_yaw is not None else body_yaw
        self._queue_move(
            deps,
            target_head,
            target_antennas,
            target_body_yaw,
            action.duration,
            start_head=head,
            start_antennas=antennas,
            start_body_yaw=body_yaw,
        )
        return target_head, target_antennas, target_body_yaw

    def _queue_move(
        self,
        deps: ToolDependencies,
        head: npt.NDArray[Any],
        antennas: Antennas,
        body_yaw: float,
        duration: float,
        start_head: npt.NDArray[Any] | None = None,
        start_antennas: Antennas | None = None,
        start_body_yaw: float | None = None,
    ) -> None:
        """Enqueue a GotoQueueMove; defaults make it a hold (start == target)."""
        deps.movement_manager.queue_move(
            GotoQueueMove(
                target_head_pose=head,
                start_head_pose=start_head if start_head is not None else head,
                target_antennas=antennas,
                start_antennas=start_antennas if start_antennas is not None else antennas,
                target_body_yaw=body_yaw,
                start_body_yaw=start_body_yaw if start_body_yaw is not None else body_yaw,
                duration=duration,
            )
        )

    def _capture(self, deps: ToolDependencies) -> str | None:
        """Grab the latest camera frame as base64 JPEG, or None if unavailable."""
        if deps.camera_worker is None:
            logger.warning("rmscript picture skipped: no camera worker")
            return None
        frame = deps.camera_worker.get_latest_frame()
        if frame is None:
            logger.warning("rmscript picture skipped: no frame available")
            return None
        return base64.b64encode(encode_bgr_frame_as_jpeg(frame)).decode("utf-8")


def make_rmscript_tool_class(source: str, tool_name: str) -> type[RmscriptTool] | None:
    """Compile `source` into a zero-argument RmscriptTool subclass, or None on error."""
    result = compile_script(source)
    if not result.success:
        for err in result.errors:
            logger.error("rmscript tool '%s' line %s: %s", tool_name, err.line, err.message)
        return None
    for warning in result.warnings:
        logger.warning("rmscript tool '%s' line %s: %s", tool_name, warning.line, warning.message)
    description = result.description or f"Run the {tool_name} behavior."
    return type(
        f"RmscriptTool_{tool_name}",
        (RmscriptTool,),
        {
            "name": tool_name,
            "description": description,
            "_ir": result.ir,
        },
    )


def queue_rmscript(source: str, deps: ToolDependencies) -> Dict[str, Any]:
    """Compile an rmscript and queue its moves for fire-and-forget preview.

    Clears the movement queue, then enqueues every move up front; the movement
    worker plays them back-to-back honoring each duration, so no host-side pacing
    is needed. Pictures and sounds are skipped (there is no timeline to align
    them to). Returns ``{"ok": True, "duration": <seconds>}`` or, on a compile
    failure, ``{"ok": False, "error": "compile_failed"}`` without touching the robot.
    """
    cls = make_rmscript_tool_class(source, "preview")
    if cls is None:
        return {"ok": False, "error": "compile_failed"}

    mini = deps.reachy_mini
    head: npt.NDArray[Any] = mini.get_current_head_pose()
    head_joints, antenna_joints = mini.get_current_joint_positions()
    antennas: Antennas = (antenna_joints[0], antenna_joints[1])  # [right, left]
    body_yaw: float = head_joints[0]

    tool = cls()
    deps.movement_manager.clear_move_queue()
    total = 0.0
    for action in cls._ir:
        if isinstance(action, IRAction):
            head, antennas, body_yaw = tool._queue_action(deps, action, head, antennas, body_yaw)
            total += action.duration
        elif isinstance(action, IRWaitAction):
            tool._queue_move(deps, head, antennas, body_yaw, action.duration)
            total += action.duration
    return {"ok": True, "duration": total}
