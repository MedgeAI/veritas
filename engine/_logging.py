"""Centralized logging configuration for the Veritas project.

Usage::

    from engine._logging import get_logger, configure_logging

    # In CLI entry point (once at startup):
    configure_logging("INFO")

    # In each module:
    logger = get_logger(__name__)
    logger.info("progress message")
"""

from __future__ import annotations

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under the ``veritas`` hierarchy.

    If *name* starts with ``engine.``, ``cli.`` or ``runtime.`` the prefix is
    kept so log records identify the originating subsystem.
    """
    # Avoid double-prefixing when called as get_logger("veritas.x")
    if name.startswith("veritas."):
        return logging.getLogger(name)
    return logging.getLogger(f"veritas.{name}")


def configure_logging(level: str = "INFO") -> None:
    """Attach a stderr handler to the ``veritas`` root logger.

    Call once at CLI startup.  Subsequent calls are harmless (a duplicate
    handler would be added, but Python's logging module de-duplicates by
    identity when using ``basicConfig``; here we guard explicitly).
    """
    root = logging.getLogger("veritas")
    # Guard against duplicate handlers on repeated calls.
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(name)s %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(handler)
