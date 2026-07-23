"""Gesture library: named, communicative motion programs for head and antennas."""

from collections.abc import Callable

from reachy_buddy.animation.pose import BodyPose
from reachy_buddy.animation.program import PoseKeyframe, GestureProgram


# Antenna conventions (radians): positive perks both, negative droops both, 0 is mid.
_PERK = 0.6
_MID_PERK = 0.35
_RELAXED = -0.1745
_DROOP = -0.55


def _key(yaw: float, pitch: float, roll: float, antenna: float, duration: float) -> PoseKeyframe:
    """Build a keyframe with mirrored antennas (positive value perks both)."""
    return PoseKeyframe(
        BodyPose(yaw=yaw, pitch=pitch, roll=roll, antenna_left=antenna, antenna_right=-antenna), duration
    )


def _rest(duration: float) -> PoseKeyframe:
    """Build a return-to-neutral keyframe."""
    return PoseKeyframe(BodyPose(), duration)


class GestureLibrary:
    """Builds the buddy's named gestures as pure keyframe programs."""

    def __init__(self) -> None:
        """Register the self-contained gestures that take no aim parameters."""
        self._simple: dict[str, Callable[[], GestureProgram]] = {
            "nod": self.nod,
            "shake": self.shake,
            "look_up_recall": self.look_up_recall,
            "tilt_uncertain": self.tilt_uncertain,
            "lean_interested": self.lean_interested,
            "antenna_twitch": self.antenna_twitch,
            "scan": self.scan,
            "glance_down": self.glance_down,
            "perk_up": self.perk_up,
            "droop": self.droop,
        }

    def names(self) -> list[str]:
        """Return every gesture name the library can build."""
        return sorted([*self._simple, "turn_to_sound", "look_at_object", "glance_reaction"])

    def build(self, name: str, yaw_degrees: float = 0.0, pitch_degrees: float = 0.0) -> GestureProgram:
        """Build a gesture by name; yaw/pitch aim the targeted gestures."""
        if name == "turn_to_sound":
            return self.turn_to_sound(yaw_degrees)
        if name == "look_at_object":
            return self.look_at_object(yaw_degrees, pitch_degrees)
        if name == "glance_reaction":
            return self.glance_reaction(yaw_degrees)
        factory = self._simple.get(name)
        if factory is None:
            raise KeyError(f"unknown gesture: {name}")
        return factory()

    def nod(self) -> GestureProgram:
        """Yes: a small down-up head bob."""
        return GestureProgram("nod", [_key(0.0, -12.0, 0.0, 0.0, 0.22), _key(0.0, 7.0, 0.0, 0.0, 0.26), _rest(0.3)])

    def shake(self) -> GestureProgram:
        """No: a small left-right head sweep."""
        return GestureProgram("shake", [_key(15.0, 0.0, 0.0, 0.0, 0.26), _key(-15.0, 0.0, 0.0, 0.0, 0.34), _rest(0.3)])

    def look_up_recall(self) -> GestureProgram:
        """Search memory: gaze up and aside, hold, then return."""
        return GestureProgram(
            "look_up_recall",
            [_key(-10.0, 22.0, 0.0, _MID_PERK - 0.05, 0.5), _key(-10.0, 22.0, 0.0, _MID_PERK - 0.05, 0.9), _rest(0.6)],
        )

    def turn_to_sound(self, yaw_degrees: float) -> GestureProgram:
        """Orient toward a sound with a small overshoot; ends facing the source."""
        return GestureProgram(
            "turn_to_sound",
            [_key(yaw_degrees * 1.08, 2.0, 0.0, _PERK, 0.3), _key(yaw_degrees, 0.0, 0.0, _PERK, 0.5)],
        )

    def tilt_uncertain(self) -> GestureProgram:
        """Uncertainty: a slow head tilt with one antenna raised, hold, then release."""
        uncertain = BodyPose(yaw=0.0, pitch=-2.0, roll=14.0, antenna_left=_MID_PERK, antenna_right=0.05)
        return GestureProgram(
            "tilt_uncertain", [PoseKeyframe(uncertain, 0.55), PoseKeyframe(uncertain, 0.8), _rest(0.6)]
        )

    def lean_interested(self) -> GestureProgram:
        """Interest: tip forward toward the speaker with perked antennas, then settle back."""
        return GestureProgram(
            "lean_interested",
            [_key(0.0, -12.0, 0.0, _PERK - 0.1, 0.45), _key(0.0, -12.0, 0.0, _PERK - 0.1, 0.9), _rest(0.55)],
        )

    def antenna_twitch(self) -> GestureProgram:
        """Excitement: rapid antenna oscillations around a perked pose with the head lifted."""
        keyframes = []
        for _ in range(3):
            keyframes.append(_key(0.0, 4.0, 0.0, _PERK + 0.25, 0.08))
            keyframes.append(_key(0.0, 4.0, 0.0, _PERK - 0.2, 0.11))
        keyframes.append(_key(0.0, 4.0, 0.0, _PERK, 0.12))
        keyframes.append(_rest(0.35))
        return GestureProgram("antenna_twitch", keyframes)

    def look_at_object(self, yaw_degrees: float, pitch_degrees: float) -> GestureProgram:
        """Look at a thing before mentioning it; ends holding the object in view."""
        return GestureProgram(
            "look_at_object",
            [
                _key(yaw_degrees, pitch_degrees, 0.0, _MID_PERK, 0.45),
                _key(yaw_degrees, pitch_degrees, 0.0, _MID_PERK, 0.7),
            ],
        )

    def glance_reaction(self, yaw_degrees: float) -> GestureProgram:
        """Gauge a reaction: quick glance to the user, reading them, staying engaged."""
        reading = BodyPose(yaw=yaw_degrees, pitch=0.0, roll=5.0, antenna_left=0.45, antenna_right=-0.45)
        settling = BodyPose(yaw=yaw_degrees, pitch=0.0, roll=0.0, antenna_left=0.2, antenna_right=-0.2)
        return GestureProgram(
            "glance_reaction", [PoseKeyframe(reading, 0.28), PoseKeyframe(reading, 0.55), PoseKeyframe(settling, 0.35)]
        )

    def scan(self) -> GestureProgram:
        """Idle: a slow look around the room."""
        return GestureProgram(
            "scan", [_key(28.0, 2.0, 0.0, _RELAXED, 0.7), _key(-28.0, 2.0, 0.0, _RELAXED, 1.1), _rest(0.7)]
        )

    def glance_down(self) -> GestureProgram:
        """Idle: a brief thoughtful downward glance."""
        return GestureProgram(
            "glance_down",
            [_key(0.0, -16.0, 0.0, -0.3, 0.5), _key(0.0, -16.0, 0.0, -0.3, 0.5), _rest(0.55)],
        )

    def perk_up(self) -> GestureProgram:
        """Idle: a quick attention lift, antennas perking, then relax."""
        return GestureProgram(
            "perk_up", [_key(0.0, 6.0, 0.0, _PERK, 0.35), _key(0.0, 6.0, 0.0, _PERK, 0.45), _rest(0.45)]
        )

    def droop(self) -> GestureProgram:
        """Idle: a sleepy sag of head and antennas, then a slow recovery."""
        return GestureProgram(
            "droop",
            [_key(0.0, -10.0, 0.0, _DROOP, 0.9), _key(0.0, -10.0, 0.0, _DROOP, 0.8), _rest(0.8)],
        )
