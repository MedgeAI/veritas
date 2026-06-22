from __future__ import annotations

from pathlib import Path

import pytest


WEB_DB_TEST_PATHS = (
    "tests/unit/test_case_isolation.py",
    "tests/unit/test_cbir_upload.py",
    "tests/unit/test_stale_recovery.py",
    "tests/unit/test_web_",
    "tests/integration/test_auth_flow.py",
    "tests/e2e/test_cbir_provenance.py",
)


def _uses_web_database(node_path: str) -> bool:
    normalized = node_path.replace("\\", "/")
    return any(marker in normalized for marker in WEB_DB_TEST_PATHS)


@pytest.fixture(scope="session")
def pglite_server():
    from web.backend.veritas_web.pglite import start_pglite_server

    # Increase max_connections to handle 140+ web tests
    server = start_pglite_server(max_connections=64)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture(autouse=True)
def web_database_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    if not _uses_web_database(str(Path(request.node.fspath))):
        yield
        return

    server = request.getfixturevalue("pglite_server")
    monkeypatch.setenv("VERITAS_DATABASE_URL", server.database_url)
    monkeypatch.setenv("VERITAS_DATABASE_BACKEND", "pglite")

    from web.backend.veritas_web import models as _models  # noqa: F401
    from web.backend.veritas_web.database import Base, create_db_engine

    # Use pool_size=0, max_overflow=0 to avoid connection accumulation across 140+ tests
    # Connections are returned to PGlite immediately after each operation
    engine = create_db_engine(server.database_url, pool_size=0, max_overflow=0)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    try:
        yield
    finally:
        engine = create_db_engine(server.database_url, pool_size=0, max_overflow=0)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
