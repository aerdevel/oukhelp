import logging

from core.config import settings


def setup_logger():
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        force=True,
    )