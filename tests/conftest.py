from __future__ import annotations

import os
from pathlib import Path

import pytest

# Default to Docker PostgreSQL (started by ``make db-up``).
# Developers can override with VERITAS_DATABASE_URL for a different instance.
os.environ.setdefault(
    "VERITAS_DATABASE_URL",
    "postgresql://veritas_dev:veritas_dev_pass@localhost:5433/veritas_dev",
)


WEB_DB_TEST_PATHS = (
    "tests/unit/test_case_isolation.py",
    "tests/unit/test_case_delete.py",
    "tests/unit/test_stale_recovery.py",
    "tests/unit/test_web_",
    "tests/unit/test_upload_size_limit.py",
    "tests/unit/test_concurrency_limit.py",
    "tests/unit/test_metrics_endpoint.py",
    "tests/unit/test_users_api.py",
    "tests/integration/test_auth_flow.py",
)


def _uses_web_database(node_path: str) -> bool:
    normalized = node_path.replace("\\", "/")
    return any(marker in normalized for marker in WEB_DB_TEST_PATHS)


@pytest.fixture(autouse=True)
def web_database_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """Set up and tear down tables for each web database test.

    Connects to Docker PostgreSQL (``make db-up``) and creates/drops all
    tables around each test that uses the web database layer.
    """
    if not _uses_web_database(str(Path(request.node.fspath))):
        yield
        return

    from web.backend.veritas_web import models as _models  # noqa: F401
    from web.backend.veritas_web.database import Base, create_db_engine, get_database_url

    db_url = get_database_url()

    engine = create_db_engine(db_url)
    # Terminate other connections to avoid deadlocks during table drops.
    _terminate_other_connections(engine, db_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    try:
        yield
    finally:
        engine = create_db_engine(db_url)
        _terminate_other_connections(engine, db_url)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _terminate_other_connections(engine, db_url: str) -> None:
    """Terminate other connections to *db_url* to avoid drop deadlocks."""
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            db_name = str(engine.url).rsplit("/", 1)[-1].split("?")[0]
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": db_name},
            )
            conn.commit()
    except Exception:
        pass  # best-effort
