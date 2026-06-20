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
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

logger = logging.getLogger(__name__)

DOCKER_IMAGE = "veritas-elis-provenance:latest"


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
# Docker invocation
# ---------------------------------------------------------------------------


def _run_docker(
    container_input: dict[str, Any],
    host_image_dirs: list[Path],
    host_output_dir: Path,
    timeout: int = 600,
) -> dict[str, Any]:
    """Execute the provenance-analysis Docker container.

    Returns the parsed ``ContainerOutput`` dict.
    """
    host_output_dir.mkdir(parents=True, exist_ok=True)

    # Build volume mounts.  All unique image parent directories are mounted
    # read-only under ``/data/imgN``; the output directory is mounted
    # read-write under ``/output``.
    volume_args: list[str] = []
    path_remap: dict[str, str] = {}  # host absolute -> container path

    for idx, img_dir in enumerate({str(p) for p in host_image_dirs}):
        container_mount = f"/data/img{idx}"
        volume_args.extend(["-v", f"{img_dir}:{container_mount}:ro"])
        path_remap[img_dir] = container_mount

    abs_output = host_output_dir.resolve()
    volume_args.extend(["-v", f"{abs_output}:/output"])

    # Rewrite image paths in the container input to container-relative paths
    container_input_copy = json.loads(json.dumps(container_input))  # deep copy
    for img in container_input_copy["provenance_request"]["images"]:
        host_path = img["path"]
        for host_prefix, container_prefix in path_remap.items():
            if host_path.startswith(host_prefix):
                img["path"] = host_path.replace(host_prefix, container_prefix, 1)
                break
    container_input_copy["provenance_request"]["output_dir"] = "/output"

    # Write input JSON to a temp file
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

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            stderr_snippet = (proc.stderr or "").strip()[-500:]
            return {
                "success": False,
                "error": f"Container exit {proc.returncode}: {stderr_snippet}",
            }
        return _parse_container_output(proc.stdout)
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Docker container timed out after {timeout}s",
        }
    except OSError as exc:
        return {"success": False, "error": str(exc)}
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
        Docker execution timeout in seconds.

    Returns
    -------
    dict
        Canonical provenance graph dict compatible with
        ``provenance_graph.build_provenance_graph`` output format.
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

    result = _run_docker(
        container_input=container_input,
        host_image_dirs=list(image_dirs),
        host_output_dir=output_dir,
        timeout=timeout,
    )

    if not result["success"]:
        error_msg = result.get("error", "Unknown error")
        limitations.append(f"ELIS provenance Docker container failed: {error_msg}")
        return _failed_result(
            failure_category="runtime",
            error=error_msg,
            limitations=limitations,
        )

    # Convert ELIS graph to Veritas format
    elis_graph = result.get("graph")
    if elis_graph is None:
        limitations.append("Container succeeded but returned no provenance graph.")
        return _failed_result(
            failure_category="runtime",
            error="No provenance graph in container output.",
            limitations=limitations,
        )

    graph = _convert_graph(elis_graph, workdir=workdir)
    graph["status"] = "ran"
    graph["candidate_pairs_tested"] = result.get("total_pairs_checked", 0)
    graph["edges_found"] = len(graph.get("edges", []))
    graph["processing_time_seconds"] = round(
        result.get("processing_time_seconds", 0.0), 2
    )
    graph["source"] = "elis_provenance_docker"

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
