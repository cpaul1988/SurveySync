from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def configure_logging(log_dir: Path) -> logging.Logger:
    """Configure application logging once.

    A daily rotating UTF-8 log is kept for 14 days. Console logging remains enabled for the
    browser/debug launcher. Calling this function repeatedly is safe.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("fieldbook_sync")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if getattr(logger, "_fbs_configured", False):
        return logger

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = TimedRotatingFileHandler(
        log_dir / "fieldbook_sync.log",
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    console.setLevel(logging.INFO)
    logger.addHandler(console)

    logger._fbs_configured = True  # type: ignore[attr-defined]
    logger.info("Logging initialized at %s", log_dir)
    return logger
