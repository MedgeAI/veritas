"""Database engine, session factory, and FastAPI dependencies."""

from __future__ import annotations

import logging
import os
from typing import Any, Generator
from urllib.parse import urlparse

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all Veritas models."""


logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """Return the configured database URL.

    Resolution order:

    1. ``VERITAS_DATABASE_URL`` environment variable (mandatory).
    2. Raises :class:`RuntimeError` if not set — no silent fallback.

    Raises:
        RuntimeError: If ``VERITAS_DATABASE_URL`` is not set or the resolved
            URL is not PostgreSQL-compatible.
    """
    url = os.environ.get("VERITAS_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "VERITAS_DATABASE_URL is not set.\n"
            "  Dev:  export VERITAS_DATABASE_URL="
            "postgresql://veritas_dev:veritas_dev_pass@localhost:5433/veritas_dev\n"
            "  Prod: set VERITAS_DATABASE_URL in deploy/.env"
        )
    if url.startswith("sqlite"):
        raise RuntimeError(
            "SQLite is not supported. Use PostgreSQL with pgvector. "
            "Set VERITAS_DATABASE_URL or run 'make db-up' for local dev."
        )
    return url


def create_db_engine(database_url: str | None = None, **kwargs: Any) -> Engine:
    """Create a SQLAlchemy engine with connection pooling.

    Args:
        database_url: PostgreSQL-compatible connection string. Falls back to
            ``VERITAS_DATABASE_URL`` or the default dev URL.
        **kwargs: Extra keyword arguments forwarded to
            :func:`sqlalchemy.create_engine`.
    """
    url = database_url or get_database_url()
    parsed = urlparse(url)
    logger.info(
        "Database connecting: host=%s port=%s db=%s user=%s",
        parsed.hostname,
        parsed.port,
        parsed.path.lstrip("/"),
        parsed.username,
    )
    defaults: dict[str, Any] = {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
    }
    defaults.update(kwargs)
    engine = create_engine(url, **defaults)

    @event.listens_for(engine, "connect")
    def _register_vector_extension(
        dbapi_connection: Any, _connection_record: Any
    ) -> None:
        """Ensure pgvector types are available on each new PostgreSQL connection."""
        cursor = None
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception as exc:
            raise RuntimeError(f"pgvector extension setup failed: {exc}") from exc
        finally:
            if cursor is not None:
                cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to *engine*."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db(engine: Engine | None = None) -> Generator[Session, None, None]:
    """FastAPI dependency: yield a DB session, auto-close on exit."""
    if engine is None:
        engine = create_db_engine()
    factory = create_session_factory(engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> None:
    """Create all tables and enable pgvector extension.

    This is intended for development bootstrapping. Production deployments
    should use Alembic migrations once the schema stabilises.
    """
    if engine is None:
        engine = create_db_engine()

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    # Import models module so all model classes register with Base.metadata
    # before create_all runs.  The import is intentional side-effect.
    from . import models as _models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def check_connection(engine: Engine | None = None) -> bool:
    """Return ``True`` if the database is reachable."""
    if engine is None:
        engine = create_db_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def check_db_or_raise(engine: Engine | None = None) -> None:
    """Verify the database is reachable at startup.

    Raises :class:`RuntimeError` with actionable guidance when the
    connection fails.  Call this once during application bootstrap so
    developers get a clear message instead of a cryptic SQLAlchemy
    error on the first request.
    """
    if engine is None:
        engine = create_db_engine()
    url = str(engine.url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError(
            f"Cannot connect to PostgreSQL at {url!r}: {exc}\n"
            "For local development, start Docker PostgreSQL first:\n"
            "  make db-up\n"
            "Or set VERITAS_DATABASE_URL to point at your database."
        ) from exc
