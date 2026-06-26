"""Centralized logging configuration for the Veritas project.

Usage::

    from veritas_web.logging_config import configure_logging

    configure_logging()  # called once at app startup

Reads ``VERITAS_LOG_LEVEL`` from the environment (default ``INFO`` in prod,
``DEBUG`` in dev when VERITAS_DEV=1).
Logs are written to stderr and optionally to a rotating file at
``$VERITAS_LOG_DIR/veritas.log`` (default ``logs/`` repo-relative,
``/app/logs`` in Docker).
"""

from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

from engine.env import get_env

_CONFIGURED = False

_LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5

# HTTP paths that represent frontend polling — noisy at INFO during audit runs.
POLLING_PATHS: tuple[str, ...] = (
    "/api/runs",
    "/api/events",
    "/api/artifacts",
)
_POLLING_PATH_RE = re.compile(
    "|".join(re.escape(p) for p in POLLING_PATHS)
)

# Slow-request threshold (ms). Polling requests slower than this are still
# logged at INFO because they may indicate a real problem.
SLOW_REQUEST_THRESHOLD_MS = 5000


class PollingRequestFilter(logging.Filter):
    """Suppress INFO-level log records for frontend polling requests.

    Polling endpoints (``/api/runs``, ``/api/events``, ``/api/artifacts``)
    are called repeatedly by the frontend during an audit run. Each call
    generates an INFO-level access log line that drowns out meaningful
    progress messages. This filter drops those records.

    Errors (level >= WARNING) and slow requests (>5s) are always kept so
    that real problems remain visible at INFO.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Keep errors and warnings unconditionally.
        if record.levelno >= logging.WARNING:
            return True
        # Keep slow requests (message typically contains duration).
        msg = record.getMessage()
        # Match patterns like "GET /api/runs/xxx → 200 (5234.1ms)"
        match = re.search(r"\((\d+(?:\.\d+)?)ms\)", msg)
        if match and float(match.group(1)) > SLOW_REQUEST_THRESHOLD_MS:
            return True
        # Drop if message references a polling path.
        if _POLLING_PATH_RE.search(msg):
            return False
        return True


class DuplicateDBConnectFilter(logging.Filter):
    """Suppress repeated 'Database connecting' INFO messages.

    SQLAlchemy connection pool may emit "Database connecting" messages
    each time a new connection is established. Only the first occurrence
    per process lifetime is logged at INFO; subsequent ones are dropped.

    The filter is stateful (class-level) — resetting requires calling
    :meth:`reset`.
    """

    _first_seen: bool = True

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        msg = record.getMessage()
        if "Database connecting" in msg:
            if DuplicateDBConnectFilter._first_seen:
                DuplicateDBConnectFilter._first_seen = False
                return True
            return False
        return True

    @classmethod
    def reset(cls) -> None:
        """Reset the first-seen flag. Primarily for testing."""
        cls._first_seen = True


def is_polling_path(path: str) -> bool:
    """Return True if *path* matches a known polling endpoint."""
    return bool(_POLLING_PATH_RE.search(path))

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
    is_dev = get_env("VERITAS_DEV", required=False, default="").strip() in (
        "1", "true", "yes"
    )
    effective_level = (
        level
        or get_env(
            "VERITAS_LOG_LEVEL",
            required=False,
            default="DEBUG" if is_dev else "INFO",
        )
    ).upper()

    root = logging.getLogger()  # ROOT logger — catches all module loggers
    root.setLevel(getattr(logging, effective_level, logging.INFO))

    formatter = logging.Formatter(_LOG_FORMAT)

    # --- Stream handler (stderr) ---
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # --- Rotating file handler (optional) ---
    log_dir = get_env("VERITAS_LOG_DIR", required=False, default="logs/")
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

    # --- Install noise-reduction filters ---
    # DuplicateDBConnectFilter on root catches all "Database connecting" repeats
    # regardless of which module emits them.
    root.addFilter(DuplicateDBConnectFilter())
    # PollingRequestFilter on the app logger catches access-log records.
    logging.getLogger("veritas_web.app").addFilter(PollingRequestFilter())


def redact_dsn(dsn: str) -> str:
    """Redact database DSN for safe logging.

    Parses the DSN and returns a formatted string with password replaced
    by '***'. Handles missing password, missing components, and query params.

    Args:
        dsn: Database connection string (e.g., postgresql://user:pass@host:5432/db)

    Returns:
        Redacted string: 'Database configured: env=<env> user=<user> host=<host> port=<port> db=<db> password=***'
    """
    if not dsn:
        return "Database configured: env=unknown user=unknown host=unknown port=unknown db=unknown password=***"

    try:
        parsed = urlparse(dsn)

        # Extract components with sensible defaults
        scheme = parsed.scheme or "unknown"
        user = parsed.username or "unknown"
        host = parsed.hostname or "unknown"
        port = str(parsed.port) if parsed.port else "unknown"
        db = parsed.path.lstrip("/") if parsed.path else "unknown"

        return f"Database configured: env={scheme} user={user} host={host} port={port} db={db} password=***"
    except Exception:
        # If parsing fails for any reason, return a safe fallback
        return "Database configured: env=unknown user=unknown host=unknown port=unknown db=unknown password=***"
