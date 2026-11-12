"""Logging setup: every move is written to a log file with source, destination and time."""

from __future__ import annotations

import logging
from pathlib import Path

LOGGER_NAME = "smart_organizer"
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_file: Path, console: bool = False, level: int = logging.INFO) -> logging.Logger:
    """Configure the application logger. Safe to call more than once."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(message)s"))
        stream.setLevel(logging.WARNING)  # the CLI prints its own progress
        logger.addHandler(stream)

    return logger
