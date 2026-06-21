"""Database engine, session factory, and FastAPI dependencies."""

from __future__ import annotations

import logging
import os
from typing import Any, Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all Veritas models."""


logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """Return the configured database URL.

    Web data must use PostgreSQL-compatible semantics.  Docker deployments set
    ``VERITAS_DATABASE_URL``.  Local development can opt into an in-memory
    PGlite socket server with ``VERITAS_ENABLE_PGLITE=1``.
    """
    env_url = os.environ.get("VERITAS_DATABASE_URL")
    if env_url:
        return env_url
    if os.environ.get("VERITAS_ENABLE_PGLITE") == "1":
        from .pglite import get_or_start_pglite_server

        os.environ.setdefault("VERITAS_DATABASE_BACKEND", "pglite")
        return get_or_start_pglite_server().database_url
    raise RuntimeError(
        "VERITAS_DATABASE_URL is required for the Web data layer. "
        "For local development, set VERITAS_ENABLE_PGLITE=1 to use "
        "an in-memory PGlite PostgreSQL-compatible server."
    )


def create_db_engine(database_url: str | None = None, **kwargs: Any) -> Engine:
    """Create a SQLAlchemy engine with connection pooling.

    Args:
        database_url: PostgreSQL-compatible connection string. Falls back to
            ``VERITAS_DATABASE_URL`` or opt-in PGlite, never SQLite files.
        **kwargs: Extra keyword arguments forwarded to
            :func:`sqlalchemy.create_engine`.
    """
    url = database_url or get_database_url()
    defaults: dict[str, Any] = {
        "pool_pre_ping": True,
    }
    backend = os.environ.get("VERITAS_DATABASE_BACKEND", "").lower()
    # SQLite is still supported when passed explicitly by legacy helpers, but
    # it is no longer used as the implicit Web data fallback.
    if url.startswith("sqlite"):
        defaults["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url == "sqlite://":
            from sqlalchemy.pool import StaticPool

            defaults["poolclass"] = StaticPool
    elif backend != "pglite":
        defaults["pool_size"] = 5
        defaults["max_overflow"] = 10
    if backend == "pglite":
        defaults["pool_size"] = 5
        defaults["max_overflow"] = 5
    defaults.update(kwargs)
    engine = create_engine(url, **defaults)

    if not url.startswith("sqlite") and backend != "pglite":

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

    backend = os.environ.get("VERITAS_DATABASE_BACKEND", "").lower()
    if not str(engine.url).startswith("sqlite") and backend != "pglite":
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
