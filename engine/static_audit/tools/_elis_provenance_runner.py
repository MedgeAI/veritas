"""ELIS provenance-analysis HTTP service adapter.

Wraps the ELIS provenance-analysis service (RootSIFT descriptor extraction,
recursive BFS matching, MST-based provenance graph construction) running
as a long-running HTTP service (veritas-elis-forensic-service:8771).

The service keeps the analysis engine warm across requests, eliminating
per-invocation Docker container startup overhead (~5s conda init + model
loading).

Failure isolation
-----------------
Service unavailability, HTTP errors and JSON parse failures are all
captured and returned as structured failure dicts; the caller never
sees an exception.

File I/O:
    The service reads images from a shared ``/data`` bind mount.  The
    adapter translates host paths to container paths (project root → /data)
    before sending, and translates back for result paths.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from engine.env import get_env
from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service URL and project root for path translation.
# ---------------------------------------------------------------------------

_SERVICE_URL: str = get_env(
    "ELIS_FORENSIC_URL", required=False, default="http://localhost:8771"
)

# Project root — the bind mount maps this to /data inside the container.
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

_HTTP_TIMEOUT = 600.0  # provenance analysis can take a while


def _client() -> httpx.Client:
    """Return an httpx client that bypasses env proxy settings for local calls."""
    return httpx.Client(base_url=_SERVICE_URL, timeout=_HTTP_TIMEOUT, trust_env=False)


# ---------------------------------------------------------------------------
# Path translation  (host ↔ container)
# ---------------------------------------------------------------------------


def _to_container_path(host_path: Path) -> str:
    """Translate a host absolute path to the container's ``/data/...`` path."""
    return str(host_path).replace(str(_PROJECT_ROOT), "/data", 1)


def _to_host_path(container_path: str) -> str:
    """Translate a container ``/data/...`` path back to host absolute path."""
    return container_path.replace("/data", str(_PROJECT_ROOT), 1)


# ---------------------------------------------------------------------------
# Service health check
# ---------------------------------------------------------------------------


def _service_available() -> bool:
    """Return True if the ELIS forensic service is reachable."""
    try:
        with _client() as c:
            resp = c.get("/health", timeout=5.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


# ---------------------------------------------------------------------------
# ELIS → Veritas graph conversion
# ---------------------------------------------------------------------------


def _convert_graph(
    elis_graph: dict[str, Any],
    *,
    workdir: Path,
) -> dict[str, Any]:
    """Convert ELIS ``ProvenanceGraphResult`` to Veritas provenance graph."""
    nodes = []
    for n in elis_graph.get("nodes", []):
        image_path = n.get("image_path", "")
        # Translate container path → host path, then make relative to workdir
        host_path = _to_host_path(image_path)
        try:
            image_path = str(Path(host_path).relative_to(workdir))
        except (ValueError, TypeError):
            image_path = host_path
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
                "cosine_similarity": 0.0,
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
# Output directory recovery
# ---------------------------------------------------------------------------


def _validate_output_graph(output_dir: Path) -> dict[str, Any] | None:
    """Validate and parse provenance_graph.json from output directory."""
    graph_file = output_dir / "provenance_graph.json"
    if not graph_file.exists():
        return None
    try:
        with open(graph_file) as f:
            data = json.load(f)
        if "nodes" in data and "edges" in data:
            return data
        return None
    except (json.JSONDecodeError, OSError):
        return None


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
    """Run ELIS provenance-analysis via the HTTP service.

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
        Maximum parallel workers inside the service.
    timeout:
        HTTP request timeout in seconds.

    Returns
    -------
    dict
        Canonical provenance graph dict compatible with
        ``provenance_graph.build_provenance_graph`` output format.
    """
    limitations: list[str] = []

    # Check service availability
    if not _service_available():
        limitations.append(
            f"ELIS forensic service unreachable at {_SERVICE_URL}. "
            f"Start with: docker compose -p vdev "
            f"-f deploy/docker-compose.forensics.yml up -d --build"
        )
        return _failed_result(
            failure_category="environment",
            error=f"ELIS forensic service unreachable at {_SERVICE_URL}.",
            limitations=limitations,
        )

    # Collect figures with valid image paths
    images_info: list[dict[str, Any]] = []

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
                "path": _to_container_path(abs_path),
                "label": fid,
                "is_query": fid in (query_figure_ids or []),
            }
        )

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
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build HTTP request payload
    payload = {
        "images": images_info,
        "query_image_ids": query_ids,
        "output_dir": _to_container_path(output_dir.resolve()),
        "descriptor_type": descriptor_type,
        "min_keypoints": min_keypoints,
        "min_area": min_area,
        "check_flip": check_flip,
        "parallel": True,
        "max_workers": max_workers,
        "save_descriptors": True,
    }

    # Make HTTP call
    try:
        with _client() as c:
            resp = c.post("/provenance", json=payload)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        error_msg = f"Service returned HTTP {exc.response.status_code}"
        limitations.append(f"ELIS forensic service error: {error_msg}")
        return _failed_result(
            failure_category="runtime",
            error=error_msg,
            limitations=limitations,
        )
    except httpx.HTTPError as exc:
        error_msg = f"HTTP call failed: {exc}"
        limitations.append(f"ELIS forensic service error: {error_msg}")
        return _failed_result(
            failure_category="runtime",
            error=error_msg,
            limitations=limitations,
        )

    # Check response
    if not data.get("success"):
        error_msg = data.get("message", "Unknown service error")
        limitations.append(f"ELIS provenance analysis failed: {error_msg}")
        return _failed_result(
            failure_category="runtime",
            error=error_msg,
            limitations=limitations,
        )

    elis_graph = data.get("graph")
    if elis_graph is None:
        # Try to recover from output directory
        recovered = _validate_output_graph(output_dir)
        if recovered:
            elis_graph = recovered
        else:
            limitations.append("Service succeeded but returned no provenance graph.")
            return _failed_result(
                failure_category="runtime",
                error="No provenance graph in service response.",
                limitations=limitations,
            )

    # Convert ELIS graph to Veritas format
    graph = _convert_graph(elis_graph, workdir=workdir)
    graph["status"] = "ran"
    graph["elis_status"] = "completed"
    graph["candidate_pairs_tested"] = data.get("total_pairs_checked", 0)
    graph["edges_found"] = len(graph.get("edges", []))
    graph["processing_time_seconds"] = round(
        data.get("processing_time_seconds", 0.0), 2
    )
    graph["source"] = "elis_provenance_service"
    graph["phase_telemetry"] = [
        {
            "phase": "http_request",
            "status": "completed",
            "duration_seconds": graph["processing_time_seconds"],
        }
    ]
    graph["service_diagnostics"] = {
        "service_url": _SERVICE_URL,
        "total_images": data.get("total_images", 0),
        "matched_pairs_count": data.get("matched_pairs_count", 0),
    }

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
        "source": "elis_provenance_service",
        "nodes": [],
        "edges": [],
        "spanning_tree_edges": [],
        "connected_components": [],
        "statistics": {},
        "limitations": limitations or [],
    }
