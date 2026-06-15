"""Provenance graph builder for cross-figure content sharing analysis.

Builds a provenance graph from figure images by:
1. Computing dhash for all figures
2. Pre-filtering candidate pairs (hamming distance <= threshold)
3. Verifying candidates with RootSIFT+MAGSAC++ (via ELIS runner)
4. Building a weighted graph with shared_area as edge weights
5. Computing MST and connected components
6. Exporting vis.js-compatible visualization data

This follows the ELIS provenance-analysis architecture, replacing CBIR with
dhash for candidate selection (Veritas does not use Milvus).
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from engine.static_audit.visual_schemas import VISUAL_SCHEMA_VERSION

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ELIS_KEYPOINT_SRC = _REPO_ROOT / "third_party" / "elis" / "system_modules" / "copy-move-detection-keypoint" / "src"


@dataclass
class ProvenanceNode:
    id: str
    label: str
    image_path: str
    is_query: bool = False


@dataclass
class ProvenanceEdge:
    source: str
    target: str
    weight: float  # min(shared_area_source, shared_area_target)
    shared_area_source: float
    shared_area_target: float
    matched_keypoints: int
    is_flipped: bool


@dataclass
class ProvenanceGraph:
    nodes: list[ProvenanceNode] = field(default_factory=list)
    edges: list[ProvenanceEdge] = field(default_factory=list)
    spanning_tree_edges: list[ProvenanceEdge] = field(default_factory=list)
    connected_components: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "created_by": "engine/static_audit/tools/provenance_graph.py",
            "nodes": [
                {"id": n.id, "label": n.label, "image_path": n.image_path, "is_query": n.is_query}
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source, "target": e.target, "weight": round(e.weight, 4),
                    "shared_area_source": round(e.shared_area_source, 4),
                    "shared_area_target": round(e.shared_area_target, 4),
                    "matched_keypoints": e.matched_keypoints,
                    "is_flipped": e.is_flipped,
                }
                for e in self.edges
            ],
            "spanning_tree_edges": [
                {"source": e.source, "target": e.target, "weight": round(e.weight, 4)}
                for e in self.spanning_tree_edges
            ],
            "connected_components": self.connected_components,
            "statistics": {
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "component_count": len(self.connected_components),
                "max_weight": round(max((e.weight for e in self.edges), default=0.0), 4),
                "mean_weight": round(
                    sum(e.weight for e in self.edges) / max(len(self.edges), 1), 4
                ),
            },
            "visualization_data": _build_vis_data(self),
        }


def _dhash(path: Path, hash_size: int = 8) -> int:
    from PIL import Image
    with Image.open(path) as image:
        resized = image.convert("L").resize((hash_size + 1, hash_size))
        pixels = list(resized.getdata())
    value = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            value = (value << 1) | int(left > right)
    return value


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _find_dhash_candidates(
    figures: list[tuple[str, Path]],
    threshold: int = 20,
    max_pairs: int = 500,
) -> list[tuple[str, str, int]]:
    """Find candidate pairs by dhash hamming distance."""
    hashes = []
    for fid, path in figures:
        try:
            hashes.append((fid, path, _dhash(path)))
        except Exception:
            continue

    candidates = []
    for (fid_a, _, ha), (fid_b, _, hb) in combinations(hashes, 2):
        dist = _hamming(ha, hb)
        if dist <= threshold:
            candidates.append((fid_a, fid_b, dist))

    candidates.sort(key=lambda x: x[2])
    return candidates[:max_pairs]


def _verify_candidates_subprocess(
    candidates: list[tuple[str, str, int]],
    figure_paths: dict[str, Path],
    output_dir: Path,
    min_keypoints: int = 20,
    min_area: float = 0.01,
) -> list[dict[str, Any]]:
    """Verify candidate pairs via ELIS RootSIFT+MAGSAC++ runner."""
    if not candidates:
        return []

    pairs = []
    for idx, (fid_a, fid_b, dist) in enumerate(candidates):
        path_a = figure_paths.get(fid_a)
        path_b = figure_paths.get(fid_b)
        if path_a and path_b:
            pairs.append({
                "pair_id": f"prov-{idx:04d}",
                "source": str(path_a),
                "target": str(path_b),
                "source_figure_id": fid_a,
                "target_figure_id": fid_b,
            })

    if not pairs:
        return []

    cross_output = output_dir / "provenance_cross"
    cross_output.mkdir(parents=True, exist_ok=True)

    input_data = {
        "mode": "cross",
        "pairs": pairs,
        "output_dir": str(cross_output),
        "min_keypoints": min_keypoints,
        "min_area": min_area,
        "check_flip": True,
    }

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "engine.static_audit.tools._elis_copy_move_runner"],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=max(600, len(pairs) * 5),
            check=False,
        )
        if proc.returncode != 0:
            return []
        result = json.loads(proc.stdout)
        return result.get("results", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []


def _build_mst(nodes: list[str], edges: list[ProvenanceEdge]) -> list[ProvenanceEdge]:
    """Compute Maximum Spanning Tree using Kruskal's algorithm."""
    try:
        import networkx as nx
    except ImportError:
        # Fallback: simple sorted edge selection
        return _simple_mst(nodes, edges)

    G = nx.Graph()
    for n in nodes:
        G.add_node(n)
    for e in edges:
        G.add_edge(e.source, e.target, weight=e.weight, edge=e)

    mst = nx.maximum_spanning_tree(G)
    mst_edges = []
    for u, v, data in mst.edges(data=True):
        if "edge" in data:
            mst_edges.append(data["edge"])
    return mst_edges


