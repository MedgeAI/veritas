"""Centralized logging configuration for the Veritas web backend.

Usage::

    from .logging_config import configure_logging

    configure_logging()  # called once at app startup

Reads ``VERITAS_LOG_LEVEL`` from the environment (default ``INFO``).
Logs are written to stderr and to a rotating file at
``/app/logs/veritas.log`` (or ``VERITAS_LOG_DIR`` override).
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_CONFIGURED = False

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5


def configure_logging(level: str | None = None) -> None:
    """Attach stderr and rotating-file handlers to the ``veritas`` root logger.

    Safe to call multiple times — only the first call has effect.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger("veritas")

    effective_level = (
        level or os.environ.get("VERITAS_LOG_LEVEL", "INFO")
    ).upper()
    root.setLevel(getattr(logging, effective_level, logging.INFO))

    formatter = logging.Formatter(_LOG_FORMAT)

    # --- Stream handler (stderr) ---
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # --- Rotating file handler ---
    log_dir = os.environ.get("VERITAS_LOG_DIR", "/app/logs")
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
        # If we cannot write to the log directory (e.g. read-only container),
        # degrade gracefully — stderr is still available.
        root.warning(
            "veritas.logging: unable to write log file to %s, "
            "falling back to stderr only",
            log_dir,
        )
