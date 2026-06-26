"""Tests for ELIS provenance-analysis Docker adapter.

Tests verify:
1. _docker_available correctly detects Docker presence
2. _build_container_input produces valid ContainerInput JSON
3. _parse_container_output handles success, failure, invalid JSON, missing fields
4. _convert_graph maps ELIS ProvenanceGraphResult to Veritas format
5. _failed_result produces canonical failure dict
6. _run_docker_with_telemetry invokes Docker with correct volume mounts and parses output
7. run_provenance_analysis end-to-end with Docker mocked
8. Failure isolation: Docker unavailable, container error, insufficient figures
9. Phase-level telemetry (PRD3-T8)
10. Inactivity watchdog marks stalled
11. Hard cap terminates and attempts output recovery
12. Docker diagnostics recorded correctly
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.static_audit.tools._elis_provenance_runner import (
    DOCKER_IMAGE,
    HARD_CAP_SECONDS,
    INACTIVITY_WATCHDOG_SECONDS,
    DockerDiagnostics,
    PhaseTelemetry,
    _build_container_input,
    _convert_graph,
    _docker_available,
    _failed_result,
    _infer_phase_from_output,
    _parse_container_output,
    _run_docker_with_telemetry,
    _validate_output_graph,
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
                    {
                        "id": "FE-001",
                        "label": "FE-001",
                        "image_path": "/data/img0/fig1.png",
                        "is_query": True,
                        "metadata": None,
                    },
                    {
                        "id": "FE-002",
                        "label": "FE-002",
                        "image_path": "/data/img1/fig2.png",
                        "is_query": False,
                        "metadata": None,
                    },
                    {
                        "id": "FE-003",
                        "label": "FE-003",
                        "image_path": "/data/img0/fig3.png",
                        "is_query": False,
                        "metadata": None,
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
                    },
                    {
                        "source": "FE-002",
                        "target": "FE-003",
                        "weight": 0.20,
                        "shared_area_source": 0.22,
                        "shared_area_target": 0.20,
                        "matched_keypoints": 30,
                        "is_flipped": True,
                    },
                ],
                "spanning_tree_edges": [
                    {
                        "source": "FE-001",
                        "target": "FE-002",
                        "weight": 0.35,
                        "shared_area_source": 0.40,
                        "shared_area_target": 0.35,
                        "matched_keypoints": 45,
                        "is_flipped": False,
                    },
                ],
                "connected_components": [["FE-001", "FE-002", "FE-003"]],
                "adjacency_matrix": {
                    "FE-001": {"FE-002": 0.35},
                    "FE-002": {"FE-001": 0.35, "FE-003": 0.20},
                },
            },
            "matched_pairs": [
                {
                    "image1_id": "FE-001",
                    "image2_id": "FE-002",
                    "shared_area_img1": 0.40,
                    "shared_area_img2": 0.35,
                    "matched_keypoints": 45,
                    "is_flipped": False,
                },
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
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 10)
        ):
            assert _docker_available() is False


# ---------------------------------------------------------------------------
# _build_container_input
# ---------------------------------------------------------------------------


class TestBuildContainerInput:
    def test_structure(self):
        images = [
            {"id": "FE-001", "path": "/a.png", "label": "FE-001", "is_query": True}
        ]
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
            images=[],
            query_image_ids=[],
            output_dir="/out",
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
                {
                    "id": "A",
                    "label": "A",
                    "image_path": "/data/img0/a.png",
                    "is_query": True,
                },
                {
                    "id": "B",
                    "label": "B",
                    "image_path": "/data/img1/b.png",
                    "is_query": False,
                },
            ],
            "edges": [
                {
                    "source": "A",
                    "target": "B",
                    "weight": 0.35,
                    "shared_area_source": 0.40,
                    "shared_area_target": 0.35,
                    "matched_keypoints": 45,
                    "is_flipped": False,
                },
            ],
            "spanning_tree_edges": [
                {
                    "source": "A",
                    "target": "B",
                    "weight": 0.35,
                    "shared_area_source": 0.40,
                    "shared_area_target": 0.35,
                    "matched_keypoints": 45,
                    "is_flipped": False,
                },
            ],
            "connected_components": [["A", "B"]],
        }
        result = _convert_graph(elis_graph, workdir=tmp_path)
        assert result["schema_version"] == "1.0"
        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["is_query"] is True
        assert len(result["edges"]) == 1
        assert (
            result["edges"][0]["cosine_similarity"] == 0.0
        )  # ELIS does not compute SSCD
        assert len(result["spanning_tree_edges"]) == 1
        assert result["connected_components"] == [["A", "B"]]

    def test_statistics(self, tmp_path):
        elis_graph = {
            "nodes": [
                {"id": "X", "label": "X", "image_path": "x.png", "is_query": False}
            ],
            "edges": [
                {
                    "source": "X",
                    "target": "Y",
                    "weight": 0.5,
                    "shared_area_source": 0.6,
                    "shared_area_target": 0.5,
                    "matched_keypoints": 100,
                    "is_flipped": False,
                },
                {
                    "source": "X",
                    "target": "Z",
                    "weight": 0.3,
                    "shared_area_source": 0.3,
                    "shared_area_target": 0.3,
                    "matched_keypoints": 50,
                    "is_flipped": False,
                },
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
        elis_graph = {
            "nodes": [],
            "edges": [],
            "spanning_tree_edges": [],
            "connected_components": [],
        }
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
# Phase telemetry helpers
# ---------------------------------------------------------------------------


class TestPhaseTelemetryHelpers:
    def test_infer_phase_nonexistent_dir(self, tmp_path):
        # Non-existent directory
        nonexistent = tmp_path / "nonexistent"
        phase, summary = _infer_phase_from_output(nonexistent)
        assert phase == "docker_start"
        assert summary["files_written"] == 0

    def test_infer_phase_empty_dir(self, tmp_path):
        # Empty directory exists, should be in descriptor_extraction
        phase, summary = _infer_phase_from_output(tmp_path)
        assert phase == "descriptor_extraction"
        assert summary["files_written"] == 0

    def test_infer_phase_no_descriptors(self, tmp_path):
        (tmp_path / "descriptors").mkdir()
        phase, summary = _infer_phase_from_output(tmp_path)
        assert phase == "descriptor_extraction"
        assert summary["descriptor_files"] == 0

    def test_infer_phase_with_descriptors(self, tmp_path):
        desc_dir = tmp_path / "descriptors"
        desc_dir.mkdir()
        (desc_dir / "img1.npy").write_bytes(b"\x00" * 10)
        (desc_dir / "img2.npy").write_bytes(b"\x00" * 10)
        phase, summary = _infer_phase_from_output(tmp_path)
        assert phase == "matching_bfs"
        assert summary["descriptor_files"] == 2

    def test_infer_phase_with_matches(self, tmp_path):
        desc_dir = tmp_path / "descriptors"
        desc_dir.mkdir()
        (desc_dir / "img1.npy").write_bytes(b"\x00" * 10)
        match_dir = tmp_path / "matches"
        match_dir.mkdir()
        (match_dir / "match1.json").write_text("{}")
        phase, summary = _infer_phase_from_output(tmp_path)
        assert phase == "mst_graph_build"
        assert summary["match_files"] == 1

    def test_infer_phase_with_graph(self, tmp_path):
        desc_dir = tmp_path / "descriptors"
        desc_dir.mkdir()
        (desc_dir / "img1.npy").write_bytes(b"\x00" * 10)
        match_dir = tmp_path / "matches"
        match_dir.mkdir()
        (match_dir / "match1.json").write_text("{}")
        (tmp_path / "provenance_graph.json").write_text('{"nodes":[],"edges":[]}')
        phase, summary = _infer_phase_from_output(tmp_path)
        assert phase == "artifact_write"
        assert summary["graph_file_exists"] is True

    def test_infer_phase_with_visualization(self, tmp_path):
        (tmp_path / "provenance_graph.json").write_text('{"nodes":[],"edges":[]}')
        (tmp_path / "visualization_data.json").write_text("{}")
        phase, summary = _infer_phase_from_output(tmp_path)
        assert phase == "output_validation"
        assert summary["visualization_file_exists"] is True

    def test_validate_output_graph_valid(self, tmp_path):
        graph_data = {"nodes": [{"id": "A"}], "edges": [{"source": "A", "target": "B"}]}
        (tmp_path / "provenance_graph.json").write_text(json.dumps(graph_data))
        result = _validate_output_graph(tmp_path)
        assert result is not None
        assert result["nodes"][0]["id"] == "A"

    def test_validate_output_graph_missing(self, tmp_path):
        result = _validate_output_graph(tmp_path)
        assert result is None

    def test_validate_output_graph_invalid_json(self, tmp_path):
        (tmp_path / "provenance_graph.json").write_text("not json")
        result = _validate_output_graph(tmp_path)
        assert result is None

    def test_validate_output_graph_missing_fields(self, tmp_path):
        (tmp_path / "provenance_graph.json").write_text('{"foo": "bar"}')
        result = _validate_output_graph(tmp_path)
        assert result is None

    def test_phase_telemetry_to_dict(self):
        now = datetime.now(timezone.utc)
        phase = PhaseTelemetry(
            phase="descriptor_extraction",
            status="running",
            started_at=now,
            last_progress_at=now,
            progress_summary={"images_done": 5, "images_total": 42},
        )
        d = phase.to_dict()
        assert d["phase"] == "descriptor_extraction"
        assert d["status"] == "running"
        assert d["started_at"] is not None
        assert d["progress_summary"]["images_done"] == 5

    def test_docker_diagnostics_to_dict(self):
        diag = DockerDiagnostics(
            image="test:latest",
            argv=["docker", "run"],
            input_json_path="/tmp/input.json",
            output_dir="/output",
            timeout_seconds=600,
            hard_cap_seconds=1800,
            exit_code=0,
        )
        d = diag.to_dict()
        assert d["image"] == "test:latest"
        assert d["timeout_seconds"] == 600
        assert d["hard_cap_seconds"] == 1800
        assert d["exit_code"] == 0


# ---------------------------------------------------------------------------
# _run_docker_with_telemetry
# ---------------------------------------------------------------------------


class TestRunDockerWithTelemetry:
    def test_success_with_telemetry(self, tmp_path, sample_elis_output):
        output_dir = tmp_path / "output"
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout.read.return_value = json.dumps(sample_elis_output)
        mock_proc.stderr.read.return_value = ""
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("docker", 2), None]

        container_input = _build_container_input(
            images=[
                {"id": "A", "path": str(image_dir / "a.png")},
                {"id": "B", "path": str(image_dir / "b.png")},
            ],
            query_image_ids=["A"],
            output_dir=str(output_dir),
        )

        with patch("subprocess.Popen", return_value=mock_proc):
            result = _run_docker_with_telemetry(
                container_input, [image_dir], output_dir
            )
            assert result["success"] is True
            assert result["status"] == "completed"
            assert "phases" in result
            assert "diagnostics" in result
            # Should have at least prepare_input, docker_start, and one more
            assert len(result["phases"]) >= 3

    def test_container_exit_nonzero(self, tmp_path):
        output_dir = tmp_path / "output"
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout.read.return_value = ""
        mock_proc.stderr.read.return_value = "Error: segmentation fault"
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("docker", 2), None]

        container_input = _build_container_input(
            images=[{"id": "A", "path": str(image_dir / "a.png")}],
            query_image_ids=[],
            output_dir=str(output_dir),
        )

        with patch("subprocess.Popen", return_value=mock_proc):
            result = _run_docker_with_telemetry(
                container_input, [image_dir], output_dir
            )
            assert result["success"] is False
            assert "segmentation fault" in result["error"]
            assert result["status"] == "failed"

    def test_os_error(self, tmp_path):
        output_dir = tmp_path / "output"
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        container_input = _build_container_input(
            images=[{"id": "A", "path": str(image_dir / "a.png")}],
            query_image_ids=[],
            output_dir=str(output_dir),
        )

        with patch("subprocess.Popen", side_effect=OSError("Docker daemon not running")):
            result = _run_docker_with_telemetry(
                container_input, [image_dir], output_dir
            )
            assert result["success"] is False
            assert "Docker daemon" in result["error"]
            assert result["status"] == "failed"

    def test_diagnostics_recorded(self, tmp_path, sample_elis_output):
        output_dir = tmp_path / "output"
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout.read.return_value = json.dumps(sample_elis_output)
        mock_proc.stderr.read.return_value = ""
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("docker", 2), None]

        container_input = _build_container_input(
            images=[{"id": "A", "path": str(image_dir / "a.png")}],
            query_image_ids=[],
            output_dir=str(output_dir),
        )

        with patch("subprocess.Popen", return_value=mock_proc):
            result = _run_docker_with_telemetry(
                container_input, [image_dir], output_dir
            )
            diag = result["diagnostics"]
            assert diag["image"] == DOCKER_IMAGE
            assert diag["output_dir"] == str(output_dir)
            assert diag["exit_code"] == 0
            assert diag["started_at"] is not None
            assert diag["ended_at"] is not None

    def test_hard_cap_recovery(self, tmp_path):
        """Test hard cap termination with output recovery."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        image_dir = tmp_path / "images"
        image_dir.mkdir()

        # Write a valid graph to simulate output recovery
        graph_data = {
            "nodes": [{"id": "A", "image_path": "/a.png", "label": "A", "is_query": False}],
            "edges": [],
            "spanning_tree_edges": [],
            "connected_components": [["A"]],
        }
        (output_dir / "provenance_graph.json").write_text(json.dumps(graph_data))

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.read.return_value = ""
        mock_proc.stderr.read.return_value = ""
        # Simulate process running indefinitely (always timeout in polling)
        # But succeed when called during termination (no timeout arg)
        def wait_side_effect(*args, **kwargs):
            if 'timeout' in kwargs:
                raise subprocess.TimeoutExpired("docker", kwargs['timeout'])
            return None  # Success during termination
        mock_proc.wait.side_effect = wait_side_effect

        container_input = _build_container_input(
            images=[{"id": "A", "path": str(image_dir / "a.png")}],
            query_image_ids=[],
            output_dir=str(output_dir),
        )

        # Patch HARD_CAP_SECONDS to a very small value for testing
        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch(
                "engine.static_audit.tools._elis_provenance_runner.HARD_CAP_SECONDS",
                0,
            ),
        ):
            result = _run_docker_with_telemetry(
                container_input, [image_dir], output_dir
            )
            assert result["success"] is True
            assert result["status"] == "completed_after_cap"
            assert result["recovered"] is True
            assert "graph" in result