def _simple_mst(nodes: list[str], edges: list[ProvenanceEdge]) -> list[ProvenanceEdge]:
    """Simple MST fallback without networkx."""
    # Union-Find
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    sorted_edges = sorted(edges, key=lambda e: e.weight, reverse=True)
    mst = []
    for e in sorted_edges:
        if union(e.source, e.target):
            mst.append(e)
        if len(mst) == len(nodes) - 1:
            break
    return mst


def _connected_components(nodes: list[str], edges: list[ProvenanceEdge]) -> list[list[str]]:
    """Find connected components via BFS."""
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for e in edges:
        adj[e.source].add(e.target)
        adj[e.target].add(e.source)

    visited: set[str] = set()
    components = []

    for node in nodes:
        if node in visited:
            continue
        component = []
        queue = [node]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            for neighbor in adj[current]:
                if neighbor not in visited:
                    queue.append(neighbor)
        components.append(sorted(component))

    return components


def _build_vis_data(graph: ProvenanceGraph) -> dict[str, Any]:
    """Build vis.js-compatible visualization data."""
    vis_nodes = []
    for i, node in enumerate(graph.nodes):
        vis_nodes.append({
            "id": node.id,
            "label": node.label,
            "title": f"{node.label} ({node.id})",
            "group": "query" if node.is_query else "figure",
            "shape": "image",
            "image": node.image_path,
        })

    vis_edges = []
    mst_keys = {(e.source, e.target) for e in graph.spanning_tree_edges}
    mst_keys.update({(e.target, e.source) for e in graph.spanning_tree_edges})

    for edge in graph.edges:
        is_mst = (edge.source, edge.target) in mst_keys or (edge.target, edge.source) in mst_keys
        vis_edges.append({
            "from": edge.source,
            "to": edge.target,
            "width": max(1, int(edge.weight * 20)),
            "title": f"shared_area={edge.weight:.2%}, kp={edge.matched_keypoints}, flip={edge.is_flipped}",
            "color": {"color": "#FF8C00" if edge.is_flipped else "#848484"},
            "dashes": not is_mst,
        })

    return {
        "nodes": vis_nodes,
        "edges": vis_edges,
        "components": graph.connected_components,
        "options": {
            "physics": {"enabled": True, "barnesHut": {"gravitationalConstant": -3000}},
            "interaction": {"hover": True, "tooltipDelay": 200},
        },
    }


