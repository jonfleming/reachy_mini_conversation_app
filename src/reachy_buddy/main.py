"""CLI hint: the desktop buddy runs inside the conversation app."""

import logging

from reachy_buddy.runtime_config import BuddyRuntimeConfig


logger = logging.getLogger(__name__)


def main() -> None:
    """Print how to enable the buddy sidecar in the conversation app."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    runtime = BuddyRuntimeConfig.from_env()
    logger.info(
        "This vision sidecar runs inside reachy-desktop-buddy. "
        "Set BUDDY_ENABLED=1 (currently %s) and launch the conversation app.",
        runtime.enabled,
    )


if __name__ == "__main__":
    main()
