"""Personalities: named parameter sets that make the same engine feel like different characters."""

from dataclasses import field, dataclass

from reachy_buddy.core.drives import Drives


@dataclass
class Personality:
    """Tunables for one character: drive baselines, behavioral thresholds, cadence, and voice style."""

    name: str = "default"
    baseline: Drives = field(default_factory=Drives)
    chattiness: float = 0.5
    ask_threshold: float = 0.8
    joke_threshold: float = 0.75
    quiet_confidence: float = 0.3
    quiet_social_energy: float = 0.2
    speak_cooldown_s: float = 45.0
    monologue_cadence_s: tuple[float, float] = (10.0, 20.0)
    style_hint: str = "warm, observational"


PERSONALITIES: dict[str, Personality] = {
    "default": Personality(),
    "noir_detective": Personality(
        name="noir_detective",
        baseline=Drives(curiosity=0.85, social_energy=0.4, playfulness=0.3, focus=0.7),
        chattiness=0.4,
        speak_cooldown_s=90.0,
        style_hint="hard-boiled, observational",
    ),
}
