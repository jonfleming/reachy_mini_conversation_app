"""Entry point and composition root for the Reachy Desktop Buddy."""

import logging
from dataclasses import replace, dataclass

from reachy_buddy.core.drives import Drives
from reachy_buddy.animation.gaze import GazeController
from reachy_buddy.core.curiosity import CuriosityEngine
from reachy_buddy.core.monologue import ThoughtStream
from reachy_buddy.vision.presence import PresenceTracker
from reachy_buddy.core.personality import PERSONALITIES, Personality
from reachy_buddy.core.world_model import WorldModel
from reachy_buddy.conversation.flow import ConversationFlow
from reachy_buddy.core.emotional_state import EmotionalState
from reachy_buddy.vision.face_tracking import FaceTracker, ensure_face_landmarker_model


logger = logging.getLogger(__name__)


@dataclass
class BuddyContext:
    """The buddy's long-lived subsystems, built once at startup."""

    world_model: WorldModel
    curiosity: CuriosityEngine
    mood: EmotionalState
    flow: ConversationFlow
    gaze: GazeController
    presence: PresenceTracker
    personality: Personality
    drives: Drives
    thoughts: ThoughtStream


def main() -> None:
    """Build the buddy context and report readiness; loops land in follow-up tasks."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    personality = PERSONALITIES["default"]
    context = BuddyContext(
        world_model=WorldModel(),
        curiosity=CuriosityEngine(personality=personality),
        mood=EmotionalState(),
        flow=ConversationFlow(),
        gaze=GazeController(),
        presence=PresenceTracker(FaceTracker(ensure_face_landmarker_model())),
        personality=personality,
        drives=replace(personality.baseline),
        thoughts=ThoughtStream(personality=personality),
    )
    logger.info("Reachy Desktop Buddy ready with %s personality: %s", personality.name, list(vars(context)))
    logger.info("Presence and gaze loops attach to camera and robot handles in the integration task.")


if __name__ == "__main__":
    main()
