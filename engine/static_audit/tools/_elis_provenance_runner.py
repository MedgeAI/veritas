"""ELIS provenance-analysis Docker subprocess adapter.

Wraps the ELIS provenance-analysis container (RootSIFT descriptor extraction,
recursive BFS matching, MST-based provenance graph construction) and converts
its ``ContainerOutput`` to Veritas provenance graph format.

Docker invocation
-----------------
The container image ``veritas-elis-provenance:latest`` exposes::

    ENTRYPOINT ["python", "-m", "src.main"]

This adapter uses the ``run`` sub-command with a JSON file containing a
``ContainerInput`` (``command=provenance``, ``provenance_request=...``).
The container writes ``ContainerOutput`` JSON to stdout.

Failure isolation
-----------------
Docker unavailability, container errors and JSON parse failures are all
captured and returned as structured failure dicts; the caller never sees an
exception.

Phase-level telemetry (PRD3-T8)
--------------------------------
The adapter tracks 7 phases to provide observability into slow tasks:

1. prepare_input - building ContainerInput JSON
2. docker_start - launching Docker container
3. descriptor_extraction - RootSIFT descriptor generation
4. matching_bfs - recursive BFS matching
5. mst_graph_build - MST graph construction
6. artifact_write - writing output artifacts
7. output_validation - validating output completeness

Each phase records: phase name, status, started_at, ended_at, duration_seconds,
last_progress_at, progress_summary.

Watchdog and hard cap:
- 5min inactivity watchdog: marks current phase as stalled (doesn't kill)
- 30min hard cap: terminates task, attempts output directory recovery

Status enum: running | stalled | needs_investigation | completed |
             completed_after_cap | failed

Docker diagnostics: image, argv, input path, output dir, timeout/cap,
started/ended, exit code, stderr summary, last phase, last progress ts.
No secrets are logged.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

logger = logging.getLogger(__name__)

DOCKER_IMAGE = "veritas-elis-provenance:latest"

# Phase telemetry configuration
INACTIVITY_WATCHDOG_SECONDS = 300  # 5 minutes
HARD_CAP_SECONDS = 1800  # 30 minutes
POLL_INTERVAL_SECONDS = 2  # Check progress every 2 seconds

# Status enum
ElisStatus = Literal[
    "running",
    "stalled",
    "needs_investigation",
    "completed",
    "completed_after_cap",
    "failed",
]

# Phase names
PhaseName = Literal[
    "prepare_input",
    "docker_start",
    "descriptor_extraction",
    "matching_bfs",
    "mst_graph_build",
    "artifact_write",
    "output_validation",
]


def _calc_duration(started_at: datetime | None, ended_at: datetime | None) -> float:
    """Calculate duration in seconds, returning 0.0 if either timestamp is None."""
    if started_at is not None and ended_at is not None:
        return (ended_at - started_at).total_seconds()
    return 0.0


@dataclass
class PhaseTelemetry:
    """Telemetry for a single phase."""

    phase: PhaseName
    status: Literal["running", "completed", "stalled", "failed"] = "running"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float = 0.0
    last_progress_at: datetime | None = None
    progress_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dict."""
        return {
            "phase": self.phase,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": round(self.duration_seconds, 2),
            "last_progress_at": (
                self.last_progress_at.isoformat() if self.last_progress_at else None
            ),
            "progress_summary": self.progress_summary,
        }


