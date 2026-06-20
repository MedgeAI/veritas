"""Integration tests for upgraded provenance_graph.py.

Tests verify:
1. build_provenance_graph delegates to run_provenance_analysis correctly
2. Query figure IDs are passed through
3. Descriptor type and max_depth parameters are forwarded
4. Failure isolation: insufficient figures, adapter exception
5. Output format includes max_depth and descriptor_type metadata
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from engine.static_audit.tools.provenance_graph import build_provenance_graph


@pytest.fixture()
def figure_evidence_list(tmp_path: Path) -> list[dict]:
    """Figure evidence with real (tiny) image files on disk."""
    from PIL import Image

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for name in ("fig1.png", "fig2.png", "fig3.png"):
        img = Image.new("RGB", (64, 64), color="blue")
        img.save(images_dir / name)

    return [
        {"figure_id": "FE-001", "source_image_path": "images/fig1.png"},
        {"figure_id": "FE-002", "source_image_path": "images/fig2.png"},
        {"figure_id": "FE-003", "source_image_path": "images/fig3.png"},
    ]


@pytest.fixture()
def mock_provenance_result() -> dict:
    """Mock result from run_provenance_analysis."""
    return {
        "schema_version": "1.0",
        "status": "ran",
        "source": "elis_provenance_docker",
        "nodes": [
            {
                "id": "FE-001",
                "label": "FE-001",
                "image_path": "images/fig1.png",
                "is_query": True,
            },
            {
                "id": "FE-002",
                "label": "FE-002",
                "image_path": "images/fig2.png",
                "is_query": False,
            },
            {
                "id": "FE-003",
                "label": "FE-003",
                "image_path": "images/fig3.png",
                "is_query": False,
            },
        ],
        "edges": [
            {
                "source": "FE-001",
                "target": "FE-002",
                "weight": 0.35,
                "shared_area_source": 0.40,
                "shared_area_target": 0.35,
                "matched_keypoints": 45,
                "is_flipped": False,
                "cosine_similarity": 0.0,
            },
        ],
        "spanning_tree_edges": [
            {"source": "FE-001", "target": "FE-002", "weight": 0.35},
        ],
        "connected_components": [["FE-001", "FE-002", "FE-003"]],
        "statistics": {
            "node_count": 3,
            "edge_count": 1,
            "component_count": 1,
            "max_weight": 0.35,
            "mean_weight": 0.35,
        },
        "candidate_pairs_tested": 3,
        "edges_found": 1,
        "processing_time_seconds": 12.34,
        "limitations": [],
    }


class TestBuildProvenanceGraphIntegration:
    """Integration tests for build_provenance_graph."""

    def test_delegates_to_provenance_adapter(
        self, figure_evidence_list, tmp_path, mock_provenance_result
    ):
        """Verify build_provenance_graph calls run_provenance_analysis with correct params."""
        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=mock_provenance_result,
        ) as mock_run:
            result = build_provenance_graph(
                figure_evidence_list,
                workdir=tmp_path,
                query_figure_ids=["FE-001"],
                descriptor_type="cv_rsift",
                min_keypoints=20,
                min_area=0.01,
                max_depth=3,
                check_flip=True,
                max_workers=4,
                timeout=600,
            )

            # Verify run_provenance_analysis was called
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["figure_evidence"] == figure_evidence_list
            assert call_kwargs["workdir"] == tmp_path
            assert call_kwargs["query_figure_ids"] == ["FE-001"]
            assert call_kwargs["descriptor_type"] == "cv_rsift"
            assert call_kwargs["min_keypoints"] == 20
            assert call_kwargs["min_area"] == 0.01
            assert call_kwargs["check_flip"] is True
            assert call_kwargs["max_workers"] == 4
            assert call_kwargs["timeout"] == 600

            # Verify result structure
            assert result["status"] == "ran"
            assert result["max_depth"] == 3
            assert result["descriptor_type"] == "cv_rsift"
            assert len(result["nodes"]) == 3
            assert len(result["edges"]) == 1

    def test_all_figures_as_queries_when_none_specified(
        self, figure_evidence_list, tmp_path, mock_provenance_result
    ):
        """When query_figure_ids is None, all figures should be treated as queries."""
        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=mock_provenance_result,
        ) as mock_run:
            build_provenance_graph(figure_evidence_list, workdir=tmp_path)

            call_kwargs = mock_run.call_args.kwargs
            # All figure IDs should be in query_figure_ids
            assert set(call_kwargs["query_figure_ids"]) == {
                "FE-001",
                "FE-002",
                "FE-003",
            }

    def test_insufficient_figures(self, tmp_path):
        """Should return failed status when fewer than 2 figures have valid paths."""
        result = build_provenance_graph(
            [{"figure_id": "FE-001", "source_image_path": "missing.png"}],
            workdir=tmp_path,
        )
        assert result["status"] == "failed"
        assert result["failure_category"] == "dependency"
        assert "Not enough figures" in result["error"]

    def test_adapter_exception_isolation(self, figure_evidence_list, tmp_path):
        """Verify adapter exceptions are caught and returned as structured failure."""
        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            side_effect=RuntimeError("Docker daemon crashed"),
        ):
            result = build_provenance_graph(figure_evidence_list, workdir=tmp_path)

            assert result["status"] == "failed"
            assert result["failure_category"] == "runtime"
            assert "Docker daemon crashed" in result["error"]
            assert any("Docker daemon crashed" in lim for lim in result["limitations"])

    def test_custom_descriptor_type(
        self, figure_evidence_list, tmp_path, mock_provenance_result
    ):
        """Verify custom descriptor_type is forwarded to adapter."""
        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=mock_provenance_result,
        ) as mock_run:
            result = build_provenance_graph(
                figure_evidence_list,
                workdir=tmp_path,
                descriptor_type="vlfeat_sift_heq",
            )

            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["descriptor_type"] == "vlfeat_sift_heq"
            assert result["descriptor_type"] == "vlfeat_sift_heq"

    def test_custom_max_depth(
        self, figure_evidence_list, tmp_path, mock_provenance_result
    ):
        """Verify custom max_depth is added to result metadata."""
        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=mock_provenance_result,
        ):
            result = build_provenance_graph(
                figure_evidence_list,
                workdir=tmp_path,
                max_depth=5,
            )
            assert result["max_depth"] == 5

    def test_failed_adapter_result_preserved(self, figure_evidence_list, tmp_path):
        """Verify failed adapter results are preserved (not converted to exception)."""
        failed_result = {
            "schema_version": "1.0",
            "status": "failed",
            "failure_category": "environment",
            "error": "Docker image not available",
            "source": "elis_provenance_docker",
            "nodes": [],
            "edges": [],
            "statistics": {},
            "limitations": ["Docker image not found"],
        }
        with patch(
            "engine.static_audit.tools.provenance_graph.run_provenance_analysis",
            return_value=failed_result,
        ):
            result = build_provenance_graph(figure_evidence_list, workdir=tmp_path)

            # Failed results should not have max_depth/descriptor_type added
            assert result["status"] == "failed"
            assert "max_depth" not in result
            assert "descriptor_type" not in result
            assert result["limitations"] == ["Docker image not found"]

    def test_missing_image_paths_filtered(self, tmp_path):
        """Figures without valid image paths should be filtered before adapter call."""
        from PIL import Image

        images_dir = tmp_path / "images"
        images_dir.mkdir()
        Image.new("RGB", (32, 32)).save(images_dir / "fig1.png")

        evidence = [
            {"figure_id": "FE-001", "source_image_path": "images/fig1.png"},
            {
                "figure_id": "FE-002",
                "source_image_path": "images/missing.png",
            },  # does not exist
        ]

        # Only 1 valid figure -> should fail with dependency error
        result = build_provenance_graph(evidence, workdir=tmp_path)
        assert result["status"] == "failed"
        assert result["failure_category"] == "dependency"