def build_provenance_graph(
    figure_evidence: list[dict[str, Any]],
    *,
    workdir: Path,
    dhash_threshold: int = 20,
    max_candidate_pairs: int = 500,
    min_keypoints: int = 20,
    min_area: float = 0.01,
    query_figure_id: str | None = None,
) -> dict[str, Any]:
    """Build a provenance graph from figure evidence.

    Args:
        figure_evidence: List of figure evidence dicts.
        workdir: Working directory for resolving paths and writing output.
        dhash_threshold: Max hamming distance for dhash pre-filter.
        max_candidate_pairs: Max pairs to verify with keypoint matching.
        min_keypoints: Min matched keypoints for valid edge.
        min_area: Min shared area for valid edge.
        query_figure_id: Optional query figure (highlighted in visualization).

    Returns:
        Canonical provenance graph dict.
    """
    # Collect figures with valid image paths
    figures_with_paths: list[tuple[str, Path]] = []
    figure_path_map: dict[str, Path] = {}
    for fig in figure_evidence:
        fid = str(fig.get("figure_id") or "")
        source = str(fig.get("source_image_path") or "")
        if not fid or not source:
            continue
        fig_path = workdir / source
        if fig_path.exists():
            figures_with_paths.append((fid, fig_path))
            figure_path_map[fid] = fig_path

    if len(figures_with_paths) < 2:
        return {
            "schema_version": VISUAL_SCHEMA_VERSION,
            "status": "skipped",
            "error": "Not enough figures with valid image paths.",
            "nodes": [], "edges": [], "statistics": {},
        }

    # Phase 1: dhash pre-filtering
    candidates = _find_dhash_candidates(figures_with_paths, dhash_threshold, max_candidate_pairs)

    # Phase 2: RootSIFT+MAGSAC++ verification
    output_dir = workdir / "provenance"
    output_dir.mkdir(parents=True, exist_ok=True)
    verified = _verify_candidates_subprocess(
        candidates, figure_path_map, output_dir, min_keypoints, min_area,
    )

    # Phase 3: Build graph
    nodes = []
    for fid, path in figures_with_paths:
        try:
            rel_path = str(path.relative_to(workdir))
        except ValueError:
            rel_path = str(path)
        nodes.append(ProvenanceNode(
            id=fid,
            label=fid,
            image_path=rel_path,
            is_query=(fid == query_figure_id),
        ))

    edges = []
    node_ids = {n.id for n in nodes}
    for r in verified:
        if not r.get("success") or not r.get("found_forgery"):
            continue
        kp = r.get("matched_keypoints", 0)
        if kp < min_keypoints:
            continue
        src_area = r.get("shared_area_source", 0.0)
        tgt_area = r.get("shared_area_target", 0.0)
        weight = min(src_area, tgt_area)
        if weight < min_area:
            continue

        src_id = r.get("source_figure_id", "")
        tgt_id = r.get("target_figure_id", "")
        if src_id not in node_ids or tgt_id not in node_ids:
            continue

        edges.append(ProvenanceEdge(
            source=src_id,
            target=tgt_id,
            weight=weight,
            shared_area_source=src_area,
            shared_area_target=tgt_area,
            matched_keypoints=kp,
            is_flipped=r.get("is_flipped", False),
        ))

    # Phase 4: MST + connected components
    graph = ProvenanceGraph(nodes=nodes, edges=edges)
    graph.spanning_tree_edges = _build_mst([n.id for n in nodes], edges)
    graph.connected_components = _connected_components([n.id for n in nodes], edges)

    result = graph.to_dict()
    result["status"] = "ran"
    result["candidate_pairs_tested"] = len(candidates)
    result["edges_found"] = len(edges)
    result["limitations"] = []
    if not edges:
        result["limitations"].append(
            "No provenance edges found. Figures do not share detectable content."
        )

    return result
