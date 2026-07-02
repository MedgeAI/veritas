from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.static_audit.audit_config import provenance_relationship_config
from engine.static_audit._shared import resolve_artifact_path, write_json_artifact


def _edge_score(edge: dict[str, Any]) -> float:
    for key in ("score", "weight", "cosine_similarity"):
        value = edge.get(key)
        if isinstance(value, int | float):
            return float(value)
    return 0.0


def _node_labels(graph: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        label = str(node.get("label") or node_id)
        if node_id:
            labels[node_id] = label
    return labels


def provenance_edge_to_findings(
    graph: dict[str, Any],
    *,
    threshold: float,
    max_items: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Convert strong provenance graph edges into reviewable findings."""
    edges = [edge for edge in (graph.get("edges") or []) if isinstance(edge, dict)]
    scored = sorted(edges, key=_edge_score, reverse=True)
    emitted_edges = [edge for edge in scored if _edge_score(edge) >= threshold][
        :max_items
    ]
    labels = _node_labels(graph)

    findings: list[dict[str, Any]] = []
    for index, edge in enumerate(emitted_edges, start=1):
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        score = round(_edge_score(edge), 4)
        source_label = labels.get(source, source)
        target_label = labels.get(target, target)
        findings.append(
            {
                "finding_id": f"VRL-{index:04d}",
                "category": "visual_provenance_relationship",
                "risk_level": "medium",
                "source_figure": source_label,
                "target_figure": target_label,
                "source_node": source,
                "target_node": target,
                "relationship_type": "near_duplicate_or_derived",
                "score": score,
                "matched_keypoints": edge.get("matched_keypoints"),
                "shared_area_source": edge.get("shared_area_source"),
                "shared_area_target": edge.get("shared_area_target"),
                "benign_explanations": [
                    "same experiment repeated",
                    "authorized reuse with cropping or resizing",
                    "shared schematic or template element",
                ],
                "summary": (
                    f"{source_label} and {target_label} have provenance graph "
                    f"similarity score {score:.2f}; manual review should verify "
                    "whether they represent independent images."
                ),
                "review_question": (
                    f"{source_label} 和 {target_label} 的图像溯源关系分数为 "
                    f"{score:.2f}，是否为独立实验图像或已声明复用？"
                ),
                "evidence_refs": [
                    f"visual/provenance_graph.json:edge-{index}",
                ],
                "metadata": {
                    "source_artifact": "provenance_graph.json",
                    "threshold": threshold,
                    "raw_edge": edge,
                },
            }
        )

    top_edge = scored[0] if scored else None
    filtered = {
        "schema_version": "provenance_edge_filter.v1",
        "total_edges": len(edges),
        "threshold": threshold,
        "emitted_findings": len(findings),
        "top_score": round(_edge_score(top_edge), 4) if top_edge else None,
        "top_score_edge": top_edge,
        "filter_reason": None
        if findings
        else (
            "all_edges_below_threshold"
            if edges
            else "no_edges"
        ),
    }
    return findings, filtered


def write_provenance_relationship_artifacts(
    workdir: Path,
    graph: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    threshold, max_items = provenance_relationship_config()
    findings, filtered = provenance_edge_to_findings(
        graph,
        threshold=threshold,
        max_items=max_items,
    )
    stats = graph.get("statistics") if isinstance(graph.get("statistics"), dict) else {}
    relationship_doc = {
        "schema_version": "visual_relationship_findings.v1",
        "summary": {
            "graph_nodes": stats.get("node_count", len(graph.get("nodes") or [])),
            "graph_edges": stats.get("edge_count", len(graph.get("edges") or [])),
            "emitted_relationship_findings": len(findings),
            "components": stats.get(
                "component_count", len(graph.get("connected_components") or [])
            ),
            "filtered_out_path": "visual/provenance_edge_filtered.json",
        },
        "findings": findings,
    }
    write_json_artifact(
        resolve_artifact_path(workdir, "visual_relationship_findings.json"),
        relationship_doc,
    )
    write_json_artifact(
        resolve_artifact_path(workdir, "provenance_edge_filtered.json"),
        filtered,
    )
    return findings, relationship_doc, filtered