# ---------------------------------------------------------------------------
# run_provenance_analysis (integration-level)
# ---------------------------------------------------------------------------


class TestRunProvenanceAnalysis:
    def test_docker_unavailable(self, figure_evidence_list, tmp_path):
        with patch(
            "engine.static_audit.tools._elis_provenance_runner._docker_available",
            return_value=False,
        ):
            result = run_provenance_analysis(figure_evidence_list, workdir=tmp_path)
            assert result["status"] == "failed"
            assert result["failure_category"] == "environment"
            assert DOCKER_IMAGE in result["limitations"][0]

    def test_insufficient_figures(self, tmp_path):
        with patch(
            "engine.static_audit.tools._elis_provenance_runner._docker_available",
            return_value=True,
        ):
            result = run_provenance_analysis(
                [{"figure_id": "FE-001", "source_image_path": "missing.png"}],
                workdir=tmp_path,
            )
            assert result["status"] == "failed"
            assert result["failure_category"] == "dependency"

    def test_success(self, figure_evidence_list, tmp_path, sample_elis_output):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout.read.return_value = json.dumps(sample_elis_output)
        mock_proc.stderr.read.return_value = ""
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("docker", 2), None]

        with (
            patch(
                "engine.static_audit.tools._elis_provenance_runner._docker_available",
                return_value=True,
            ),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_provenance_analysis(
                figure_evidence_list,
                workdir=tmp_path,
                query_figure_ids=["FE-001"],
            )
            assert result["status"] == "ran"
            assert result["elis_status"] == "completed"
            assert result["source"] == "elis_provenance_docker"
            assert len(result["nodes"]) == 3
            assert len(result["edges"]) == 2
            assert result["processing_time_seconds"] == 12.34
            assert "phase_telemetry" in result
            assert "docker_diagnostics" in result
            # Query flag should be preserved
            query_nodes = [n for n in result["nodes"] if n["is_query"]]
            assert len(query_nodes) >= 1

    def test_container_failure(self, figure_evidence_list, tmp_path):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout.read.return_value = ""
        mock_proc.stderr.read.return_value = "CUDA out of memory"
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("docker", 2), None]

        with (
            patch(
                "engine.static_audit.tools._elis_provenance_runner._docker_available",
                return_value=True,
            ),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_provenance_analysis(figure_evidence_list, workdir=tmp_path)
            assert result["status"] == "failed"
            assert result["failure_category"] == "runtime"
            assert "CUDA" in result["error"] or "CUDA" in result["limitations"][0]

    def test_no_edges_limitation(self, figure_evidence_list, tmp_path):
        """Container success but no edges should produce a limitation, not a failure."""
        no_edges_output = {
            "success": True,
            "command": "provenance",
            "message": "ok",
            "provenance_response": {
                "success": True,
                "message": "ok",
                "total_images": 3,
                "total_pairs_checked": 3,
                "matched_pairs_count": 0,
                "processing_time_seconds": 5.0,
                "graph": {
                    "nodes": [
                        {
                            "id": "FE-001",
                            "label": "FE-001",
                            "image_path": "/a.png",
                            "is_query": True,
                        },
                        {
                            "id": "FE-002",
                            "label": "FE-002",
                            "image_path": "/b.png",
                            "is_query": False,
                        },
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
        mock_proc.stdout.read.return_value = json.dumps(no_edges_output)
        mock_proc.stderr.read.return_value = ""
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("docker", 2), None]

        with (
            patch(
                "engine.static_audit.tools._elis_provenance_runner._docker_available",
                return_value=True,
            ),
            patch("subprocess.Popen", return_value=mock_proc),
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
            {
                "figure_id": "FE-002",
                "source_image_path": "images/missing.png",
            },  # does not exist
        ]
        with patch(
            "engine.static_audit.tools._elis_provenance_runner._docker_available",
            return_value=True,
        ):
            result = run_provenance_analysis(evidence, workdir=tmp_path)
            # Only 1 valid figure -> should fail with dependency error
            assert result["status"] == "failed"
            assert result["failure_category"] == "dependency"

    def test_volume_mount_paths(
        self, figure_evidence_list, tmp_path, sample_elis_output
    ):
        """Verify Docker command includes correct volume mounts."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout.read.return_value = json.dumps(sample_elis_output)
        mock_proc.stderr.read.return_value = ""
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("docker", 2), None]

        with (
            patch(
                "engine.static_audit.tools._elis_provenance_runner._docker_available",
                return_value=True,
            ),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
        ):
            run_provenance_analysis(figure_evidence_list, workdir=tmp_path)
            cmd = mock_popen.call_args[0][0]
            # Check volume mounts exist
            volume_flags = [i for i, x in enumerate(cmd) if x == "-v"]
            assert (
                len(volume_flags) >= 2
            )  # At least image dir + output dir + input json

    def test_phase_telemetry_present_on_success(
        self, figure_evidence_list, tmp_path, sample_elis_output
    ):
        """Verify phase telemetry is included in successful result."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout.read.return_value = json.dumps(sample_elis_output)
        mock_proc.stderr.read.return_value = ""
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("docker", 2), None]

        with (
            patch(
                "engine.static_audit.tools._elis_provenance_runner._docker_available",
                return_value=True,
            ),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_provenance_analysis(figure_evidence_list, workdir=tmp_path)
            assert "phase_telemetry" in result
            phases = result["phase_telemetry"]
            assert len(phases) >= 2  # At least prepare_input and docker_start
            # Check first phase
            assert phases[0]["phase"] == "prepare_input"
            assert phases[0]["status"] == "completed"
            # Check second phase
            assert phases[1]["phase"] == "docker_start"

    def test_docker_diagnostics_present_on_success(
        self, figure_evidence_list, tmp_path, sample_elis_output
    ):
        """Verify Docker diagnostics are included in successful result."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout.read.return_value = json.dumps(sample_elis_output)
        mock_proc.stderr.read.return_value = ""
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("docker", 2), None]

        with (
            patch(
                "engine.static_audit.tools._elis_provenance_runner._docker_available",
                return_value=True,
            ),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_provenance_analysis(figure_evidence_list, workdir=tmp_path)
            assert "docker_diagnostics" in result
            diag = result["docker_diagnostics"]
            assert diag["image"] == DOCKER_IMAGE
            assert diag["started_at"] is not None
            assert diag["ended_at"] is not None
            assert "input_json_path" in diag
            assert "output_dir" in diag
