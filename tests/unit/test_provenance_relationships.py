from __future__ import annotations

from engine.static_audit.visual_pipeline.provenance_relationships import (
    provenance_edge_to_findings,
)


def test_provenance_edge_to_findings_emits_top_edges() -> None:
    graph = {
        "nodes": [
            {"id": "FE-1", "label": "Fig. 2e"},
            {"id": "FE-2", "label": "Fig. 7e"},
        ],
        "edges": [
            {"source": "FE-1", "target": "FE-2", "weight": 0.91},
            {"source": "FE-1", "target": "FE-3", "weight": 0.5},
        ],
    }

    findings, filtered = provenance_edge_to_findings(
        graph, threshold=0.85, max_items=10
    )

    assert filtered["total_edges"] == 2
    assert filtered["emitted_findings"] == 1
    assert findings[0]["finding_id"] == "VRL-0001"
    assert findings[0]["source_figure"] == "Fig. 2e"
    assert findings[0]["target_figure"] == "Fig. 7e"


def test_provenance_edge_to_findings_records_filtered_out() -> None:
    graph = {
        "nodes": [],
        "edges": [{"source": "A", "target": "B", "weight": 0.72}],
    }

    findings, filtered = provenance_edge_to_findings(
        graph, threshold=0.85, max_items=10
    )

    assert findings == []
    assert filtered["top_score"] == 0.72
    assert filtered["filter_reason"] == "all_edges_below_threshold"
