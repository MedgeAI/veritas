"""Centralized logging configuration for the Veritas project.

Usage::

    from veritas_web.logging_config import configure_logging

    configure_logging()  # called once at app startup

Reads ``VERITAS_LOG_LEVEL`` from the environment (default ``INFO`` in prod,
``DEBUG`` in dev when VERITAS_DEV=1).
Logs are written to stderr and optionally to a rotating file at
``$VERITAS_LOG_DIR/veritas.log`` (default ``/app/logs``).
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_CONFIGURED = False

_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5

# Noisy third-party loggers to quieten.
_QUIET_LOGGERS = {
    "uvicorn.access": logging.WARNING,
    "uvicorn.error": logging.INFO,
    "sqlalchemy.engine": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "multipart": logging.WARNING,
    "watchfiles": logging.WARNING,
}


def configure_logging(level: str | None = None) -> None:
    """Attach stderr and rotating-file handlers to the **root** logger.

    Configuring the root logger (``""``) ensures that all modules using
    ``logging.getLogger(__name__)`` — e.g. ``engine.static_audit.pipeline`` —
    propagate their messages through the configured handlers.

    Safe to call multiple times — only the first call has effect.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    # Default to DEBUG in dev, INFO in prod.
    is_dev = os.environ.get("VERITAS_DEV", "").strip() in ("1", "true", "yes")
    effective_level = (
        level or os.environ.get("VERITAS_LOG_LEVEL", "DEBUG" if is_dev else "INFO")
    ).upper()

    root = logging.getLogger()  # ROOT logger — catches all module loggers
    root.setLevel(getattr(logging, effective_level, logging.INFO))

    formatter = logging.Formatter(_LOG_FORMAT)

    # --- Stream handler (stderr) ---
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # --- Rotating file handler (optional) ---
    log_dir = os.environ.get("VERITAS_LOG_DIR", "")
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            file_handler = RotatingFileHandler(
                os.path.join(log_dir, "veritas.log"),
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            root.warning(
                "veritas.logging: unable to write log file to %s, "
                "falling back to stderr only",
                log_dir,
            )

    # --- Quiet noisy third-party loggers ---
    for name, lvl in _QUIET_LOGGERS.items():
        logging.getLogger(name).setLevel(lvl)
