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

    server = start_pglite_server()
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

    engine = create_db_engine(server.database_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    try:
        yield
    finally:
        engine = create_db_engine(server.database_url)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
