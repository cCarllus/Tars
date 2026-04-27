"""Central logging configuration for the bot."""

import logging
import sys

from bot.config import settings


def configure_logging() -> None:
    """Configure application-wide logging."""

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


logger = logging.getLogger("tars")
