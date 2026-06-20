"""Tests for ELIS provenance-analysis Docker adapter.

Tests verify:
1. _docker_available correctly detects Docker presence
2. _build_container_input produces valid ContainerInput JSON
3. _parse_container_output handles success, failure, invalid JSON, missing fields
4. _convert_graph maps ELIS ProvenanceGraphResult to Veritas format
5. _failed_result produces canonical failure dict
6. _run_docker invokes Docker with correct volume mounts and parses output
7. run_provenance_analysis end-to-end with Docker mocked
8. Failure isolation: Docker unavailable, container error, insufficient figures
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.static_audit.tools._elis_provenance_runner import (
    DOCKER_IMAGE,
    _build_container_input,
    _convert_graph,
    _docker_available,
    _failed_result,
    _parse_container_output,
    _run_docker,
    run_provenance_analysis,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_elis_output() -> dict:
    """A realistic ContainerOutput from the ELIS provenance container."""
    return {
        "success": True,
        "command": "provenance",
        "message": "Provenance analysis completed: 3 images, 2 matches",
        "provenance_response": {
            "success": True,
            "message": "ok",
            "total_images": 3,
            "total_pairs_checked": 3,
            "matched_pairs_count": 2,
            "processing_time_seconds": 12.34,
            "graph": {
                "nodes": [
                    {"id": "FE-001", "label": "FE-001", "image_path": "/data/img0/fig1.png", "is_query": True, "metadata": None},
                    {"id": "FE-002", "label": "FE-002", "image_path": "/data/img1/fig2.png", "is_query": False, "metadata": None},
                    {"id": "FE-003", "label": "FE-003", "image_path": "/data/img0/fig3.png", "is_query": False, "metadata": None},
                ],
                "edges": [
                    {
                        "source": "FE-001", "target": "FE-002",
                        "weight": 0.35, "shared_area_source": 0.40,
                        "shared_area_target": 0.35, "matched_keypoints": 45,
                        "is_flipped": False,
                    },
                    {
                        "source": "FE-002", "target": "FE-003",
                        "weight": 0.20, "shared_area_source": 0.22,
                        "shared_area_target": 0.20, "matched_keypoints": 30,
                        "is_flipped": True,
                    },
                ],
                "spanning_tree_edges": [
                    {
                        "source": "FE-001", "target": "FE-002",
                        "weight": 0.35, "shared_area_source": 0.40,
                        "shared_area_target": 0.35, "matched_keypoints": 45,
                        "is_flipped": False,
                    },
                ],
                "connected_components": [["FE-001", "FE-002", "FE-003"]],
                "adjacency_matrix": {"FE-001": {"FE-002": 0.35}, "FE-002": {"FE-001": 0.35, "FE-003": 0.20}},
            },
            "matched_pairs": [
                {"image1_id": "FE-001", "image2_id": "FE-002", "shared_area_img1": 0.40, "shared_area_img2": 0.35, "matched_keypoints": 45, "is_flipped": False},
            ],
            "visualization_data": {"nodes": [], "edges": []},
            "output_files": {"graph_json": "/output/provenance_graph.json"},
        },
    }


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


# ---------------------------------------------------------------------------
# _docker_available
# ---------------------------------------------------------------------------

class TestDockerAvailable:
    def test_returns_true_when_image_present(self):
        mock_result = MagicMock()
        mock_result.stdout = "abc123\n"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            assert _docker_available() is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[:3] == ["docker", "images", "-q"]

    def test_returns_false_when_image_missing(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            assert _docker_available() is False

    def test_returns_false_on_os_error(self):
        with patch("subprocess.run", side_effect=OSError("no docker")):
            assert _docker_available() is False

    def test_returns_false_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 10)):
            assert _docker_available() is False


# ---------------------------------------------------------------------------
# _build_container_input
# ---------------------------------------------------------------------------

class TestBuildContainerInput:
    def test_structure(self):
        images = [{"id": "FE-001", "path": "/a.png", "label": "FE-001", "is_query": True}]
        result = _build_container_input(
            images=images,
            query_image_ids=["FE-001"],
            output_dir="/output",
        )
        assert result["command"] == "provenance"
        req = result["provenance_request"]
        assert req["images"] is images
        assert req["query_image_ids"] == ["FE-001"]
        assert req["output_dir"] == "/output"
        assert req["descriptor_type"] == "cv_rsift"
        assert req["alignment_strategy"] == "CV_MAGSAC"
        assert req["check_flip"] is True

    def test_custom_parameters(self):
        result = _build_container_input(
            images=[], query_image_ids=[], output_dir="/out",
            descriptor_type="vlfeat_sift_heq",
            min_keypoints=50,
            min_area=0.05,
            check_flip=False,
            max_workers=8,
        )
        req = result["provenance_request"]
        assert req["descriptor_type"] == "vlfeat_sift_heq"
        assert req["min_keypoints"] == 50
        assert req["min_area"] == 0.05
        assert req["check_flip"] is False
        assert req["max_workers"] == 8


# ---------------------------------------------------------------------------
# _parse_container_output
# ---------------------------------------------------------------------------

class TestParseContainerOutput:
    def test_success(self, sample_elis_output):
        result = _parse_container_output(json.dumps(sample_elis_output))
        assert result["success"] is True
        assert result["total_images"] == 3
        assert result["matched_pairs_count"] == 2
        assert result["graph"] is not None
        assert len(result["graph"]["nodes"]) == 3
        assert len(result["graph"]["edges"]) == 2

    def test_invalid_json(self):
        result = _parse_container_output("not json at all")
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_container_failure(self):
        data = {"success": False, "command": "provenance", "message": "OOM killed"}
        result = _parse_container_output(json.dumps(data))
        assert result["success"] is False
        assert "OOM killed" in result["error"]

    def test_missing_provenance_response(self):
        data = {"success": True, "command": "provenance", "message": "ok"}
        result = _parse_container_output(json.dumps(data))
        assert result["success"] is False
        assert "Missing provenance_response" in result["error"]

    def test_empty_stdout(self):
        result = _parse_container_output("")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# _convert_graph
# ---------------------------------------------------------------------------

class TestConvertGraph:
    def test_basic_conversion(self, tmp_path):
        elis_graph = {
            "nodes": [
                {"id": "A", "label": "A", "image_path": "/data/img0/a.png", "is_query": True},
                {"id": "B", "label": "B", "image_path": "/data/img1/b.png", "is_query": False},
            ],
            "edges": [
                {
                    "source": "A", "target": "B",
                    "weight": 0.35, "shared_area_source": 0.40,
                    "shared_area_target": 0.35, "matched_keypoints": 45,
                    "is_flipped": False,
                },
            ],
            "spanning_tree_edges": [
                {"source": "A", "target": "B", "weight": 0.35,
                 "shared_area_source": 0.40, "shared_area_target": 0.35,
                 "matched_keypoints": 45, "is_flipped": False},
            ],
            "connected_components": [["A", "B"]],
        }
        result = _convert_graph(elis_graph, workdir=tmp_path)
        assert result["schema_version"] == "1.0"
        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["is_query"] is True
        assert len(result["edges"]) == 1
        assert result["edges"][0]["cosine_similarity"] == 0.0  # ELIS does not compute SSCD
        assert len(result["spanning_tree_edges"]) == 1
        assert result["connected_components"] == [["A", "B"]]

    def test_statistics(self, tmp_path):
        elis_graph = {
            "nodes": [{"id": "X", "label": "X", "image_path": "x.png", "is_query": False}],
            "edges": [
                {"source": "X", "target": "Y", "weight": 0.5,
                 "shared_area_source": 0.6, "shared_area_target": 0.5,
                 "matched_keypoints": 100, "is_flipped": False},
                {"source": "X", "target": "Z", "weight": 0.3,
                 "shared_area_source": 0.3, "shared_area_target": 0.3,
                 "matched_keypoints": 50, "is_flipped": False},
            ],
            "spanning_tree_edges": [],
            "connected_components": [["X", "Y", "Z"]],
        }
        result = _convert_graph(elis_graph, workdir=tmp_path)
        stats = result["statistics"]
        assert stats["node_count"] == 1
        assert stats["edge_count"] == 2
        assert stats["max_weight"] == 0.5
        assert stats["mean_weight"] == 0.4

    def test_empty_graph(self, tmp_path):
        elis_graph = {"nodes": [], "edges": [], "spanning_tree_edges": [], "connected_components": []}
        result = _convert_graph(elis_graph, workdir=tmp_path)
        assert result["statistics"]["node_count"] == 0
        assert result["statistics"]["edge_count"] == 0
        assert result["statistics"]["max_weight"] == 0.0


# ---------------------------------------------------------------------------
# _failed_result
# ---------------------------------------------------------------------------

class TestFailedResult:
    def test_structure(self):
        result = _failed_result(
            failure_category="environment",
            error="Docker not found",
            limitations=["Docker image not available"],
        )
        assert result["status"] == "failed"
        assert result["failure_category"] == "environment"
        assert result["error"] == "Docker not found"
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["source"] == "elis_provenance_docker"
        assert result["limitations"] == ["Docker image not available"]

    def test_default_limitations(self):
        result = _failed_result(failure_category="runtime", error="crash")
        assert result["limitations"] == []


# ---------------------------------------------------------------------------
# _run_docker
# ---------------------------------------------------------------------------

class TestRunDocker:
    def test_success(self, tmp_path, sample_elis_output):
        output_dir = tmp_path / "output"
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(sample_elis_output)
        mock_proc.stderr = ""

        container_input = _build_container_input(
            images=[{"id": "A", "path": str(image_dir / "a.png")}, {"id": "B", "path": str(image_dir / "b.png")}],
            query_image_ids=["A"],
            output_dir=str(output_dir),
        )

        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            result = _run_docker(container_input, [image_dir], output_dir)
            assert result["success"] is True
            assert result["total_images"] == 3

            # Verify docker run was called with correct image
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "docker"
            assert "run" in cmd
            assert DOCKER_IMAGE in cmd

    def test_container_exit_nonzero(self, tmp_path):
        output_dir = tmp_path / "output"
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "Error: segmentation fault"
        mock_proc.stdout = ""

        container_input = _build_container_input(
            images=[{"id": "A", "path": str(image_dir / "a.png")}],
            query_image_ids=[],
            output_dir=str(output_dir),
        )

        with patch("subprocess.run", return_value=mock_proc):
            result = _run_docker(container_input, [image_dir], output_dir)
            assert result["success"] is False
            assert "segmentation fault" in result["error"]

    def test_timeout(self, tmp_path):
        output_dir = tmp_path / "output"
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        container_input = _build_container_input(
            images=[{"id": "A", "path": str(image_dir / "a.png")}],
            query_image_ids=[],
            output_dir=str(output_dir),
        )

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 600)):
            result = _run_docker(container_input, [image_dir], output_dir, timeout=600)
            assert result["success"] is False
            assert "timed out" in result["error"]

    def test_os_error(self, tmp_path):
        output_dir = tmp_path / "output"
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        container_input = _build_container_input(
            images=[{"id": "A", "path": str(image_dir / "a.png")}],
            query_image_ids=[],
            output_dir=str(output_dir),
        )

        with patch("subprocess.run", side_effect=OSError("Docker daemon not running")):
            result = _run_docker(container_input, [image_dir], output_dir)
            assert result["success"] is False
            assert "Docker daemon" in result["error"]


# ---------------------------------------------------------------------------
# run_provenance_analysis (integration-level)
# ---------------------------------------------------------------------------

class TestRunProvenanceAnalysis:
    def test_docker_unavailable(self, figure_evidence_list, tmp_path):
        with patch("engine.static_audit.tools._elis_provenance_runner._docker_available", return_value=False):
            result = run_provenance_analysis(figure_evidence_list, workdir=tmp_path)
            assert result["status"] == "failed"
            assert result["failure_category"] == "environment"
            assert DOCKER_IMAGE in result["limitations"][0]

    def test_insufficient_figures(self, tmp_path):
        with patch("engine.static_audit.tools._elis_provenance_runner._docker_available", return_value=True):
            result = run_provenance_analysis(
                [{"figure_id": "FE-001", "source_image_path": "missing.png"}],
                workdir=tmp_path,
            )
            assert result["status"] == "failed"
            assert result["failure_category"] == "dependency"

    def test_success(self, figure_evidence_list, tmp_path, sample_elis_output):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(sample_elis_output)
        mock_proc.stderr = ""

        with (
            patch("engine.static_audit.tools._elis_provenance_runner._docker_available", return_value=True),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = run_provenance_analysis(
                figure_evidence_list,
                workdir=tmp_path,
                query_figure_ids=["FE-001"],
            )
            assert result["status"] == "ran"
            assert result["source"] == "elis_provenance_docker"
            assert len(result["nodes"]) == 3
            assert len(result["edges"]) == 2
            assert result["processing_time_seconds"] == 12.34
            # Query flag should be preserved
            query_nodes = [n for n in result["nodes"] if n["is_query"]]
            assert len(query_nodes) >= 1

    def test_container_failure(self, figure_evidence_list, tmp_path):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "CUDA out of memory"
        mock_proc.stdout = ""

        with (
            patch("engine.static_audit.tools._elis_provenance_runner._docker_available", return_value=True),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = run_provenance_analysis(figure_evidence_list, workdir=tmp_path)
            assert result["status"] == "failed"
            assert result["failure_category"] == "runtime"
            assert "CUDA" in result["error"] or "CUDA" in result["limitations"][0]

    def test_no_edges_limitation(self, figure_evidence_list, tmp_path):
        """Container success but no edges should produce a limitation, not a failure."""
        no_edges_output = {
            "success": True, "command": "provenance", "message": "ok",
            "provenance_response": {
                "success": True, "message": "ok",
                "total_images": 3, "total_pairs_checked": 3,
                "matched_pairs_count": 0, "processing_time_seconds": 5.0,
                "graph": {
                    "nodes": [
                        {"id": "FE-001", "label": "FE-001", "image_path": "/a.png", "is_query": True},
                        {"id": "FE-002", "label": "FE-002", "image_path": "/b.png", "is_query": False},
                    ],
                    "edges": [],
                    "spanning_tree_edges": [],
                    "connected_components": [["FE-001"], ["FE-002"]],
                },
                "matched_pairs": [],
                "visualization_data": None,
                "output_files": None,
            },
        }
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(no_edges_output)

        with (
            patch("engine.static_audit.tools._elis_provenance_runner._docker_available", return_value=True),
            patch("subprocess.run", return_value=mock_proc),
        ):
            result = run_provenance_analysis(figure_evidence_list, workdir=tmp_path)
            assert result["status"] == "ran"
            assert result["edges_found"] == 0
            assert any("No provenance edges" in lim for lim in result["limitations"])

    def test_missing_images_skipped(self, tmp_path):
        """Figures without valid image paths should be silently skipped."""
        from PIL import Image
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        Image.new("RGB", (32, 32)).save(images_dir / "fig1.png")

        evidence = [
            {"figure_id": "FE-001", "source_image_path": "images/fig1.png"},
            {"figure_id": "FE-002", "source_image_path": "images/missing.png"},  # does not exist
        ]
        with patch("engine.static_audit.tools._elis_provenance_runner._docker_available", return_value=True):
            result = run_provenance_analysis(evidence, workdir=tmp_path)
            # Only 1 valid figure -> should fail with dependency error
            assert result["status"] == "failed"
            assert result["failure_category"] == "dependency"

    def test_volume_mount_paths(self, figure_evidence_list, tmp_path, sample_elis_output):
        """Verify Docker command includes correct volume mounts."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(sample_elis_output)

        with (
            patch("engine.static_audit.tools._elis_provenance_runner._docker_available", return_value=True),
            patch("subprocess.run", return_value=mock_proc) as mock_run,
        ):
            run_provenance_analysis(figure_evidence_list, workdir=tmp_path)
            cmd = mock_run.call_args[0][0]
            # Check volume mounts exist
            volume_flags = [i for i, x in enumerate(cmd) if x == "-v"]
            assert len(volume_flags) >= 2  # At least image dir + output dir + input json
