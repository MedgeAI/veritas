"""Tests for ELIS provenance-analysis HTTP service adapter.

Tests verify:
1. _service_available correctly detects service presence
2. _convert_graph maps ELIS ProvenanceGraphResult to Veritas format
3. _failed_result produces canonical failure dict
4. _to_container_path / _to_host_path round-trip correctly
5. _validate_output_graph parses output from disk
6. run_provenance_analysis end-to-end with HTTP service mocked
7. Failure isolation: service unavailable, HTTP error, insufficient figures

Note: Tests in TestServiceAvailable and test_returns_failed_when_service_unreachable
are integration tests — they require ELIS to be UNREACHABLE. When `make dev-up`
is running ELIS on :8771, these tests are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from engine.static_audit.tools._elis_provenance_runner import (
    _convert_graph,
    _failed_result,
    _to_container_path,
    _to_host_path,
    _validate_output_graph,
    _service_available,
    run_provenance_analysis,
)

# Skip integration tests when ELIS service is reachable (e.g. `make dev-up`)
_ELIS_AVAILABLE = _service_available()
_skip_if_elis_available = pytest.mark.skipif(
    _ELIS_AVAILABLE,
    reason="ELIS forensic service is reachable — integration test requires it to be down",
)


# ---------------------------------------------------------------------------
# Path translation
# ---------------------------------------------------------------------------


class TestPathTranslation:
    def test_to_container_path_replaces_project_root(self):
        result = _to_container_path(
            Path("/mnt/disk1/LZJ/project/veritas/outputs/test.png")
        )
        assert result == "/data/outputs/test.png"

    def test_to_host_path_replaces_data(self):
        result = _to_host_path("/data/outputs/test.png")
        assert result.endswith("/outputs/test.png")
        assert "/data" not in result

    def test_round_trip(self, tmp_path: Path):
        # Use the actual project root for a realistic path
        host_path = _to_host_path("/data/outputs/test.png")
        container_path = _to_container_path(Path(host_path))
        assert container_path == "/data/outputs/test.png"


# ---------------------------------------------------------------------------
# Graph conversion
# ---------------------------------------------------------------------------


class TestConvertGraph:
    def test_converts_nodes_and_edges(self, tmp_path: Path):
        elis_graph = {
            "nodes": [
                {
                    "id": "fig-1",
                    "label": "Figure 1",
                    "image_path": "/data/workdir/fig1.png",
                    "is_query": True,
                },
                {
                    "id": "fig-2",
                    "label": "Figure 2",
                    "image_path": "/data/workdir/fig2.png",
                    "is_query": False,
                },
            ],
            "edges": [
                {
                    "source": "fig-1",
                    "target": "fig-2",
                    "weight": 0.85,
                    "shared_area_source": 0.3,
                    "shared_area_target": 0.25,
                    "matched_keypoints": 42,
                    "is_flipped": False,
                },
            ],
            "spanning_tree_edges": [
                {"source": "fig-1", "target": "fig-2", "weight": 0.85},
            ],
            "connected_components": [["fig-1", "fig-2"]],
        }

        result = _convert_graph(elis_graph, workdir=tmp_path)

        assert result["schema_version"]
        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["id"] == "fig-1"
        assert result["nodes"][0]["is_query"] is True

        assert len(result["edges"]) == 1
        assert result["edges"][0]["weight"] == 0.85
        assert (
            result["edges"][0]["cosine_similarity"] == 0.0
        )  # ELIS doesn't compute SSCD

        assert len(result["spanning_tree_edges"]) == 1
        assert result["connected_components"] == [["fig-1", "fig-2"]]

        stats = result["statistics"]
        assert stats["node_count"] == 2
        assert stats["edge_count"] == 1
        assert stats["component_count"] == 1

    def test_handles_empty_graph(self, tmp_path: Path):
        result = _convert_graph({"nodes": [], "edges": []}, workdir=tmp_path)
        assert result["statistics"]["node_count"] == 0
        assert result["statistics"]["edge_count"] == 0


# ---------------------------------------------------------------------------
# _failed_result
# ---------------------------------------------------------------------------


class TestFailedResult:
    def test_canonical_failure_structure(self):
        result = _failed_result(
            failure_category="environment",
            error="Service unreachable",
            limitations=["Start the service first"],
        )
        assert result["status"] == "failed"
        assert result["failure_category"] == "environment"
        assert result["error"] == "Service unreachable"
        assert result["source"] == "elis_provenance_service"
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["limitations"] == ["Start the service first"]


# ---------------------------------------------------------------------------
# _validate_output_graph
# ---------------------------------------------------------------------------


class TestValidateOutputGraph:
    def test_valid_graph_file(self, tmp_path: Path):
        graph = {"nodes": [{"id": "1"}], "edges": []}
        (tmp_path / "provenance_graph.json").write_text(json.dumps(graph))
        result = _validate_output_graph(tmp_path)
        assert result is not None
        assert result["nodes"] == [{"id": "1"}]

    def test_missing_graph_file(self, tmp_path: Path):
        assert _validate_output_graph(tmp_path) is None

    def test_invalid_json(self, tmp_path: Path):
        (tmp_path / "provenance_graph.json").write_text("not json")
        assert _validate_output_graph(tmp_path) is None

    def test_missing_required_fields(self, tmp_path: Path):
        (tmp_path / "provenance_graph.json").write_text(json.dumps({"foo": "bar"}))
        assert _validate_output_graph(tmp_path) is None


# ---------------------------------------------------------------------------
# Service availability
# ---------------------------------------------------------------------------


class TestServiceAvailable:
    @_skip_if_elis_available
    def test_returns_false_when_unreachable(self):
        assert _service_available() is False

    @patch("engine.static_audit.tools._elis_provenance_runner._client")
    def test_returns_true_when_healthy(self, mock_client_factory):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_factory.return_value = mock_client

        assert _service_available() is True


# ---------------------------------------------------------------------------
# run_provenance_analysis — end-to-end
# ---------------------------------------------------------------------------


class TestRunProvenanceAnalysis:
    @_skip_if_elis_available
    def test_returns_failed_when_service_unreachable(self, tmp_path: Path):
        figures = [
            {"figure_id": "fig-1", "source_image_path": "fig1.png"},
            {"figure_id": "fig-2", "source_image_path": "fig2.png"},
        ]
        # Create fake image files
        (tmp_path / "fig1.png").write_bytes(b"fake")
        (tmp_path / "fig2.png").write_bytes(b"fake")

        result = run_provenance_analysis(figures, workdir=tmp_path)

        assert result["status"] == "failed"
        assert result["failure_category"] == "environment"
        assert (
            "unreachable" in result["error"].lower()
            or "service" in result["error"].lower()
        )

    def test_returns_failed_with_insufficient_figures(self, tmp_path: Path):
        figures = [
            {"figure_id": "fig-1", "source_image_path": "fig1.png"},
        ]
        (tmp_path / "fig1.png").write_bytes(b"fake")

        # Even if service were available, < 2 figures → dependency failure
        with patch(
            "engine.static_audit.tools._elis_provenance_runner._service_available",
            return_value=True,
        ):
            result = run_provenance_analysis(figures, workdir=tmp_path)

        assert result["status"] == "failed"
        assert result["failure_category"] == "dependency"

    @patch(
        "engine.static_audit.tools._elis_provenance_runner._service_available",
        return_value=True,
    )
    @patch("engine.static_audit.tools._elis_provenance_runner._client")
    def test_end_to_end_success(
        self, mock_client_factory, mock_available, tmp_path: Path
    ):
        figures = [
            {"figure_id": "fig-1", "source_image_path": "fig1.png"},
            {"figure_id": "fig-2", "source_image_path": "fig2.png"},
        ]
        (tmp_path / "fig1.png").write_bytes(b"fake")
        (tmp_path / "fig2.png").write_bytes(b"fake")

        # Mock HTTP response
        service_response = {
            "success": True,
            "message": "Provenance analysis completed",
            "total_images": 2,
            "total_pairs_checked": 1,
            "matched_pairs_count": 1,
            "processing_time_seconds": 5.5,
            "graph": {
                "nodes": [
                    {
                        "id": "fig-1",
                        "label": "fig-1",
                        "image_path": "/data/workdir/fig1.png",
                        "is_query": True,
                    },
                    {
                        "id": "fig-2",
                        "label": "fig-2",
                        "image_path": "/data/workdir/fig2.png",
                        "is_query": False,
                    },
                ],
                "edges": [
                    {
                        "source": "fig-1",
                        "target": "fig-2",
                        "weight": 0.75,
                        "shared_area_source": 0.2,
                        "shared_area_target": 0.15,
                        "matched_keypoints": 30,
                        "is_flipped": False,
                    },
                ],
                "spanning_tree_edges": [],
                "connected_components": [],
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = service_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_factory.return_value = mock_client

        result = run_provenance_analysis(figures, workdir=tmp_path)

        assert result["status"] == "ran"
        assert result["elis_status"] == "completed"
        assert result["source"] == "elis_provenance_service"
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1
        assert result["edges"][0]["weight"] == 0.75
        assert result["processing_time_seconds"] == 5.5
