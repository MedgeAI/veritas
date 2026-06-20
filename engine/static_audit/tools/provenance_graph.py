"""Provenance graph builder for cross-figure content sharing analysis.

Builds a provenance graph from figure images by delegating to the ELIS
provenance-analysis adapter (provenance-adapter). The adapter performs:
1. RootSIFT descriptor extraction for all figures
2. Recursive BFS matching with expansion (max_depth)
3. MST-based provenance graph construction
4. Connected components analysis

This replaces the previous SSCD embedding + cosine similarity pre-filtering
approach with the more comprehensive ELIS provenance-analysis pipeline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from engine.static_audit.tools._elis_provenance_runner import run_provenance_analysis

logger = logging.getLogger(__name__)


def build_provenance_graph(
    figure_evidence: list[dict[str, Any]],
    *,
    workdir: Path,
    query_figure_ids: list[str] | None = None,
    descriptor_type: str = "cv_rsift",
    min_keypoints: int = 20,
    min_area: float = 0.01,
    max_depth: int = 3,
    check_flip: bool = True,
    max_workers: int = 4,
    timeout: int = 600,
) -> dict[str, Any]:
    """Build a provenance graph from figure evidence using ELIS provenance-adapter.

    The ELIS provenance-analysis adapter performs recursive BFS matching with
    expansion, starting from query images (or all images if no query specified)
    and expanding outward up to max_depth levels.

    Args:
        figure_evidence: List of figure evidence dicts with figure_id and source_image_path.
        workdir: Working directory for resolving paths and writing output.
        query_figure_ids: Optional list of figure IDs to start BFS expansion from.
            If None, all figures are treated as queries (all-pairs matching).
        descriptor_type: Keypoint descriptor type (cv_rsift, cv_sift, vlfeat_sift_heq).
        min_keypoints: Minimum matched keypoints for a valid edge.
        min_area: Minimum shared area threshold (0-1).
        max_depth: Maximum BFS expansion depth (1 = no expansion, 2-10 = expansion).
        check_flip: Whether to check for horizontal flips during matching.
        max_workers: Maximum parallel workers inside the Docker container.
        timeout: Docker execution timeout in seconds.

    Returns:
        Canonical provenance graph dict with nodes, edges, spanning_tree_edges,
        connected_components, statistics, and visualization_data.
    """
    # Collect figures with valid image paths
    figures_with_paths: list[tuple[str, Path]] = []
    for fig in figure_evidence:
        fid = str(fig.get("figure_id") or "")
        source = str(fig.get("source_image_path") or "")
        if not fid or not source:
            continue
        fig_path = workdir / source
        if fig_path.exists():
            figures_with_paths.append((fid, fig_path))

    if len(figures_with_paths) < 2:
        return {
            "schema_version": "1.0",
            "status": "failed",
            "failure_category": "dependency",
            "error": "Not enough figures with valid image paths.",
            "nodes": [], "edges": [], "statistics": {},
        }

    # If no query figures specified, treat all as queries (all-pairs matching)
    if not query_figure_ids:
        query_figure_ids = [fid for fid, _ in figures_with_paths]

    # Delegate to ELIS provenance-adapter
    try:
        result = run_provenance_analysis(
            figure_evidence=figure_evidence,
            workdir=workdir,
            query_figure_ids=query_figure_ids,
            descriptor_type=descriptor_type,
            min_keypoints=min_keypoints,
            min_area=min_area,
            check_flip=check_flip,
            max_workers=max_workers,
            timeout=timeout,
        )
    except Exception as exc:
        logger.exception("Provenance-adapter failed unexpectedly")
        return {
            "schema_version": "1.0",
            "status": "failed",
            "failure_category": "runtime",
            "error": f"Provenance-adapter failed: {exc}",
            "limitations": [f"Provenance-adapter failed unexpectedly: {exc}"],
            "nodes": [], "edges": [], "statistics": {},
        }

    # Add max_depth and descriptor_type metadata for downstream consumers
    if result.get("status") == "ran":
        result["max_depth"] = max_depth
        result["descriptor_type"] = descriptor_type

    return result
