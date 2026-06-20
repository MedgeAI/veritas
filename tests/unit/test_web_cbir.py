"""Tests for CBIR search service and endpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers.asgi_client import LocalASGITestClient as TestClient
from web.backend.veritas_web.app import create_app
from web.backend.veritas_web.cbir_service import search_similar_panels
from web.backend.veritas_web.database import Base, create_db_engine, create_session_factory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """Create an in-memory SQLite session for testing."""
    engine = create_db_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = create_session_factory(engine)
    session = factory()
    yield session
    session.close()


def _insert_embedding(db, case_id, panel_id, figure_id, embedding, image_path=""):
    from web.backend.veritas_web.embeddings import _utc_now
    from web.backend.veritas_web.models import ImageEmbeddingModel

    db.add(ImageEmbeddingModel(
        case_id=case_id,
        panel_id=panel_id,
        figure_id=figure_id,
        image_path=image_path or f"panels/{panel_id}.png",
        embedding=embedding,
        indexed_at=_utc_now(),
    ))
    db.commit()


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------

class TestSearchSimilarPanels:
    def test_no_query_panel_returns_empty(self, db_session):
        result = search_similar_panels(db_session, "nonexistent")
        assert result["similar_panels"] == []
        assert result["total_candidates"] == 0

    def test_single_case_search(self, db_session):
        # P1 and P2 similar, P3 different
        _insert_embedding(db_session, "case1", "P1", "F1", [1.0, 0.0, 0.0] + [0.0] * 509)
        _insert_embedding(db_session, "case1", "P2", "F1", [0.99, 0.01, 0.0] + [0.0] * 509)
        _insert_embedding(db_session, "case1", "P3", "F2", [0.0, 0.0, 1.0] + [0.0] * 509)

        result = search_similar_panels(
            db_session, "P1", case_id="case1", threshold=0.9,
        )
        assert len(result["similar_panels"]) == 1
        assert result["similar_panels"][0]["panel_id"] == "P2"
        assert result["similar_panels"][0]["similarity"] > 0.9
        assert result["similar_panels"][0]["case_id"] == "case1"
        assert result["query_case_id"] == "case1"

    def test_cross_case_search(self, db_session):
        _insert_embedding(db_session, "case1", "P1", "F1", [1.0, 0.0, 0.0] + [0.0] * 509)
        _insert_embedding(db_session, "case2", "P2", "F1", [0.99, 0.01, 0.0] + [0.0] * 509)
        _insert_embedding(db_session, "case3", "P3", "F2", [0.0, 0.0, 1.0] + [0.0] * 509)

        # Search across all cases
        result = search_similar_panels(db_session, "P1", threshold=0.9)
        assert len(result["similar_panels"]) == 1
        assert result["similar_panels"][0]["panel_id"] == "P2"
        assert result["similar_panels"][0]["case_id"] == "case2"

    def test_top_k_limits_results(self, db_session):
        base = [1.0, 0.0, 0.0] + [0.0] * 509
        _insert_embedding(db_session, "case1", "P0", "F1", base)
        for i in range(1, 6):
            # Slightly different but above threshold
            v = [1.0 - 0.001 * i, 0.001 * i, 0.0] + [0.0] * 509
            _insert_embedding(db_session, "case1", f"P{i}", "F1", v)

        result = search_similar_panels(
            db_session, "P0", case_id="case1", top_k=3, threshold=0.5,
        )
        assert len(result["similar_panels"]) == 3
        # Results should be sorted by similarity descending
        sims = [r["similarity"] for r in result["similar_panels"]]
        assert sims == sorted(sims, reverse=True)

    def test_threshold_filters_low_similarity(self, db_session):
        _insert_embedding(db_session, "case1", "P1", "F1", [1.0, 0.0, 0.0] + [0.0] * 509)
        _insert_embedding(db_session, "case1", "P2", "F1", [0.5, 0.5, 0.0] + [0.0] * 509)

        result = search_similar_panels(
            db_session, "P1", case_id="case1", threshold=0.9,
        )
        assert len(result["similar_panels"]) == 0

    def test_label_filtering(self, db_session, tmp_path):
        _insert_embedding(db_session, "case1", "P1", "F1", [1.0, 0.0, 0.0] + [0.0] * 509)
        _insert_embedding(db_session, "case1", "P2", "F1", [0.99, 0.01, 0.0] + [0.0] * 509)
        _insert_embedding(db_session, "case1", "P3", "F2", [0.99, 0.01, 0.0] + [0.0] * 509)

        workdir = tmp_path / "workdir"
        workdir.mkdir()
        panel_doc = {
            "panels": [
                {"panel_id": "P1", "label": "a"},
                {"panel_id": "P2", "label": "b"},
                {"panel_id": "P3", "label": "western blot"},
            ],
        }
        (workdir / "panel_evidence.json").write_text(json.dumps(panel_doc))

        def resolver(cid):
            return workdir if cid == "case1" else None

        result = search_similar_panels(
            db_session,
            "P1",
            case_id="case1",
            threshold=0.9,
            label="western",
            artifact_resolver=resolver,
        )
        assert len(result["similar_panels"]) == 1
        assert result["similar_panels"][0]["panel_id"] == "P3"
        assert result["similar_panels"][0]["label"] == "western blot"


# ---------------------------------------------------------------------------
# Endpoint-level tests
# ---------------------------------------------------------------------------

def _setup_app_with_embeddings(tmp_path: Path) -> TestClient:
    """Create a test app with an in-memory DB and some embeddings."""
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url="sqlite:///:memory:",
    )
    return TestClient(app, raise_server_exceptions=False)


def _seed_embeddings(client: TestClient, tmp_path: Path) -> None:
    """Seed the in-memory DB with test embeddings via direct ORM access."""
    # The app was created with an in-memory DB; we access it through deps.
    # Since each create_app creates a new in-memory DB, we seed via the
    # app's engine directly.
    pass  # Seeding is done per-test below to avoid cross-test contamination.


def test_cbir_search_endpoint_basic(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url="sqlite:///:memory:",
    )
    Base.metadata.create_all(bind=app.state.dependencies._engine)
    client = TestClient(app, raise_server_exceptions=False)

    # Seed embeddings
    deps = app.state.dependencies
    session = deps._session_factory()
    try:
        _insert_embedding(session, "case1", "P1", "F1", [1.0, 0.0, 0.0] + [0.0] * 509)
        _insert_embedding(session, "case1", "P2", "F1", [0.99, 0.01, 0.0] + [0.0] * 509)
        _insert_embedding(session, "case1", "P3", "F2", [0.0, 0.0, 1.0] + [0.0] * 509)
    finally:
        session.close()

    resp = client.post("/api/cbir/search", json={
        "panel_id": "P1",
        "case_id": "case1",
        "threshold": 0.9,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["query_panel_id"] == "P1"
    assert data["query_case_id"] == "case1"
    assert len(data["similar_panels"]) == 1
    assert data["similar_panels"][0]["panel_id"] == "P2"
    assert data["similar_panels"][0]["similarity"] > 0.9


def test_cbir_search_cross_case(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url="sqlite:///:memory:",
    )
    Base.metadata.create_all(bind=app.state.dependencies._engine)
    client = TestClient(app, raise_server_exceptions=False)

    deps = app.state.dependencies
    session = deps._session_factory()
    try:
        _insert_embedding(session, "case1", "P1", "F1", [1.0, 0.0, 0.0] + [0.0] * 509)
        _insert_embedding(session, "case2", "P2", "F1", [0.99, 0.01, 0.0] + [0.0] * 509)
    finally:
        session.close()

    # Cross-case: no case_id specified
    resp = client.post("/api/cbir/search", json={
        "panel_id": "P1",
        "threshold": 0.9,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["similar_panels"]) == 1
    assert data["similar_panels"][0]["case_id"] == "case2"


def test_cbir_search_no_results(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url="sqlite:///:memory:",
    )
    Base.metadata.create_all(bind=app.state.dependencies._engine)
    client = TestClient(app, raise_server_exceptions=False)

    deps = app.state.dependencies
    session = deps._session_factory()
    try:
        _insert_embedding(session, "case1", "P1", "F1", [1.0, 0.0, 0.0] + [0.0] * 509)
        _insert_embedding(session, "case1", "P2", "F1", [0.0, 1.0, 0.0] + [0.0] * 509)
    finally:
        session.close()

    resp = client.post("/api/cbir/search", json={
        "panel_id": "P1",
        "case_id": "case1",
        "threshold": 0.99,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["similar_panels"] == []


def test_cbir_search_nonexistent_panel(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url="sqlite:///:memory:",
    )
    Base.metadata.create_all(bind=app.state.dependencies._engine)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/api/cbir/search", json={
        "panel_id": "nonexistent",
        "case_id": "case1",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["similar_panels"] == []
    assert data["total_candidates"] == 0


def test_cbir_search_validation_top_k(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url="sqlite:///:memory:",
    )
    Base.metadata.create_all(bind=app.state.dependencies._engine)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/api/cbir/search", json={
        "panel_id": "P1",
        "top_k": 0,  # Invalid: must be >= 1
    })
    assert resp.status_code == 422


def test_cbir_search_validation_threshold(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url="sqlite:///:memory:",
    )
    Base.metadata.create_all(bind=app.state.dependencies._engine)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/api/cbir/search", json={
        "panel_id": "P1",
        "threshold": 1.5,  # Invalid: must be <= 1.0
    })
    assert resp.status_code == 422


def test_cbir_search_by_label(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url="sqlite:///:memory:",
    )
    Base.metadata.create_all(bind=app.state.dependencies._engine)
    client = TestClient(app, raise_server_exceptions=False)

    deps = app.state.dependencies
    # Create the case in CaseStore so latest_workdir can resolve it.
    deps.store.create_case(case_id="case1")
    session = deps._session_factory()
    try:
        _insert_embedding(session, "case1", "P1", "F1", [1.0, 0.0, 0.0] + [0.0] * 509)
        _insert_embedding(session, "case1", "P2", "F1", [0.5, 0.5, 0.0] + [0.0] * 509)
    finally:
        session.close()

    # Create a workdir with panel_evidence.json for label resolution
    case_dir = tmp_path / "outputs" / "case1" / "research-integrity-audit"
    case_dir.mkdir(parents=True)
    panel_doc = {
        "panels": [
            {"panel_id": "P1", "label": "western blot"},
            {"panel_id": "P2", "label": "flow cytometry"},
        ],
    }
    (case_dir / "panel_evidence.json").write_text(json.dumps(panel_doc))

    # Point the case's latest run at this workdir
    run = deps.store.create_run("case1")
    run.workdir = str(case_dir)
    deps.store.save_run(run)

    resp = client.get("/api/cbir/search/by-panel?case_id=case1&label=western")
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == "case1"
    assert data["label_filter"] == "western"
    assert data["match_count"] == 1
    assert data["panels"][0]["panel_id"] == "P1"
    assert data["panels"][0]["label"] == "western blot"


def test_cbir_search_by_label_no_match(tmp_path: Path) -> None:
    app = create_app(
        data_root=tmp_path / "web_data",
        output_root=tmp_path / "outputs",
        database_url="sqlite:///:memory:",
    )
    Base.metadata.create_all(bind=app.state.dependencies._engine)
    client = TestClient(app, raise_server_exceptions=False)

    deps = app.state.dependencies
    deps.store.create_case(case_id="case1")
    session = deps._session_factory()
    try:
        _insert_embedding(session, "case1", "P1", "F1", [1.0, 0.0, 0.0] + [0.0] * 509)
    finally:
        session.close()

    resp = client.get("/api/cbir/search/by-panel?case_id=case1&label=nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["match_count"] == 0
    assert data["panels"] == []
