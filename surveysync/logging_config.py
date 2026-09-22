from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def configure_logging(log_dir: Path) -> logging.Logger:
    """Configure persistent SurveySync core logging once.

    Module loggers use names under ``surveysync.*`` and propagate to this
    parent logger. Logs rotate daily and are retained for 14 days so failures
    that were formerly swallowed by broad exception handlers can be diagnosed
    from support bundles without filling the user's disk indefinitely.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("surveysync")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if getattr(logger, "_surveysync_configured", False):
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = TimedRotatingFileHandler(
        log_dir / "surveysync.log",
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.WARNING)
    console.setFormatter(formatter)
    logger.addHandler(console)

    logger._surveysync_configured = True  # type: ignore[attr-defined]
    logger.info("SurveySync core logging initialized at %s", log_dir)
    return logger
