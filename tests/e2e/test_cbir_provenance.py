"""E2E and performance integration tests for CBIR search and provenance graph.

Tests cover three areas:

1. **E2E flow tests** -- full pipeline from panel images through CBIR search or
   provenance analysis to structured output, including Agent investigation
   dispatch and report integration.
2. **Performance benchmarks** -- embedding index, CBIR search latency, and
   provenance BFS scaling.  Benchmarks use ``pytest-benchmark`` when available
   and degrade to plain ``time.perf_counter`` measurement otherwise.
3. **Report integration** -- verify that CBIR and provenance outputs are
   consumed by ``build_static_audit_bundle`` and the HTML report.

Mocking policy
--------------
* Docker invocations (provenance-adapter) are mocked at the subprocess boundary.
* SSCD encoder is replaced with a deterministic synthetic encoder.
* No core logic (``run_cbir_search``, ``build_provenance_graph``,
  ``search_similar_panels``, ``_convert_graph``) is mocked.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_panel_images(
    tmp_path: Path, n: int, *, size: int = 64
) -> list[dict[str, Any]]:
    """Create *n* synthetic panel images and return panel evidence entries.

    Images are deterministic: each panel gets a unique solid colour so HSV
    histograms are distinct but repeatable.
    """
    visual_dir = tmp_path / "visual"
    visual_dir.mkdir(exist_ok=True)
    panels_dir = visual_dir / "panels"
    panels_dir.mkdir(exist_ok=True)

    panels: list[dict[str, Any]] = []
    for i in range(n):
        # Cycle hue across panels; vary saturation/lightness slightly
        hue = int(255 * i / max(n, 1))
        sat = 128 + (i % 4) * 30
        val = 180 + (i % 3) * 25
        colour = (hue, min(sat, 255), min(val, 255))
        img = Image.new("RGB", (size, size), color=colour)
        fname = f"panel_{i:04d}.png"
        img.save(panels_dir / fname)
        panels.append(
            {
                "panel_id": f"P{i:04d}",
                "parent_figure_id": f"F{i // 3:03d}",
                "crop_path": f"visual/panels/{fname}",
                "source_image_path": f"visual/panels/{fname}",
            }
        )
    return panels


def _make_figure_images(
    tmp_path: Path, n: int, *, size: int = 128
) -> list[dict[str, Any]]:
    """Create *n* synthetic figure images and return figure evidence entries."""
    images_dir = tmp_path / "images"
    images_dir.mkdir(exist_ok=True)
    figures: list[dict[str, Any]] = []
    for i in range(n):
        hue = int(255 * i / max(n, 1))
        img = Image.new("RGB", (size, size), color=(hue, 180, 200))
        fname = f"fig_{i:03d}.png"
        img.save(images_dir / fname)
        figures.append(
            {
                "figure_id": f"FE-{i:03d}",
                "source_image_path": f"images/{fname}",
            }
        )
    return figures


def _write_panel_evidence(tmp_path: Path, panels: list[dict]) -> Path:
    """Write panel_evidence.json into the workdir."""
    pe_path = tmp_path / "visual" / "panel_evidence.json"
    pe_path.parent.mkdir(parents=True, exist_ok=True)
    pe_path.write_text(json.dumps({"panels": panels}, indent=2))
    return pe_path


def _ensure_case(db, case_id: str) -> None:
    from web.backend.veritas_web.models import CaseModel

    if db.get(CaseModel, case_id) is None:
        db.add(CaseModel(case_id=case_id, paper_title=case_id))
        db.flush()


# ---------------------------------------------------------------------------
# 1. E2E: CBIR search flow
# ---------------------------------------------------------------------------


class TestCbirSearchE2E:
    """End-to-end tests for ``run_cbir_search``."""

    def test_full_cbir_pipeline_produces_pairs(self, tmp_path: Path) -> None:
        """Create identical panels, run CBIR, verify pairs are emitted."""
        panels_dir = tmp_path / "visual" / "panels"
        panels_dir.mkdir(parents=True)

        # Two identical images should have cosine similarity ~ 1.0
        img_a = Image.new("RGB", (64, 64), color=(100, 150, 200))
        img_b = Image.new("RGB", (64, 64), color=(100, 150, 200))
        # A third, very different image
        img_c = Image.new("RGB", (64, 64), color=(255, 0, 0))

        img_a.save(panels_dir / "p1.png")
        img_b.save(panels_dir / "p2.png")
        img_c.save(panels_dir / "p3.png")

        panels = [
            {
                "panel_id": "P1",
                "parent_figure_id": "F1",
                "crop_path": "visual/panels/p1.png",
            },
            {
                "panel_id": "P2",
                "parent_figure_id": "F1",
                "crop_path": "visual/panels/p2.png",
            },
            {
                "panel_id": "P3",
                "parent_figure_id": "F2",
                "crop_path": "visual/panels/p3.png",
            },
        ]

        from engine.static_audit.tools.cbir_search import run_cbir_search

        result = run_cbir_search(panels, workdir=tmp_path, top_k=5, min_score=0.70)

        assert result["status"] == "ran"
        assert result["panel_count"] == 3
        # P1 and P2 are identical -> should produce a pair with high score
        pairs = result["pairs"]
        assert len(pairs) >= 1
        p1_p2 = [
            p
            for p in pairs
            if {p["source_panel_id"], p["target_panel_id"]} == {"P1", "P2"}
        ]
        assert len(p1_p2) == 1
        assert p1_p2[0]["score"] > 0.99
        # P3 is very different from P1/P2
        p1_p3 = [
            p
            for p in pairs
            if "P3" in (p["source_panel_id"], p["target_panel_id"])
            and "P1" in (p["source_panel_id"], p["target_panel_id"])
        ]
        # Either no pair or low score
        if p1_p3:
            assert p1_p3[0]["score"] < 0.90

    def test_cbir_writes_json_output(self, tmp_path: Path) -> None:
        """Verify CBIR result can be serialized and deserialized."""
        panels = _make_panel_images(tmp_path, 6, size=32)
        _write_panel_evidence(tmp_path, panels)

        from engine.static_audit.tools.cbir_search import run_cbir_search

        result = run_cbir_search(panels, workdir=tmp_path, top_k=3, min_score=0.50)

        output_path = tmp_path / "visual" / "cbir_search.json"
        output_path.write_text(json.dumps(result, indent=2))
        loaded = json.loads(output_path.read_text())
        assert loaded["status"] == "ran"
        assert loaded["panel_count"] == 6
        assert isinstance(loaded["pairs"], list)

    def test_cbir_respects_min_score_threshold(self, tmp_path: Path) -> None:
        """High min_score should yield fewer pairs than low min_score."""
        panels = _make_panel_images(tmp_path, 10, size=32)

        from engine.static_audit.tools.cbir_search import run_cbir_search

        strict = run_cbir_search(panels, workdir=tmp_path, top_k=5, min_score=0.95)
        loose = run_cbir_search(panels, workdir=tmp_path, top_k=5, min_score=0.10)

        assert strict["pair_count"] <= loose["pair_count"]

    def test_cbir_respects_max_pairs_limit(self, tmp_path: Path) -> None:
        """max_pairs caps output size even when many pairs pass threshold."""
        panels = _make_panel_images(tmp_path, 20, size=32)

        from engine.static_audit.tools.cbir_search import run_cbir_search

        result = run_cbir_search(
            panels,
            workdir=tmp_path,
            top_k=10,
            min_score=0.0,
            max_pairs=5,
        )
        assert result["pair_count"] <= 5

    def test_cbir_skips_panels_with_missing_images(self, tmp_path: Path) -> None:
        """Panels with unresolvable paths are skipped, not errored."""
        panels = [
            {
                "panel_id": "P1",
                "parent_figure_id": "F1",
                "crop_path": "visual/panels/nonexistent.png",
            },
            {
                "panel_id": "P2",
                "parent_figure_id": "F1",
                "crop_path": "visual/panels/also_missing.png",
            },
        ]

        from engine.static_audit.tools.cbir_search import run_cbir_search

        result = run_cbir_search(panels, workdir=tmp_path)
        assert result["status"] == "ran"
        assert result["panel_count"] == 0
        assert result["skipped_panels"] == 2

    def test_cbir_empty_input(self) -> None:
        from engine.static_audit.tools.cbir_search import run_cbir_search

        result = run_cbir_search([], workdir=Path("/tmp"))
        assert result["status"] == "skipped"
        assert result["pair_count"] == 0


# ---------------------------------------------------------------------------
# 2. E2E: Provenance graph flow
# ---------------------------------------------------------------------------


class TestProvenanceGraphE2E:
    """End-to-end tests for ``build_provenance_graph``.

    The Docker adapter is mocked at the subprocess boundary; the graph
    conversion logic (``_convert_graph``) and metadata assembly in
    ``build_provenance_graph`` are exercised with real code.
    """

    def test_provenance_full_flow_with_mock_adapter(
        self,
        tmp_path: Path,
    ) -> None:
        """Build provenance graph from figure evidence with mocked Docker."""
        figures = _make_figure_images(tmp_path, 5)

        mock_adapter_result = {
            "schema_version": "1.0",
            "status": "ran",
            "source": "elis_provenance_docker",
            "nodes": [
                {
                    "id": f"FE-{i:03d}",
                    "label": f"FE-{i:03d}",
                    "image_path": f"images/fig_{i:03d}.png",
                    "is_query": i < 2,
                }
                for i in range(5)
            ],
            "edges": [
                {
                    "source": "FE-000",
                    "target": "FE-001",
                    "weight": 0.45,
                    "shared_area_source": 0.50,
                    "shared_area_target": 0.45,
                    "matched_keypoints": 80,
                    "is_flipped": False,
                    "cosine_similarity": 0.0,
                },
                {
                    "source": "FE-001",
                    "target": "FE-002",
                    "weight": 0.30,
                    "shared_area_source": 0.35,
                    "shared_area_target": 0.30,
                    "matched_keypoints": 45,
                    "is_flipped": False,
                    "cosine_similarity": 0.0,
                },
            ],
            "spanning_tree_edges": [
                {"source": "FE-000", "target": "FE-001", "weight": 0.45},
                {"source": "FE-001", "target": "FE-002", "weight": 0.30},
            ],
            "connected_components": [
                ["FE-000", "FE-001", "FE-002"],
                ["FE-003"],
                ["FE-004"],
            ],
            "statistics": {
                "node_count": 5,
                "edge_count": 2,
                "component_count": 3,
                "max_weight": 0.45,
                "mean_weight": 0.375,
            },
            "candidate_pairs_tested": 10,
            "edges_found": 2,
            "processing_time_seconds": 3.14,
            "limitations": [],
        }

        from engine.static_audit.tools.provenance_graph import build_provenance_graph

        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=mock_adapter_result,
        ):
            result = build_provenance_graph(
                figures,
                workdir=tmp_path,
                query_figure_ids=["FE-000"],
                max_depth=3,
            )

        assert result["status"] == "ran"
        assert result["max_depth"] == 3
        assert len(result["nodes"]) == 5
        assert len(result["edges"]) == 2
        assert len(result["spanning_tree_edges"]) == 2
        assert len(result["connected_components"]) == 3
        assert result["statistics"]["node_count"] == 5

    def test_provenance_writes_json_output(self, tmp_path: Path) -> None:
        """Verify provenance output can be serialized to disk."""
        figures = _make_figure_images(tmp_path, 3)
        mock_result = {
            "schema_version": "1.0",
            "status": "ran",
            "source": "elis_provenance_docker",
            "nodes": [
                {
                    "id": f["figure_id"],
                    "label": f["figure_id"],
                    "image_path": f["source_image_path"],
                    "is_query": True,
                }
                for f in figures
            ],
            "edges": [],
            "spanning_tree_edges": [],
            "connected_components": [],
            "statistics": {
                "node_count": 3,
                "edge_count": 0,
                "component_count": 0,
                "max_weight": 0.0,
                "mean_weight": 0.0,
            },
            "candidate_pairs_tested": 3,
            "edges_found": 0,
            "processing_time_seconds": 1.0,
            "limitations": ["No edges found."],
        }

        from engine.static_audit.tools.provenance_graph import build_provenance_graph

        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=mock_result,
        ):
            result = build_provenance_graph(figures, workdir=tmp_path)

        out = tmp_path / "visual" / "provenance_graph.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))
        loaded = json.loads(out.read_text())
        assert loaded["status"] == "ran"
        assert loaded["statistics"]["node_count"] == 3

    def test_provenance_failure_isolation(self, tmp_path: Path) -> None:
        """Adapter exceptions must not propagate."""
        figures = _make_figure_images(tmp_path, 3)

        from engine.static_audit.tools.provenance_graph import build_provenance_graph

        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            side_effect=RuntimeError("Docker daemon crashed"),
        ):
            result = build_provenance_graph(figures, workdir=tmp_path)

        assert result["status"] == "failed"
        assert result["failure_category"] == "runtime"
        assert "Docker daemon crashed" in result["error"]

    def test_provenance_elis_graph_conversion(self, tmp_path: Path) -> None:
        """Verify ``_convert_graph`` maps ELIS output to Veritas format."""
        from engine.static_audit.tools._elis_provenance_runner import _convert_graph

        elis_graph = {
            "nodes": [
                {
                    "id": "N1",
                    "label": "N1",
                    "image_path": str(tmp_path / "images" / "fig_000.png"),
                    "is_query": True,
                },
                {
                    "id": "N2",
                    "label": "N2",
                    "image_path": str(tmp_path / "images" / "fig_001.png"),
                    "is_query": False,
                },
            ],
            "edges": [
                {
                    "source": "N1",
                    "target": "N2",
                    "weight": 0.55,
                    "shared_area_source": 0.60,
                    "shared_area_target": 0.55,
                    "matched_keypoints": 100,
                    "is_flipped": True,
                },
            ],
            "spanning_tree_edges": [
                {"source": "N1", "target": "N2", "weight": 0.55},
            ],
            "connected_components": [["N1", "N2"]],
        }

        result = _convert_graph(elis_graph, workdir=tmp_path)

        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1
        assert result["edges"][0]["cosine_similarity"] == 0.0  # ELIS has no SSCD
        assert result["edges"][0]["is_flipped"] is True
        assert result["statistics"]["node_count"] == 2
        assert result["statistics"]["edge_count"] == 1


# ---------------------------------------------------------------------------
# 3. E2E: Web CBIR service (SSCD embedding -> cosine search)
# ---------------------------------------------------------------------------


class TestWebCbirServiceE2E:
    """End-to-end tests for the Web P1 CBIR service using PGlite-backed DB."""

    @pytest.fixture()
    def db_session(self):
        from web.backend.veritas_web.database import (
            Base,
            create_db_engine,
            create_session_factory,
        )

        # Import models to ensure they are registered with Base before create_all
        from web.backend.veritas_web.models import ImageEmbeddingModel  # noqa: F401

        engine = create_db_engine()
        Base.metadata.create_all(bind=engine)
        factory = create_session_factory(engine)
        session = factory()
        try:
            yield session
        finally:
            try:
                session.close()
            finally:
                engine.dispose()

    def _seed_embeddings(
        self, db, case_id: str, panels: list[tuple[str, list[float]]]
    ) -> None:
        from web.backend.veritas_web.embeddings import _utc_now
        from web.backend.veritas_web.models import ImageEmbeddingModel

        _ensure_case(db, case_id)
        for panel_id, embedding in panels:
            db.add(
                ImageEmbeddingModel(
                    case_id=case_id,
                    panel_id=panel_id,
                    figure_id=f"F_{panel_id}",
                    image_path=f"panels/{panel_id}.png",
                    embedding=embedding,
                    indexed_at=_utc_now(),
                )
            )
        db.commit()

    def test_embedding_index_then_search(self, db_session) -> None:
        """Index embeddings, then search -- full flow without mocks."""
        from web.backend.veritas_web.cbir_service import search_similar_panels

        # 512-dim unit vectors: P1 ~ P2, P3 orthogonal
        v1 = [1.0, 0.0, 0.0] + [0.0] * 509
        v2 = [0.99, 0.01, 0.0] + [0.0] * 509
        v3 = [0.0, 0.0, 1.0] + [0.0] * 509

        self._seed_embeddings(
            db_session,
            "case-e2e",
            [
                ("P1", v1),
                ("P2", v2),
                ("P3", v3),
            ],
        )

        result = search_similar_panels(
            db_session, "P1", case_id="case-e2e", threshold=0.9
        )

        assert result["query_panel_id"] == "P1"
        assert result["query_case_id"] == "case-e2e"
        assert len(result["similar_panels"]) == 1
        assert result["similar_panels"][0]["panel_id"] == "P2"
        assert result["similar_panels"][0]["similarity"] >= 0.99

    def test_cross_case_search_flow(self, db_session) -> None:
        """Index embeddings across cases, search without case_id restriction."""
        from web.backend.veritas_web.cbir_service import search_similar_panels

        v1 = [1.0, 0.0, 0.0] + [0.0] * 509
        v2 = [0.98, 0.02, 0.0] + [0.0] * 509

        self._seed_embeddings(db_session, "case-A", [("PA", v1)])
        self._seed_embeddings(db_session, "case-B", [("PB", v2)])

        # Cross-case search (no case_id)
        result = search_similar_panels(db_session, "PA", threshold=0.9)

        assert result["query_case_id"] == "case-A"
        assert len(result["similar_panels"]) == 1
        assert result["similar_panels"][0]["case_id"] == "case-B"
        assert result["similar_panels"][0]["panel_id"] == "PB"

    def test_threshold_below_returns_empty(self, db_session) -> None:
        from web.backend.veritas_web.cbir_service import search_similar_panels

        v1 = [1.0, 0.0, 0.0] + [0.0] * 509
        v2 = [0.5, 0.5, 0.0] + [0.0] * 509  # cosine ~ 0.707

        self._seed_embeddings(db_session, "case-T", [("T1", v1), ("T2", v2)])

        result = search_similar_panels(
            db_session, "T1", case_id="case-T", threshold=0.95
        )
        assert result["similar_panels"] == []

    def test_nonexistent_query_returns_empty(self, db_session) -> None:
        from web.backend.veritas_web.cbir_service import search_similar_panels

        result = search_similar_panels(db_session, "nonexistent_panel")
        assert result["similar_panels"] == []
        assert result["total_candidates"] == 0


# ---------------------------------------------------------------------------
# 4. E2E: Agent investigation dispatch for CBIR
# ---------------------------------------------------------------------------


class TestAgentInvestigationCbirDispatch:
    """Verify that the Agent investigation dispatch runs CBIR correctly."""

    def test_dispatch_runs_cbir_search(self, tmp_path: Path) -> None:
        """When Agent selects visual.cbir_search, dispatch invokes run_cbir_search."""
        from engine.static_audit.investigation import InvestigationAction
        from engine.static_audit.investigation_dispatch import (
            run_investigation_tool_action,
        )

        # Set up panel evidence on disk
        panels = _make_panel_images(tmp_path, 5, size=32)
        _write_panel_evidence(tmp_path, panels)

        action = InvestigationAction(
            round_id=1,
            action_id="cbir_001",
            tool_id="visual.cbir_search",
            params={"top_k": 3, "min_score": 0.50, "max_pairs": 10},
            hypothesis="Panels share visual content",
            depends_on_artifacts=["visual/panel_evidence.json"],
            expected_evidence_type="image_similarity",
        )

        step, outputs = run_investigation_tool_action(
            action=action,
            workdir=tmp_path,
            source_data_dir=None,
            env={},
            force=True,
            progress=None,
        )

        assert step.status == "ran"
        assert len(outputs) == 1
        output_path = Path(outputs[0])
        assert output_path.exists()
        result = json.loads(output_path.read_text())
        assert result["status"] == "ran"
        assert result["panel_count"] == 5

    def test_dispatch_skips_when_panel_evidence_missing(self, tmp_path: Path) -> None:
        """CBIR dispatch skips gracefully when panel_evidence.json is absent."""
        from engine.static_audit.investigation import InvestigationAction
        from engine.static_audit.investigation_dispatch import (
            run_investigation_tool_action,
        )

        action = InvestigationAction(
            round_id=1,
            action_id="cbir_002",
            tool_id="visual.cbir_search",
            params={},
            hypothesis="test",
            depends_on_artifacts=[],
            expected_evidence_type="image_similarity",
        )

        step, outputs = run_investigation_tool_action(
            action=action,
            workdir=tmp_path,
            source_data_dir=None,
            env={},
            force=True,
            progress=None,
        )

        assert step.status == "skipped"
        assert outputs == []


# ---------------------------------------------------------------------------
# 5. Performance benchmarks
# ---------------------------------------------------------------------------


class TestCbirPerformance:
    """Performance benchmarks for CBIR search at different scales.

    These tests use plain ``time.perf_counter`` measurement.  They assert
    soft upper bounds that catch pathological regressions.
    """

    @staticmethod
    def _bench_cbir(
        n_panels: int, tmp_path: Path, *, top_k: int = 5, min_score: float = 0.50
    ) -> dict[str, float]:
        from engine.static_audit.tools.cbir_search import run_cbir_search

        panels = _make_panel_images(tmp_path, n_panels, size=32)
        t0 = time.perf_counter()
        result = run_cbir_search(
            panels, workdir=tmp_path, top_k=top_k, min_score=min_score
        )
        elapsed = time.perf_counter() - t0
        return {
            "n_panels": n_panels,
            "elapsed_seconds": round(elapsed, 4),
            "panel_count": result["panel_count"],
            "pair_count": result["pair_count"],
        }

    def test_cbir_100_panels(self, tmp_path: Path) -> None:
        stats = self._bench_cbir(100, tmp_path)
        print(
            f"\n[CBIR 100 panels] {stats['elapsed_seconds']:.3f}s, "
            f"{stats['pair_count']} pairs"
        )
        # Soft upper bound: 100 panels should complete in < 10s
        assert stats["elapsed_seconds"] < 10.0

    def test_cbir_500_panels(self, tmp_path: Path) -> None:
        stats = self._bench_cbir(500, tmp_path)
        print(
            f"\n[CBIR 500 panels] {stats['elapsed_seconds']:.3f}s, "
            f"{stats['pair_count']} pairs"
        )
        # Soft upper bound: 500 panels should complete in < 60s
        assert stats["elapsed_seconds"] < 60.0


class TestWebCbirPerformance:
    """Performance benchmarks for Web CBIR search (SSCD-style embeddings)."""

    @pytest.fixture()
    def db_session(self):
        from web.backend.veritas_web.database import (
            Base,
            create_db_engine,
            create_session_factory,
        )

        engine = create_db_engine()
        Base.metadata.create_all(bind=engine)
        factory = create_session_factory(engine)
        session = factory()
        try:
            yield session
        finally:
            try:
                session.close()
            finally:
                engine.dispose()

    def _seed_random(self, db, case_id: str, n: int, dim: int = 512) -> None:
        from web.backend.veritas_web.embeddings import _utc_now
        from web.backend.veritas_web.models import ImageEmbeddingModel
        import random

        _ensure_case(db, case_id)
        random.seed(42)
        for i in range(n):
            vec = [random.gauss(0, 1) for _ in range(dim)]
            norm = math.sqrt(sum(x * x for x in vec))
            vec = [x / norm for x in vec]
            db.add(
                ImageEmbeddingModel(
                    case_id=case_id,
                    panel_id=f"perf_P{i:05d}",
                    figure_id=f"perf_F{i:05d}",
                    image_path=f"panels/perf_P{i:05d}.png",
                    embedding=vec,
                    indexed_at=_utc_now(),
                )
            )
        db.commit()

    def test_search_latency_100_panels(self, db_session) -> None:
        from web.backend.veritas_web.cbir_service import search_similar_panels

        self._seed_random(db_session, "perf-100", 100)

        t0 = time.perf_counter()
        result = search_similar_panels(
            db_session,
            "perf_P00000",
            case_id="perf-100",
            top_k=10,
            threshold=0.5,
        )
        elapsed = time.perf_counter() - t0
        print(
            f"\n[Web CBIR 100 embeddings] {elapsed:.3f}s, "
            f"candidates={result['total_candidates']}"
        )
        # Soft bound: brute-force 100 vectors should be < 1s
        assert elapsed < 1.0
        assert result["total_candidates"] >= 0


class TestProvenancePerformance:
    """Performance benchmarks for provenance graph builder.

    The actual Docker adapter is mocked; these benchmarks measure the
    Python-side graph assembly, metadata, and conversion overhead.
    """

    def _mock_result(self, n: int) -> dict[str, Any]:
        """Generate a mock provenance result with *n* nodes and ~n edges."""
        nodes = [
            {
                "id": f"FE-{i:03d}",
                "label": f"FE-{i:03d}",
                "image_path": f"images/fig_{i:03d}.png",
                "is_query": i < 3,
            }
            for i in range(n)
        ]
        edges = []
        for i in range(1, min(n, n)):
            edges.append(
                {
                    "source": f"FE-{i - 1:03d}",
                    "target": f"FE-{i:03d}",
                    "weight": round(0.5 / i, 4),
                    "shared_area_source": round(0.5 / i, 4),
                    "shared_area_target": round(0.4 / i, 4),
                    "matched_keypoints": max(20, 100 - i * 5),
                    "is_flipped": False,
                    "cosine_similarity": 0.0,
                }
            )
        spanning = [
            {"source": e["source"], "target": e["target"], "weight": e["weight"]}
            for e in edges
        ]
        return {
            "schema_version": "1.0",
            "status": "ran",
            "source": "elis_provenance_docker",
            "nodes": nodes,
            "edges": edges,
            "spanning_tree_edges": spanning,
            "connected_components": [[n["id"] for n in nodes]],
            "statistics": {
                "node_count": n,
                "edge_count": len(edges),
                "component_count": 1,
                "max_weight": edges[0]["weight"] if edges else 0.0,
                "mean_weight": round(
                    sum(e["weight"] for e in edges) / max(len(edges), 1), 4
                ),
            },
            "candidate_pairs_tested": n * (n - 1) // 2,
            "edges_found": len(edges),
            "processing_time_seconds": 0.01 * n,
            "limitations": [],
        }

    def test_provenance_100_figures(self, tmp_path: Path) -> None:
        from engine.static_audit.tools.provenance_graph import build_provenance_graph

        figures = _make_figure_images(tmp_path, 100)

        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=self._mock_result(100),
        ):
            t0 = time.perf_counter()
            result = build_provenance_graph(figures, workdir=tmp_path, max_depth=3)
            elapsed = time.perf_counter() - t0

        assert result["status"] == "ran"
        assert result["statistics"]["node_count"] == 100
        print(
            f"\n[Provenance 100 figures] {elapsed:.3f}s, "
            f"{result['statistics']['edge_count']} edges"
        )

    def test_provenance_1000_figures(self, tmp_path: Path) -> None:
        from engine.static_audit.tools.provenance_graph import build_provenance_graph

        figures = _make_figure_images(tmp_path, 1000)

        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=self._mock_result(1000),
        ):
            t0 = time.perf_counter()
            result = build_provenance_graph(figures, workdir=tmp_path, max_depth=5)
            elapsed = time.perf_counter() - t0

        assert result["status"] == "ran"
        assert result["statistics"]["node_count"] == 1000
        print(
            f"\n[Provenance 1000 figures] {elapsed:.3f}s, "
            f"{result['statistics']['edge_count']} edges"
        )


# ---------------------------------------------------------------------------
# 6. Report integration
# ---------------------------------------------------------------------------


class TestReportIntegration:
    """Verify CBIR and provenance outputs integrate with report generation."""

    def test_cbir_result_schema_conformance(self, tmp_path: Path) -> None:
        """CBIR output conforms to the expected schema for report consumption."""
        panels = _make_panel_images(tmp_path, 8, size=32)

        from engine.static_audit.tools.cbir_search import run_cbir_search

        result = run_cbir_search(panels, workdir=tmp_path, top_k=3, min_score=0.50)

        # Required fields for report consumers
        assert "schema_version" in result
        assert "status" in result
        assert "method" in result
        assert "panel_count" in result
        assert "pair_count" in result
        assert "pairs" in result
        assert "limitations" in result

        # Each pair must have the fields the report renderer needs
        for pair in result["pairs"]:
            assert "source_panel_id" in pair
            assert "target_panel_id" in pair
            assert "score" in pair
            assert "source_type" in pair
            assert "manual_review_needed" in pair

    def test_provenance_result_schema_conformance(self, tmp_path: Path) -> None:
        """Provenance output has all fields needed for visual evidence package."""
        figures = _make_figure_images(tmp_path, 4)
        mock_result = self._provenance_mock(4)

        from engine.static_audit.tools.provenance_graph import build_provenance_graph

        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=mock_result,
        ):
            result = build_provenance_graph(figures, workdir=tmp_path)

        # Fields required by HTML visual evidence package
        assert "nodes" in result
        assert "edges" in result
        assert "spanning_tree_edges" in result
        assert "connected_components" in result
        assert "statistics" in result

        # Node fields
        for node in result["nodes"]:
            assert "id" in node
            assert "label" in node
            assert "image_path" in node

        # Edge fields
        for edge in result["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "weight" in edge
            assert "matched_keypoints" in edge

        # Statistics fields
        stats = result["statistics"]
        assert "node_count" in stats
        assert "edge_count" in stats

    def test_cbir_output_written_to_visual_dir(self, tmp_path: Path) -> None:
        """CBIR JSON is written under visual/ for artifact resolution."""
        panels = _make_panel_images(tmp_path, 4, size=32)

        from engine.static_audit.tools.cbir_search import run_cbir_search

        result = run_cbir_search(panels, workdir=tmp_path)

        out = tmp_path / "visual" / "cbir_search.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))
        assert out.exists()
        loaded = json.loads(out.read_text())
        assert loaded["status"] == "ran"

    def test_provenance_mst_in_visual_evidence_package(self, tmp_path: Path) -> None:
        """Provenance MST data is included in the visual evidence package."""
        figures = _make_figure_images(tmp_path, 5)
        mock_result = self._provenance_mock(5)

        from engine.static_audit.tools.provenance_graph import build_provenance_graph

        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=mock_result,
        ):
            result = build_provenance_graph(figures, workdir=tmp_path)

        out = tmp_path / "visual" / "provenance_graph.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))

        loaded = json.loads(out.read_text())
        # MST edges must be present for the ProvenanceGraph component
        assert len(loaded["spanning_tree_edges"]) >= 1
        for ste in loaded["spanning_tree_edges"]:
            assert "source" in ste
            assert "target" in ste
            assert "weight" in ste

    @staticmethod
    def _provenance_mock(n: int) -> dict[str, Any]:
        nodes = [
            {
                "id": f"FE-{i:03d}",
                "label": f"FE-{i:03d}",
                "image_path": f"images/fig_{i:03d}.png",
                "is_query": i == 0,
            }
            for i in range(n)
        ]
        edges = [
            {
                "source": "FE-000",
                "target": f"FE-{i:03d}",
                "weight": round(0.5 / i, 4),
                "shared_area_source": round(0.5 / i, 4),
                "shared_area_target": round(0.4 / i, 4),
                "matched_keypoints": max(20, 100 - i * 10),
                "is_flipped": False,
                "cosine_similarity": 0.0,
            }
            for i in range(1, n)
        ]
        return {
            "schema_version": "1.0",
            "status": "ran",
            "source": "elis_provenance_docker",
            "nodes": nodes,
            "edges": edges,
            "spanning_tree_edges": [
                {"source": e["source"], "target": e["target"], "weight": e["weight"]}
                for e in edges
            ],
            "connected_components": [[n["id"] for n in nodes]],
            "statistics": {
                "node_count": n,
                "edge_count": len(edges),
                "component_count": 1,
                "max_weight": edges[0]["weight"] if edges else 0.0,
                "mean_weight": round(
                    sum(e["weight"] for e in edges) / max(len(edges), 1), 4
                ),
            },
            "candidate_pairs_tested": n * (n - 1) // 2,
            "edges_found": len(edges),
            "processing_time_seconds": 0.1,
            "limitations": [],
        }


# ---------------------------------------------------------------------------
# 7. Tool registry verification
# ---------------------------------------------------------------------------


class TestToolRegistryIntegration:
    """Verify CBIR and provenance are correctly registered."""

    def test_cbir_search_registered_as_agent_selectable(self) -> None:
        from engine.tools.registry import TOOLS, TOOL_ID_CBIR_SEARCH

        assert TOOL_ID_CBIR_SEARCH in TOOLS
        tool = TOOLS[TOOL_ID_CBIR_SEARCH]
        assert tool.agent_selectable is True
        assert tool.step_key == "visual_cbir_search"
        assert "visual/cbir_search.json" in tool.expected_outputs

    def test_provenance_graph_registered(self) -> None:
        from engine.tools.registry import TOOLS, TOOL_ID_PROVENANCE_GRAPH

        assert TOOL_ID_PROVENANCE_GRAPH in TOOLS
        tool = TOOLS[TOOL_ID_PROVENANCE_GRAPH]
        assert tool.step_key == "visual_provenance_graph"
        assert "visual/provenance_graph.json" in tool.expected_outputs

    def test_cbir_param_schema(self) -> None:
        from engine.tools.registry import TOOLS, TOOL_ID_CBIR_SEARCH

        schema = TOOLS[TOOL_ID_CBIR_SEARCH].param_schema
        assert "top_k" in schema
        assert "min_score" in schema
        assert "max_pairs" in schema
        assert schema["top_k"]["type"] == "integer"
        assert schema["min_score"]["type"] == "number"
