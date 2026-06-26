"""Layer grouping for report findings (PRD2-T7).

This module provides functions to group findings into three layers based on
their risk level and category. The layer classification is a pure function
that can be independently tested and used by both the simple VerificationReport
system and the complex static audit HTML report.

Layer definitions (from PRD section 5):
    Layer 1 (高置信度发现): HIGH/CRITICAL risk findings that indicate
        clear data integrity issues (pair forensics HIGH, formula derived
        columns HIGH, TruFor HIGH, Copy-Move confirmed).

    Layer 2 (需人工判断): MEDIUM risk findings, plus HIGH-risk Paperconan
        numeric forensics anomalies that need human interpretation.

    Layer 3 (其他信号): LOW/INFO/CONTEXT risk findings, plus duplicate
        row vectors (DRV) and methodology review notes that are informational.

The classify_finding function is defined in engine/static_audit/_shared.py
to break the circular dependency pattern. This module re-exports it and
provides the grouping logic.
"""

from __future__ import annotations

from typing import Any

from engine.static_audit._shared import classify_finding


def group_findings_by_layer(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group findings into three report layers.

    Each finding is classified using classify_finding() and placed into
    layer_1, layer_2, or layer_3. Each finding dict is copied and annotated
    with a '_layer' field indicating its assigned layer.

    Args:
        findings: List of finding dicts. Each finding should have at least
            'risk_level' and optionally 'category' and 'source_artifact'.

    Returns:
        Dict with keys 'layer_1', 'layer_2', 'layer_3', each mapping to a
        list of finding dicts annotated with '_layer'.
    """
    result: dict[str, list[dict[str, Any]]] = {
        "layer_1": [],
        "layer_2": [],
        "layer_3": [],
    }

    for finding in findings:
        if not isinstance(finding, dict):
            continue

        layer = classify_finding(finding)
        finding_copy = dict(finding)
        finding_copy["_layer"] = layer
        result[layer].append(finding_copy)

    return result


# Layer metadata for rendering
LAYER_METADATA = {
    "layer_1": {
        "title": "高置信度发现",
        "description": "这些记录表明存在明确的数据完整性问题，需要优先关注",
        "default_open": True,
    },
    "layer_2": {
        "title": "需人工判断",
        "description": "这些记录需要人工复核以判断是否为真实问题",
        "default_open": True,
    },
    "layer_3": {
        "title": "其他信号",
        "description": "信息性记录，默认折叠，可选择性查看",
        "default_open": False,
    },
}
