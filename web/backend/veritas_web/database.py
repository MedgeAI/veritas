"""PostgreSQL database engine, session factory, and FastAPI dependencies."""

from __future__ import annotations

import logging
import os
from typing import Any, Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all Veritas models."""


DEFAULT_DATABASE_URL = "postgresql://veritas:veritas@127.0.0.1:5432/veritas"
logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """Return the database URL from environment or default."""
    return os.environ.get("VERITAS_DATABASE_URL", DEFAULT_DATABASE_URL)


def create_db_engine(database_url: str | None = None, **kwargs: Any) -> Engine:
    """Create a SQLAlchemy engine with connection pooling.

    Args:
        database_url: PostgreSQL connection string.  Falls back to
            ``VERITAS_DATABASE_URL`` env var or a local default.
        **kwargs: Extra keyword arguments forwarded to
            :func:`sqlalchemy.create_engine`.
    """
    url = database_url or get_database_url()
    defaults: dict[str, Any] = {
        "pool_pre_ping": True,
    }
    # SQLite doesn't support pool_size/max_overflow
    if not url.startswith("sqlite"):
        defaults["pool_size"] = 5
        defaults["max_overflow"] = 10
    defaults.update(kwargs)
    engine = create_engine(url, **defaults)

    if not url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _register_vector_extension(dbapi_connection: Any, _connection_record: Any) -> None:
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

    This is intended for development bootstrapping.  Production deployments
    should use Alembic migrations once the schema stabilises.
    """
    if engine is None:
        engine = create_db_engine()

    if not str(engine.url).startswith("sqlite"):
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
