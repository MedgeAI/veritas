"""Centralized logging for the Veritas engine/CLI.

Usage::

    from engine._logging import get_logger, configure_logging

    # In CLI entry point (once at startup):
    configure_logging("DEBUG")

    # In each module:
    logger = get_logger(__name__)
    logger.info("progress message")

The ``configure_logging`` call attaches a stderr handler to the **root**
logger so that all ``logging.getLogger(__name__)`` calls propagate correctly.
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "[%(asctime)s] %(name)-40s %(levelname)-7s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module name.

    Since the root logger is configured at startup, all loggers propagate
    through the same handler. No namespace prefixing needed.
    """
    return logging.getLogger(name)


def configure_logging(level: str = "INFO") -> None:
    """Attach a stderr handler to the **root** logger.

    Call once at CLI startup. Subsequent calls are no-ops.
    """
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%H:%M:%S"))
    effective = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(effective)
    root.addHandler(handler)
