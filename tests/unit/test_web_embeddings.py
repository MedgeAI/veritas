"""Tests for SSCD embedding extraction and similarity search."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from web.backend.veritas_web.database import Base, create_db_engine, create_session_factory
from web.backend.veritas_web.embeddings import (
    SSCDEncoder,
    _cosine_similarity,
    get_index_status,
    index_panels,
    query_all_similar_pairs,
    query_similar,
    update_index_job,
)


def _make_test_image(path: Path, color: tuple[int, int, int] = (128, 128, 128), size: tuple[int, int] = (256, 256)) -> None:
    """Create a minimal PNG image for testing."""
    from PIL import Image
    img = Image.new("RGB", size, color)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))


@pytest.fixture
def db_session():
    """Create an in-memory SQLite session for testing."""
    engine = create_db_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = create_session_factory(engine)
    session = factory()
    yield session
    session.close()


@pytest.fixture
def workdir_with_panels(tmp_path: Path) -> Path:
    """Create a workdir with panel_evidence.json and panel images."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    # Create panel images
    panels_dir = workdir / "visual" / "panels"
    panels_dir.mkdir(parents=True)
    _make_test_image(panels_dir / "P1.png", color=(200, 50, 50))  # Red-ish
    _make_test_image(panels_dir / "P2.png", color=(200, 55, 50))  # Very similar
    _make_test_image(panels_dir / "P3.png", color=(50, 50, 200))  # Blue-ish (different)

    # Write panel_evidence.json
    panel_doc = {
        "schema_version": "1.0",
        "panels": [
            {"panel_id": "P1", "parent_figure_id": "F1", "crop_path": "visual/panels/P1.png"},
            {"panel_id": "P2", "parent_figure_id": "F1", "crop_path": "visual/panels/P2.png"},
            {"panel_id": "P3", "parent_figure_id": "F2", "crop_path": "visual/panels/P3.png"},
        ],
    }
    (workdir / "panel_evidence.json").write_text(json.dumps(panel_doc), encoding="utf-8")
    return workdir


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [0.5, 0.5, 0.5, 0.5]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0, 0.0]
        b = [-1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_different_lengths_returns_zero(self) -> None:
        assert _cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


class TestSSCDEncoder:
    def test_encoder_unavailable_without_model(self, tmp_path: Path) -> None:
        encoder = SSCDEncoder(model_path=tmp_path / "nonexistent.pt")
        assert not encoder.available

    def test_default_model_path_returns_something(self) -> None:
        encoder = SSCDEncoder()
        # Path object should exist even if file doesn't
        assert encoder._model_path is not None


class TestGetIndexStatus:
    def test_empty_case_returns_not_indexed(self, db_session) -> None:
        status = get_index_status(db_session, "nonexistent-case")
        assert status["status"] == "not_indexed"
        assert status["indexed_count"] == 0
        assert status["last_indexed_at"] is None

    def test_indexed_case_returns_count(self, db_session, workdir_with_panels) -> None:
        from web.backend.veritas_web.embeddings import _utc_now
        from web.backend.veritas_web.models import ImageEmbeddingModel

        # Manually insert some embeddings
        for i in range(3):
            db_session.add(ImageEmbeddingModel(
                case_id="test-case",
                panel_id=f"P{i+1}",
                figure_id="F1",
                image_path=f"panels/P{i+1}.png",
                embedding=[0.1] * 512,
                indexed_at=_utc_now(),
            ))
        db_session.commit()

        status = get_index_status(db_session, "test-case")
        assert status["status"] == "indexed"
        assert status["indexed_count"] == 3
        assert status["last_indexed_at"] is not None

    def test_index_job_status_is_reported(self, db_session) -> None:
        update_index_job(
            db_session,
            "test-case",
            "running",
            expected_count=3,
            detail="SSCD indexing running",
        )

        status = get_index_status(db_session, "test-case")

        assert status["status"] == "running"
        assert status["job_status"] == "running"
        assert status["indexed_count"] == 0
        assert status["expected_count"] == 3
        assert status["detail"] == "SSCD indexing running"
        assert status["started_at"] is not None


class TestQuerySimilar:
    def test_no_query_panel_returns_empty(self, db_session) -> None:
        results = query_similar(db_session, "case1", "P_nonexistent")
        assert results == []

    def test_returns_similar_panels(self, db_session) -> None:
        from web.backend.veritas_web.embeddings import _utc_now
        from web.backend.veritas_web.models import ImageEmbeddingModel

        # Insert embeddings: P1 and P2 are similar, P3 is different
        db_session.add(ImageEmbeddingModel(
            case_id="case1", panel_id="P1", figure_id="F1",
            image_path="p1.png", embedding=[1.0, 0.0, 0.0] + [0.0] * 509,
            indexed_at=_utc_now(),
        ))
        db_session.add(ImageEmbeddingModel(
            case_id="case1", panel_id="P2", figure_id="F1",
            image_path="p2.png", embedding=[0.99, 0.01, 0.0] + [0.0] * 509,
            indexed_at=_utc_now(),
        ))
        db_session.add(ImageEmbeddingModel(
            case_id="case1", panel_id="P3", figure_id="F2",
            image_path="p3.png", embedding=[0.0, 0.0, 1.0] + [0.0] * 509,
            indexed_at=_utc_now(),
        ))
        db_session.commit()

        # Query for P1 — should find P2 as similar (cos ≈ 0.99), not P3 (cos ≈ 0)
        results = query_similar(db_session, "case1", "P1", threshold=0.9)
        assert len(results) == 1
        assert results[0]["panel_id"] == "P2"
        assert results[0]["similarity"] > 0.9


class TestQueryAllSimilarPairs:
    def test_finds_pairs_above_threshold(self, db_session) -> None:
        from web.backend.veritas_web.embeddings import _utc_now
        from web.backend.veritas_web.models import ImageEmbeddingModel

        db_session.add(ImageEmbeddingModel(
            case_id="case1", panel_id="P1", figure_id="F1",
            image_path="p1.png", embedding=[1.0, 0.0, 0.0] + [0.0] * 509,
            indexed_at=_utc_now(),
        ))
        db_session.add(ImageEmbeddingModel(
            case_id="case1", panel_id="P2", figure_id="F1",
            image_path="p2.png", embedding=[0.95, 0.05, 0.0] + [0.0] * 509,
            indexed_at=_utc_now(),
        ))
        db_session.add(ImageEmbeddingModel(
            case_id="case1", panel_id="P3", figure_id="F2",
            image_path="p3.png", embedding=[0.0, 1.0, 0.0] + [0.0] * 509,
            indexed_at=_utc_now(),
        ))
        db_session.commit()

        pairs = query_all_similar_pairs(db_session, "case1", threshold=0.9)
        # P1-P2 should be similar, P1-P3 and P2-P3 should not
        assert len(pairs) == 1
        assert pairs[0]["source_panel_id"] == "P1"
        assert pairs[0]["target_panel_id"] == "P2"

    def test_empty_for_single_panel(self, db_session) -> None:
        from web.backend.veritas_web.embeddings import _utc_now
        from web.backend.veritas_web.models import ImageEmbeddingModel

        db_session.add(ImageEmbeddingModel(
            case_id="case1", panel_id="P1", figure_id="F1",
            image_path="p1.png", embedding=[1.0] + [0.0] * 511,
            indexed_at=_utc_now(),
        ))
        db_session.commit()

        pairs = query_all_similar_pairs(db_session, "case1", threshold=0.5)
        assert pairs == []


class TestIndexPanels:
    def test_missing_panel_evidence_returns_failed(self, db_session, tmp_path: Path) -> None:
        encoder = SSCDEncoder()
        result = index_panels(db_session, "case1", tmp_path, encoder)
        assert result["status"] == "failed"
        assert result["failure_category"] == "artifact_missing"

    def test_unavailable_model_returns_failed_environment(self, db_session, workdir_with_panels) -> None:
        encoder = SSCDEncoder(model_path=Path("/nonexistent/model.pt"))
        result = index_panels(db_session, "case1", workdir_with_panels, encoder)
        assert result["status"] == "failed"
        assert result["failure_category"] == "environment"

    def test_all_image_encode_failures_return_failed(self, db_session, workdir_with_panels) -> None:
        class FailingEncoder:
            available = True

            def encode_batch(self, image_paths, batch_size=32):
                return [None for _path in image_paths]

        result = index_panels(db_session, "case1", workdir_with_panels, FailingEncoder())

        assert result["status"] == "failed"
        assert result["failure_category"] == "image_load_failed"
        assert result["indexed_count"] == 0
        assert result["expected_count"] == 3

    def test_partial_image_encode_failures_persist_successes(self, db_session, workdir_with_panels) -> None:
        from web.backend.veritas_web.models import ImageEmbeddingModel

        class PartialEncoder:
            available = True

            def encode_batch(self, image_paths, batch_size=32):
                return [[1.0] + [0.0] * 511, None, None]

        result = index_panels(db_session, "case1", workdir_with_panels, PartialEncoder())

        assert result["status"] == "partial"
        assert result["indexed_count"] == 1
        assert result["expected_count"] == 3
        assert db_session.query(ImageEmbeddingModel).filter(ImageEmbeddingModel.case_id == "case1").count() == 1