@dataclass
class DockerDiagnostics:
    """Docker invocation diagnostics (no secrets)."""

    image: str
    argv: list[str]
    input_json_path: str
    output_dir: str
    timeout_seconds: int
    hard_cap_seconds: int
    started_at: datetime | None = None
    ended_at: datetime | None = None
    exit_code: int | None = None
    stderr_summary: str = ""
    last_phase: str = ""
    last_progress_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dict."""
        return {
            "image": self.image,
            "argv": self.argv,
            "input_json_path": self.input_json_path,
            "output_dir": self.output_dir,
            "timeout_seconds": self.timeout_seconds,
            "hard_cap_seconds": self.hard_cap_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "exit_code": self.exit_code,
            "stderr_summary": self.stderr_summary,
            "last_phase": self.last_phase,
            "last_progress_at": (
                self.last_progress_at.isoformat() if self.last_progress_at else None
            ),
        }


# ---------------------------------------------------------------------------
# Docker availability
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    """Return True if Docker daemon is running and the image is present."""
    try:
        result = subprocess.run(
            ["docker", "images", "-q", DOCKER_IMAGE],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Container IO
# ---------------------------------------------------------------------------


def _build_container_input(
    images: list[dict[str, str]],
    query_image_ids: list[str],
    output_dir: str,
    *,
    descriptor_type: str = "cv_rsift",
    alignment_strategy: str = "CV_MAGSAC",
    matching_method: str = "BF",
    min_keypoints: int = 20,
    min_area: float = 0.01,
    check_flip: bool = True,
    parallel: bool = True,
    max_workers: int = 4,
    save_descriptors: bool = True,
) -> dict[str, Any]:
    """Build the ``ContainerInput`` JSON payload for the provenance command."""
    return {
        "command": "provenance",
        "provenance_request": {
            "images": images,
            "query_image_ids": query_image_ids,
            "descriptor_type": descriptor_type,
            "alignment_strategy": alignment_strategy,
            "matching_method": matching_method,
            "min_keypoints": min_keypoints,
            "min_area": min_area,
            "check_flip": check_flip,
            "output_dir": output_dir,
            "parallel": parallel,
            "max_workers": max_workers,
            "save_descriptors": save_descriptors,
        },
    }


def _parse_container_output(stdout: str) -> dict[str, Any]:
    """Parse ``ContainerOutput`` JSON and extract provenance_response.

    Returns a dict with at least ``success`` and ``error`` keys.
    On success, also contains the provenance graph fields.
    """
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Invalid JSON from container: {exc}"}

    if not data.get("success"):
        return {
            "success": False,
            "error": data.get("message", "Unknown container error"),
        }

    prov = data.get("provenance_response")
    if prov is None:
        return {"success": False, "error": "Missing provenance_response in output"}

    return {
        "success": prov.get("success", False),
        "message": prov.get("message", ""),
        "total_images": prov.get("total_images", 0),
        "total_pairs_checked": prov.get("total_pairs_checked", 0),
        "matched_pairs_count": prov.get("matched_pairs_count", 0),
        "processing_time_seconds": prov.get("processing_time_seconds", 0.0),
        "graph": prov.get("graph"),
        "matched_pairs": prov.get("matched_pairs"),
        "visualization_data": prov.get("visualization_data"),
        "output_files": prov.get("output_files"),
    }


# ---------------------------------------------------------------------------
# ELIS -> Veritas graph conversion
# ---------------------------------------------------------------------------


def _convert_graph(
    elis_graph: dict[str, Any],
    *,
    workdir: Path,
) -> dict[str, Any]:
    """Convert ELIS ``ProvenanceGraphResult`` to Veritas provenance graph.

    The ELIS graph uses ``ProvenanceGraphNode`` / ``ProvenanceGraphEdge``
    schemas; Veritas uses ``ProvenanceNode`` / ``ProvenanceEdge`` with the
    same core fields plus ``cosine_similarity`` (defaulted to 0.0 since
    ELIS does not compute SSCD embeddings).
    """
    nodes = []
    for n in elis_graph.get("nodes", []):
        image_path = n.get("image_path", "")
        # Make path relative to workdir when possible
        try:
            image_path = str(Path(image_path).relative_to(workdir))
        except (ValueError, TypeError):
            pass
        nodes.append(
            {
                "id": n.get("id", ""),
                "label": n.get("label", ""),
                "image_path": image_path,
                "is_query": n.get("is_query", False),
            }
        )

    edges = []
    for e in elis_graph.get("edges", []):
        edges.append(
            {
                "source": e.get("source", ""),
                "target": e.get("target", ""),
                "weight": round(e.get("weight", 0.0), 4),
                "shared_area_source": round(e.get("shared_area_source", 0.0), 4),
                "shared_area_target": round(e.get("shared_area_target", 0.0), 4),
                "matched_keypoints": e.get("matched_keypoints", 0),
                "is_flipped": e.get("is_flipped", False),
                "cosine_similarity": 0.0,  # ELIS uses RootSIFT, not SSCD
            }
        )

    spanning_tree = []
    for e in elis_graph.get("spanning_tree_edges") or []:
        spanning_tree.append(
            {
                "source": e.get("source", ""),
                "target": e.get("target", ""),
                "weight": round(e.get("weight", 0.0), 4),
            }
        )

    connected_components = elis_graph.get("connected_components") or []

    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/_elis_provenance_runner.py",
        "nodes": nodes,
        "edges": edges,
        "spanning_tree_edges": spanning_tree,
        "connected_components": connected_components,
        "statistics": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "component_count": len(connected_components),
            "max_weight": round(max((e["weight"] for e in edges), default=0.0), 4),
            "mean_weight": round(
                sum(e["weight"] for e in edges) / max(len(edges), 1), 4
            ),
        },
    }


# ---------------------------------------------------------------------------
# Phase inference from output directory
# ---------------------------------------------------------------------------


def _infer_phase_from_output(output_dir: Path) -> tuple[PhaseName, dict[str, Any]]:
    """Infer current phase and progress from output directory contents.

    ELIS provenance container writes artifacts in stages:
    - descriptors/*.npy -> descriptor_extraction phase
    - matches/*.json -> matching_bfs phase
    - provenance_graph.json -> mst_graph_build or artifact_write phase
    - visualization_data.json -> artifact_write phase

    Returns (phase_name, progress_summary).
    """
    if not output_dir.exists():
        return "docker_start", {"files_written": 0}

    # Count files by type
    descriptor_files = list((output_dir / "descriptors").glob("*.npy")) if (
        output_dir / "descriptors"
    ).exists() else []
    match_files = list((output_dir / "matches").glob("*.json")) if (
        output_dir / "matches"
    ).exists() else []
    graph_file = output_dir / "provenance_graph.json"
    viz_file = output_dir / "visualization_data.json"

    total_files = (
        len(descriptor_files)
        + len(match_files)
        + (1 if graph_file.exists() else 0)
        + (1 if viz_file.exists() else 0)
    )

    progress_summary = {
        "descriptor_files": len(descriptor_files),
        "match_files": len(match_files),
        "graph_file_exists": graph_file.exists(),
        "visualization_file_exists": viz_file.exists(),
        "files_written": total_files,
    }

    # Infer phase based on file presence (check from latest to earliest)
    if viz_file.exists():
        return "output_validation", progress_summary
    if graph_file.exists():
        return "artifact_write", progress_summary
    if match_files:
        return "mst_graph_build", progress_summary
    if descriptor_files:
        return "matching_bfs", progress_summary
    return "descriptor_extraction", progress_summary


def _validate_output_graph(output_dir: Path) -> dict[str, Any] | None:
    """Validate and parse provenance_graph.json from output directory.

    Returns parsed graph dict if valid, None otherwise.
    """
    graph_file = output_dir / "provenance_graph.json"
    if not graph_file.exists():
        return None

    try:
        with open(graph_file) as f:
            data = json.load(f)
        # Check minimal structure
        if "nodes" in data and "edges" in data:
            return data
        return None
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Docker invocation with phase telemetry
# ---------------------------------------------------------------------------


def _run_docker_with_telemetry(
    container_input: dict[str, Any],
    host_image_dirs: list[Path],
    host_output_dir: Path,
    timeout: int = 600,
) -> dict[str, Any]:
    """Execute Docker container with phase-level telemetry and watchdog.

    Returns dict with keys: success, result, phases, diagnostics, status.
    """
    host_output_dir.mkdir(parents=True, exist_ok=True)

    # Build volume mounts
    volume_args: list[str] = []
    path_remap: dict[str, str] = {}

    for idx, img_dir in enumerate({str(p) for p in host_image_dirs}):
        container_mount = f"/data/img{idx}"
        volume_args.extend(["-v", f"{img_dir}:{container_mount}:ro"])
        path_remap[img_dir] = container_mount

    abs_output = host_output_dir.resolve()
    volume_args.extend(["-v", f"{abs_output}:/output"])

    # Rewrite paths in container input
    container_input_copy = json.loads(json.dumps(container_input))
    for img in container_input_copy["provenance_request"]["images"]:
        host_path = img["path"]
        for host_prefix, container_prefix in path_remap.items():
            if host_path.startswith(host_prefix):
                img["path"] = host_path.replace(host_prefix, container_prefix, 1)
                break
    container_input_copy["provenance_request"]["output_dir"] = "/output"

    # Write input JSON
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        dir=host_output_dir,
    ) as tmp:
        json.dump(container_input_copy, tmp)
        input_json_path = tmp.name

    cmd = [
        "docker",
        "run",
        "--rm",
        *volume_args,
        "-v",
        f"{input_json_path}:/input.json:ro",
        DOCKER_IMAGE,
        "run",
        "--input",
        "/input.json",
    ]

    # Initialize telemetry
    phases: list[PhaseTelemetry] = []
    diagnostics = DockerDiagnostics(
        image=DOCKER_IMAGE,
        argv=cmd,
        input_json_path=input_json_path,
        output_dir=str(host_output_dir),
        timeout_seconds=timeout,
        hard_cap_seconds=HARD_CAP_SECONDS,
    )

    # Phase 1: prepare_input (already done)
    prepare_phase = PhaseTelemetry(
        phase="prepare_input",
        status="completed",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        duration_seconds=0.0,
    )
    phases.append(prepare_phase)

    # Phase 2: docker_start
    docker_start_phase = PhaseTelemetry(
        phase="docker_start",
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    phases.append(docker_start_phase)
    diagnostics.started_at = docker_start_phase.started_at

    # Initialize progress phase early so it's accessible in except block
    progress_phase = PhaseTelemetry(
        phase="descriptor_extraction",
        status="running",
        started_at=datetime.now(timezone.utc),
        last_progress_at=datetime.now(timezone.utc),
    )

    try:
        # Launch Docker process
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        docker_start_phase.ended_at = datetime.now(timezone.utc)
        docker_start_phase.duration_seconds = _calc_duration(docker_start_phase.started_at, docker_start_phase.ended_at)
        docker_start_phase.status = "completed"
        diagnostics.exit_code = None  # Process still running

        # Monitor phases via output directory
        last_progress_time = time.monotonic()
        last_progress_datetime = datetime.now(timezone.utc)
        last_file_count = 0
        current_phase_name: PhaseName = "descriptor_extraction"
        start_time = time.monotonic()
        stalled_marked = False

        # Phase 3-7: Monitor progress
        phases.append(progress_phase)

        while True:
            # Check if process finished
            try:
                proc.wait(timeout=POLL_INTERVAL_SECONDS)
                # Process finished
                diagnostics.exit_code = proc.returncode
                break
            except subprocess.TimeoutExpired:
                # Process still running, check progress
                pass

            # Check hard cap
            elapsed = time.monotonic() - start_time
            if elapsed >= HARD_CAP_SECONDS:
                logger.warning(
                    f"ELIS provenance hard cap reached ({HARD_CAP_SECONDS}s). "
                    f"Terminating process."
                )
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                except OSError:
                    # Process may already be dead
                    pass

                # Try to recover from output directory
                recovered_graph = _validate_output_graph(host_output_dir)
                diagnostics.ended_at = datetime.now(timezone.utc)
                diagnostics.stderr_summary = (
                    "Hard cap reached; attempted output recovery"
                )

                if recovered_graph:
                    # Mark current phase as completed
                    progress_phase.ended_at = diagnostics.ended_at
                    progress_phase.duration_seconds = _calc_duration(progress_phase.started_at, progress_phase.ended_at)
                    progress_phase.status = "completed"

                    # Add output_validation phase
                    validation_phase = PhaseTelemetry(
                        phase="output_validation",
                        status="completed",
                        started_at=diagnostics.ended_at,
                        ended_at=diagnostics.ended_at,
                        duration_seconds=0.0,
                    )
                    phases.append(validation_phase)

                    return {
                        "success": True,
                        "status": "completed_after_cap",
                        "recovered": True,
                        "graph": recovered_graph,
                        "phases": [p.to_dict() for p in phases],
                        "diagnostics": diagnostics.to_dict(),
                        "stdout": "",
                    }
                else:
                    # Mark current phase as stalled
                    progress_phase.ended_at = diagnostics.ended_at
                    progress_phase.duration_seconds = _calc_duration(progress_phase.started_at, progress_phase.ended_at)
                    progress_phase.status = "stalled"

                    return {
                        "success": False,
                        "status": "needs_investigation",
                        "error": f"Hard cap reached after {HARD_CAP_SECONDS}s",
                        "phases": [p.to_dict() for p in phases],
                        "diagnostics": diagnostics.to_dict(),
                        "stdout": "",
                    }

            # Check inactivity watchdog
            phase_name, progress_summary = _infer_phase_from_output(host_output_dir)
            current_file_count = progress_summary["files_written"]

            if current_file_count > last_file_count:
                # Progress detected
                last_progress_time = time.monotonic()
                last_progress_datetime = datetime.now(timezone.utc)
                last_file_count = current_file_count
                stalled_marked = False

                # Update progress phase
                progress_phase.last_progress_at = last_progress_datetime
                progress_phase.progress_summary = progress_summary

                # Check if phase changed
                if phase_name != current_phase_name:
                    # Complete current phase
                    progress_phase.ended_at = datetime.now(timezone.utc)
                    progress_phase.duration_seconds = _calc_duration(progress_phase.started_at, progress_phase.ended_at)
                    progress_phase.status = "completed"

                    # Start new phase
                    current_phase_name = phase_name
                    progress_phase = PhaseTelemetry(
                        phase=current_phase_name,
                        status="running",
                        started_at=datetime.now(timezone.utc),
                        last_progress_at=datetime.now(timezone.utc),
                        progress_summary=progress_summary,
                    )
                    phases.append(progress_phase)
            else:
                # No progress
                time_since_progress = time.monotonic() - last_progress_time
                if (
                    time_since_progress >= INACTIVITY_WATCHDOG_SECONDS
                    and not stalled_marked
                ):
                    logger.warning(
                        f"ELIS provenance inactivity watchdog: no progress for "
                        f"{int(time_since_progress)}s in phase {current_phase_name}"
                    )
                    progress_phase.status = "stalled"
                    diagnostics.last_phase = current_phase_name
                    diagnostics.last_progress_at = last_progress_datetime
                    stalled_marked = True

        # Process finished
        diagnostics.ended_at = datetime.now(timezone.utc)

        # Collect stderr
        stderr_output = proc.stderr.read() if proc.stderr else ""
        diagnostics.stderr_summary = stderr_output.strip()[-500:]

        # Complete current phase
        progress_phase.ended_at = diagnostics.ended_at
        progress_phase.duration_seconds = _calc_duration(progress_phase.started_at, progress_phase.ended_at)

        if proc.returncode != 0:
            progress_phase.status = "failed"
            return {
                "success": False,
                "status": "failed",
                "error": f"Container exit {proc.returncode}: {diagnostics.stderr_summary}",
                "phases": [p.to_dict() for p in phases],
                "diagnostics": diagnostics.to_dict(),
                "stdout": "",
            }

        # Collect stdout
        stdout_output = proc.stdout.read() if proc.stdout else ""
        progress_phase.status = "completed"

        # Add output_validation phase
        validation_phase = PhaseTelemetry(
            phase="output_validation",
            status="completed",
            started_at=diagnostics.ended_at,
            ended_at=diagnostics.ended_at,
            duration_seconds=0.0,
        )
        phases.append(validation_phase)

        diagnostics.last_phase = current_phase_name
        diagnostics.last_progress_at = last_progress_datetime

        # Parse container output to extract metadata
        parsed_output = {}
        if stdout_output:
            try:
                parsed_output = json.loads(stdout_output)
            except json.JSONDecodeError:
                pass

        # Extract metadata from provenance_response if present
        prov_response = parsed_output.get("provenance_response", {})

        return {
            "success": True,
            "status": "completed",
            "stdout": stdout_output,
            "phases": [p.to_dict() for p in phases],
            "diagnostics": diagnostics.to_dict(),
            "processing_time_seconds": prov_response.get("processing_time_seconds", 0.0),
            "total_pairs_checked": prov_response.get("total_pairs_checked", 0),
            "matched_pairs_count": prov_response.get("matched_pairs_count", 0),
            "graph": prov_response.get("graph"),
        }

    except OSError as exc:
        diagnostics.ended_at = datetime.now(timezone.utc)
        diagnostics.stderr_summary = str(exc)
        progress_phase.ended_at = diagnostics.ended_at
        progress_phase.duration_seconds = _calc_duration(progress_phase.started_at, progress_phase.ended_at)
        progress_phase.status = "failed"

        return {
            "success": False,
            "status": "failed",
            "error": str(exc),
            "phases": [p.to_dict() for p in phases],
            "diagnostics": diagnostics.to_dict(),
            "stdout": "",
        }
    finally:
        # Clean up temp file
        try:
            Path(input_json_path).unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_provenance_analysis(
    figure_evidence: list[dict[str, Any]],
    *,
    workdir: Path,
    query_figure_ids: list[str] | None = None,
    descriptor_type: str = "cv_rsift",
    min_keypoints: int = 20,
    min_area: float = 0.01,
    check_flip: bool = True,
    max_workers: int = 4,
    timeout: int = 600,
) -> dict[str, Any]:
    """Run ELIS provenance-analysis on figure images via Docker.

    Parameters
    ----------
    figure_evidence:
        List of figure evidence dicts with ``figure_id`` and
        ``source_image_path`` keys.
    workdir:
        Working directory for resolving image paths and writing output.
    query_figure_ids:
        Optional list of figure IDs to mark as query (highlighted in graph).
    descriptor_type:
        Keypoint descriptor type (``cv_rsift``, ``cv_sift``,
        ``vlfeat_sift_heq``).
    min_keypoints:
        Minimum matched keypoints for a valid edge.
    min_area:
        Minimum shared area threshold (0-1).
    check_flip:
        Whether to check for horizontal flips during matching.
    max_workers:
        Maximum parallel workers inside the container.
    timeout:
        Docker execution timeout in seconds (informational; hard cap is 30min).

    Returns
    -------
    dict
        Canonical provenance graph dict compatible with
        ``provenance_graph.build_provenance_graph`` output format.
        Includes phase-level telemetry and Docker diagnostics.
    """
    limitations: list[str] = []

    # Check Docker availability
    if not _docker_available():
        limitations.append(
            f"Docker image '{DOCKER_IMAGE}' not found. "
            f"Build with: docker build -t {DOCKER_IMAGE} "
            f"third_party/elis/system_modules/provenance-analysis/"
        )
        return _failed_result(
            failure_category="environment",
            error=f"Docker image '{DOCKER_IMAGE}' not available.",
            limitations=limitations,
        )

    # Collect figures with valid image paths
    images_info: list[dict[str, str]] = []
    image_dirs: set[Path] = set()

    for fig in figure_evidence:
        fid = str(fig.get("figure_id") or "")
        source = str(fig.get("source_image_path") or "")
        if not fid or not source:
            continue
        fig_path = workdir / source
        if not fig_path.exists():
            continue
        abs_path = fig_path.resolve()
        images_info.append(
            {
                "id": fid,
                "path": str(abs_path),
                "label": fid,
                "is_query": fid in (query_figure_ids or []),
            }
        )
        image_dirs.add(abs_path.parent)

    if len(images_info) < 2:
        limitations.append(
            f"Only {len(images_info)} figures with valid image paths; "
            f"need >= 2 for provenance analysis."
        )
        return _failed_result(
            failure_category="dependency",
            error="Not enough figures with valid image paths.",
            limitations=limitations,
        )

    query_ids = query_figure_ids or []
    output_dir = workdir / "provenance_elis"

    container_input = _build_container_input(
        images=images_info,
        query_image_ids=query_ids,
        output_dir=str(output_dir.resolve()),
        descriptor_type=descriptor_type,
        min_keypoints=min_keypoints,
        min_area=min_area,
        check_flip=check_flip,
        max_workers=max_workers,
    )

    result = _run_docker_with_telemetry(
        container_input=container_input,
        host_image_dirs=list(image_dirs),
        host_output_dir=output_dir,
        timeout=timeout,
    )

    # Extract telemetry
    phases = result.get("phases", [])
    diagnostics = result.get("diagnostics", {})
    status = result.get("status", "failed")

    if not result["success"]:
        # Check if we should attempt recovery from output directory
        if status == "needs_investigation":
            recovered_graph = _validate_output_graph(output_dir)
            if recovered_graph:
                # Recovery succeeded
                status = "completed_after_cap"
                result["success"] = True
                result["graph"] = recovered_graph
                result["recovered"] = True
                logger.info(
                    "ELIS provenance recovered complete graph from output directory "
                    "after hard cap"
                )
            else:
                error_msg = result.get("error", "Unknown error")
                limitations.append(f"ELIS provenance Docker container failed: {error_msg}")
                return _failed_result(
                    failure_category="runtime",
                    error=error_msg,
                    limitations=limitations,
                )
        else:
            error_msg = result.get("error", "Unknown error")
            limitations.append(f"ELIS provenance Docker container failed: {error_msg}")
            return _failed_result(
                failure_category="runtime",
                error=error_msg,
                limitations=limitations,
            )

    # Parse container output (or use recovered graph)
    if result.get("recovered"):
        elis_graph = result["graph"]
    else:
        parsed = _parse_container_output(result["stdout"])
        if not parsed["success"]:
            error_msg = parsed.get("error", "Unknown error")
            limitations.append(f"Failed to parse container output: {error_msg}")
            return _failed_result(
                failure_category="runtime",
                error=error_msg,
                limitations=limitations,
            )
        elis_graph = parsed.get("graph")

    if elis_graph is None:
        limitations.append("Container succeeded but returned no provenance graph.")
        return _failed_result(
            failure_category="runtime",
            error="No provenance graph in container output.",
            limitations=limitations,
        )

    # Convert ELIS graph to Veritas format
    graph = _convert_graph(elis_graph, workdir=workdir)
    graph["status"] = "ran"
    graph["elis_status"] = status
    graph["candidate_pairs_tested"] = result.get("total_pairs_checked", 0)
    graph["edges_found"] = len(graph.get("edges", []))
    graph["processing_time_seconds"] = round(
        result.get("processing_time_seconds", 0.0), 2
    )
    graph["source"] = "elis_provenance_docker"
    graph["phase_telemetry"] = phases
    graph["docker_diagnostics"] = diagnostics

    if not graph.get("edges"):
        limitations.append(
            "No provenance edges found. Figures do not share detectable content."
        )

    graph["limitations"] = limitations
    return graph


def _failed_result(
    *,
    failure_category: str,
    error: str,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Return a canonical failure dict."""
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/_elis_provenance_runner.py",
        "status": "failed",
        "failure_category": failure_category,
        "error": error,
        "source": "elis_provenance_docker",
        "nodes": [],
        "edges": [],
        "spanning_tree_edges": [],
        "connected_components": [],
        "statistics": {},
        "limitations": limitations or [],
    }
