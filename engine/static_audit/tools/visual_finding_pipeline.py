"""Visual finding pipeline: merge relationships and build findings.

Merges outputs from copy-move detection, exact duplicate detection,
and dHash similarity into a unified image_relationship list, then
converts high-score relationships into visual_findings with risk levels,
benign explanations, and manual review questions.

All text output is checked against FORBIDDEN_PHRASES from visual_schemas.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from engine.static_audit.visual_constants import (
    BENIGN_EXPLANATIONS,
    MANUAL_REVIEW_QUESTIONS,
    score_to_risk_level,
)
from engine.static_audit.visual_schemas import check_language_compliance


# ---------------------------------------------------------------------------
# Input normalization helpers
# ---------------------------------------------------------------------------


def _parse_score(value: Any) -> float:
    """Parse a score value from various input formats."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalized_score(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _panel_id(value: Any) -> str:
    """Convert a panel identifier to string."""
    return str(value) if value is not None else ""


def _optional_list(value: Any) -> list | None:
    """Return value if it is a list, else None."""
    return value if isinstance(value, list) else None


def _optional_str(value: Any) -> str | None:
    """Return value if it is a non-empty string, else None."""
    return value if isinstance(value, str) and value else None


def _normalize_path_key(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def _panel_image_index(panel_evidence: list[dict] | None) -> dict[str, str]:
    """Build image-path-to-panel-id index from canonical panel evidence."""
    index: dict[str, str] = {}
    if not panel_evidence:
        return index
    for panel in panel_evidence:
        if not isinstance(panel, dict) or not panel.get("panel_id"):
            continue
        panel_id = str(panel["panel_id"])
        candidates = [
            panel.get("crop_path"),
            panel.get("source_image_path"),
        ]
        metadata = panel.get("metadata") if isinstance(panel.get("metadata"), dict) else {}
        candidates.append(metadata.get("source_image_path"))
        for candidate in candidates:
            key = _normalize_path_key(candidate)
            if key:
                index[key] = panel_id
                index[Path(key).name] = panel_id
    return index


def _lookup_panel_id(value: Any, image_to_panel: dict[str, str]) -> str:
    direct = _panel_id(value)
    if direct and direct in set(image_to_panel.values()):
        return direct
    key = _normalize_path_key(value)
    if not key:
        return direct
    if key in image_to_panel:
        return image_to_panel[key]
    name = Path(key).name
    if name in image_to_panel:
        return image_to_panel[name]
    for indexed_path, panel_id in image_to_panel.items():
        if key.endswith(indexed_path) or indexed_path.endswith(key):
            return panel_id
    return direct


def _load_copy_move_relationships(
    copy_move_result: dict,
) -> list[dict]:
    """Extract relationship dicts from copy-move result."""
    raw = copy_move_result.get("relationships", [])
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append({
            "source_panel_id": _panel_id(item.get("source_panel_id")),
            "target_panel_id": _panel_id(item.get("target_panel_id")),
            "source_type": str(item.get("source_type") or "copy_move_single"),
            "score": _parse_score(item.get("score")),
            "match_method": item.get("match_method", "unknown"),
            "inlier_count": int(item.get("inlier_count", 0) or 0),
            "homography": _optional_list(item.get("homography")),
            "overlay_path": _optional_str(item.get("overlay_path")),
        })
    return out


def _load_exact_duplicate_relationships(
    exact_duplicates: dict,
    image_to_panel: dict[str, str] | None = None,
) -> list[dict]:
    """Extract relationship dicts from exact duplicates result."""
    image_to_panel = image_to_panel or {}
    raw = exact_duplicates.get("duplicates", [])
    out: list[dict] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            out.append({
                "source_panel_id": _lookup_panel_id(item.get("source_panel_id"), image_to_panel),
                "target_panel_id": _lookup_panel_id(item.get("target_panel_id"), image_to_panel),
                "score": 1.0,
                "match_method": "byte_hash",
                "inlier_count": 0,
                "homography": None,
                "overlay_path": _optional_str(item.get("overlay_path")),
            })
    duplicate_groups = exact_duplicates.get("duplicate_groups", [])
    if isinstance(duplicate_groups, list):
        for group in duplicate_groups:
            if not isinstance(group, list):
                continue
            panel_ids = [_lookup_panel_id(path, image_to_panel) for path in group]
            panel_ids = [pid for pid in panel_ids if pid]
            for src, tgt in combinations(panel_ids, 2):
                out.append({
                    "source_panel_id": src,
                    "target_panel_id": tgt,
                    "score": 1.0,
                    "match_method": "byte_hash",
                    "inlier_count": 0,
                    "homography": None,
                    "overlay_path": None,
                })
    return out


def _load_dhash_relationships(
    dhash_candidates: dict,
    image_to_panel: dict[str, str] | None = None,
) -> list[dict]:
    """Extract relationship dicts from dHash candidates result."""
    image_to_panel = image_to_panel or {}
    raw = dhash_candidates.get("candidates", [])
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        max_distance = _parse_score(item.get("max_distance")) or 64.0
        distance = _parse_score(item.get("distance"))
        score = item.get("score")
        if score is None and item.get("distance") is not None:
            score = max(0.0, 1.0 - (distance / max(max_distance, 1.0)))
        out.append({
            "source_panel_id": _lookup_panel_id(item.get("source_panel_id") or item.get("left_image"), image_to_panel),
            "target_panel_id": _lookup_panel_id(item.get("target_panel_id") or item.get("right_image"), image_to_panel),
            "score": _parse_score(score),
            "match_method": "dhash",
            "inlier_count": 0,
            "homography": None,
            "overlay_path": _optional_str(item.get("overlay_path")),
        })
    return out


# ---------------------------------------------------------------------------
# Relationship builder
# ---------------------------------------------------------------------------


def build_relationships(
    copy_move_result: dict | None = None,
    exact_duplicates: dict | None = None,
    dhash_candidates: dict | None = None,
    panel_evidence: list[dict] | None = None,
) -> list[dict]:
    """Merge copy-move, exact duplicates, and dHash into unified relationships.

    Deduplication priority:
      1. Exact duplicates win (score forced to 1.0, match_method="byte_hash").
      2. Copy-move relationships fill remaining pairs.
      3. dHash candidates fill remaining pairs.

    Deduplication key is the unordered panel pair (frozenset of two IDs).

    Args:
        copy_move_result: Output from copy-move detection tool.
            Expected shape: {"relationships": [{source_panel_id, target_panel_id,
            score, match_method, inlier_count, homography?, overlay_path?}, ...]}
        exact_duplicates: Output from exact duplicate detection.
            Expected shape: {"duplicates": [{source_panel_id, target_panel_id,
            overlay_path?}, ...]}
        dhash_candidates: Output from dHash similarity detection.
            Expected shape: {"candidates": [{source_panel_id, target_panel_id,
            score, overlay_path?}, ...]}

    Returns:
        List of relationship dicts matching ImageRelationship schema fields.
        Each dict has: relationship_id, source_type, source_panel_id,
        target_panel_id, score, match_method, inlier_count, homography,
        overlay_path, metadata.
    """
    image_to_panel = _panel_image_index(panel_evidence)
    exact_rels = (
        _load_exact_duplicate_relationships(exact_duplicates, image_to_panel)
        if exact_duplicates
        else []
    )
    cm_rels = (
        _load_copy_move_relationships(copy_move_result)
        if copy_move_result
        else []
    )
    dh_rels = (
        _load_dhash_relationships(dhash_candidates, image_to_panel)
        if dhash_candidates
        else []
    )

    result: list[dict] = []
    seen_pairs: set[frozenset[str]] = set()
    counter = 0

    def _pair_key(src: str, tgt: str) -> frozenset[str]:
        return frozenset({src, tgt})

    def _make_rel(
        *,
        src: str,
        tgt: str,
        score: float,
        source_type: str,
        match_method: str,
        inlier_count: int = 0,
        homography: list | None = None,
        overlay_path: str | None = None,
    ) -> dict:
        nonlocal counter
        counter += 1
        return {
            "relationship_id": f"IR-{counter:04d}",
            "source_type": source_type,
            "source_panel_id": src,
            "target_panel_id": tgt,
            "score": score,
            "match_method": match_method,
            "inlier_count": inlier_count,
            "homography": homography,
            "overlay_path": overlay_path,
            "metadata": {},
        }

    # Pass 1: exact duplicates (highest priority, score forced to 1.0)
    for rel in exact_rels:
        src, tgt = rel["source_panel_id"], rel["target_panel_id"]
        if not src or not tgt or src == tgt:
            continue
        pk = _pair_key(src, tgt)
        if pk in seen_pairs:
            continue
        seen_pairs.add(pk)
        result.append(_make_rel(
            src=src, tgt=tgt, score=1.0,
            source_type="exact_duplicate",
            match_method="byte_hash",
            overlay_path=rel.get("overlay_path"),
        ))

    # Pass 2: copy-move relationships
    for rel in cm_rels:
        src, tgt = rel["source_panel_id"], rel["target_panel_id"]
        if not src or not tgt or src == tgt:
            continue
        pk = _pair_key(src, tgt)
        if pk in seen_pairs:
            continue
        seen_pairs.add(pk)
        result.append(_make_rel(
            src=src, tgt=tgt, score=rel["score"],
            source_type=rel.get("source_type") or "copy_move_single",
            match_method=rel["match_method"],
            inlier_count=rel.get("inlier_count", 0),
            homography=rel.get("homography"),
            overlay_path=rel.get("overlay_path"),
        ))

    # Pass 3: dHash candidates
    for rel in dh_rels:
        src, tgt = rel["source_panel_id"], rel["target_panel_id"]
        if not src or not tgt or src == tgt:
            continue
        pk = _pair_key(src, tgt)
        if pk in seen_pairs:
            continue
        seen_pairs.add(pk)
        result.append(_make_rel(
            src=src, tgt=tgt, score=rel["score"],
            source_type="dhash_similar",
            match_method="dhash",
            overlay_path=rel.get("overlay_path"),
        ))

    return result


# ---------------------------------------------------------------------------
# Finding builder
# ---------------------------------------------------------------------------

RISK_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def _risk_rank(value: Any) -> int:
    return RISK_RANK.get(str(value), 0)


def _cap_risk_level(value: str, max_value: str) -> str:
    if _risk_rank(value) <= _risk_rank(max_value):
        return value
    return max_value


def _panel_extraction_quality(source_panel: dict, target_panel: dict) -> str:
    methods = {
        str(panel.get("extraction_method") or "")
        for panel in (source_panel, target_panel)
        if isinstance(panel, dict)
    }
    if "whole_figure_fallback" in methods:
        return "whole_figure_fallback"
    if methods:
        return "panel_level"
    return "unknown"


def _parent_figure_id(panel: dict, fallback_panel_id: str) -> str:
    if isinstance(panel, dict) and panel.get("parent_figure_id"):
        return str(panel.get("parent_figure_id"))
    text = str(fallback_panel_id or "")
    if "-" in text:
        return text.rsplit("-", 1)[0]
    return text


def _risk_max(values: list[Any], default: str = "medium") -> str:
    return max((str(value) for value in values if value), key=_risk_rank, default=default)


def _dedupe(values: list[Any], limit: int | None = None) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value)
        if text and text not in result:
            result.append(text)
        if limit is not None and len(result) >= limit:
            break
    return result


def _generate_summary(category: str, src: str, tgt: str) -> str:
    """Generate a language-compliant summary for a visual finding."""
    templates = {
        "copy_move_single": (
            "单图内 copy-move 检测发现 panel {src} 与 {tgt} 存在相似区域"
        ),
        "copy_move_cross": (
            "跨图 copy-move 检测发现 panel {src} 与 {tgt} 存在相似区域"
        ),
        "exact_duplicate": (
            "检测到 panel {src} 与 {tgt} 为字节级完全相同文件"
        ),
        "dhash_similar": (
            "dHash 检测发现 panel {src} 与 {tgt} 感知哈希相似"
        ),
    }
    template = templates.get(
        category,
        "图像关系检测发现 panel {src} 与 {tgt} 存在关联",
    )
    return template.format(src=src, tgt=tgt)


def build_visual_findings(
    relationships: list[dict],
    *,
    high_score_threshold: float = 0.4,
    critical_score_threshold: float = 0.7,
    panel_evidence: list[dict] | None = None,
) -> list[dict]:
    """Convert high-score relationships into visual findings.

    Only relationships with score >= high_score_threshold are converted.
    Each finding is enriched with:
      - risk_level: mapped from score via score_to_risk_level
      - benign_explanations: from BENIGN_EXPLANATIONS templates
      - manual_review_questions: from MANUAL_REVIEW_QUESTIONS templates
      - summary: generated from category template

    All text fields are verified against FORBIDDEN_PHRASES. Findings that
    fail language compliance are silently dropped.

    Args:
        relationships: List of relationship dicts from build_relationships.
        high_score_threshold: Minimum score to produce a finding.
        critical_score_threshold: Not used directly; score_to_risk_level
            handles the mapping. Kept in signature for API compatibility.
        panel_evidence: Optional list of panel evidence dicts for metadata.

    Returns:
        List of visual finding dicts matching VisualFinding schema fields.
    """
    panel_map: dict[str, dict] = {}
    if panel_evidence:
        for pe in panel_evidence:
            if isinstance(pe, dict) and pe.get("panel_id"):
                panel_map[str(pe["panel_id"])] = pe

    findings: list[dict] = []
    counter = 0

    for rel in relationships:
        raw_score = float(rel.get("score", 0.0))
        score = _normalized_score(raw_score)
        if score < high_score_threshold:
            continue

        src = str(rel.get("source_panel_id", ""))
        tgt = str(rel.get("target_panel_id", ""))
        source_type = str(rel.get("source_type", ""))

        # Only emit findings for categories with template support
        if source_type not in BENIGN_EXPLANATIONS:
            continue

        counter += 1
        risk_level = score_to_risk_level(score)

        benign = list(BENIGN_EXPLANATIONS[source_type])
        questions = list(MANUAL_REVIEW_QUESTIONS[source_type])
        summary = _generate_summary(source_type, src, tgt)

        # Language compliance: drop finding if any text violates
        all_text = [summary] + benign + questions
        violated = False
        for text in all_text:
            if check_language_compliance(text):
                violated = True
                break
        if violated:
            continue

        pe_meta = panel_map.get(src, {})
        target_pe_meta = panel_map.get(tgt, {})
        source_method = str(pe_meta.get("extraction_method") or "unknown")
        target_method = str(target_pe_meta.get("extraction_method") or "unknown")
        extraction_quality = _panel_extraction_quality(pe_meta, target_pe_meta)
        displayed_score = score
        confidence_adjustments = []
        if raw_score != score:
            confidence_adjustments.append("raw score normalized to [0,1]")
        if extraction_quality == "whole_figure_fallback":
            displayed_score = min(score, 0.39)
            risk_level = _cap_risk_level(score_to_risk_level(displayed_score), "medium")
            confidence_adjustments.append("risk capped because at least one panel is whole_figure_fallback")

        finding: dict = {
            "finding_id": f"VF-{counter:04d}",
            "category": source_type,
            "risk_level": risk_level,
            "summary": summary,
            "source_panel_id": src,
            "target_panel_id": tgt,
            "relationship_id": rel.get("relationship_id", ""),
            "score": displayed_score,
            "benign_explanations": benign,
            "manual_review_questions": questions,
            "overlay_path": rel.get("overlay_path"),
            "metadata": {
                "match_method": rel.get("match_method", ""),
                "inlier_count": rel.get("inlier_count", 0),
                "raw_score": raw_score,
                "normalized_score": score,
                "displayed_score": displayed_score,
                "confidence_adjustment": "; ".join(confidence_adjustments) or None,
                "panel_extraction_quality": extraction_quality,
                "source_parent_figure_id": _parent_figure_id(pe_meta, src),
                "target_parent_figure_id": _parent_figure_id(target_pe_meta, tgt),
                "source_extraction_method": source_method,
                "target_extraction_method": target_method,
                "source_panel_metadata": pe_meta.get("metadata", {}),
                "target_panel_metadata": target_pe_meta.get("metadata", {}),
            },
        }
        findings.append(finding)

    return findings


def _finding_scope(finding: dict[str, Any]) -> str:
    metadata = finding.get("metadata") if isinstance(finding.get("metadata"), dict) else {}
    src_figure = str(metadata.get("source_parent_figure_id") or finding.get("source_panel_id") or "")
    tgt_figure = str(metadata.get("target_parent_figure_id") or finding.get("target_panel_id") or "")
    return "same_figure" if src_figure == tgt_figure else "cross_figure"


def _finding_parent_figures(finding: dict[str, Any]) -> tuple[str, str]:
    metadata = finding.get("metadata") if isinstance(finding.get("metadata"), dict) else {}
    src_figure = str(metadata.get("source_parent_figure_id") or finding.get("source_panel_id") or "-")
    tgt_figure = str(metadata.get("target_parent_figure_id") or finding.get("target_panel_id") or "-")
    return src_figure, tgt_figure


def _visual_cluster_key(finding: dict[str, Any]) -> tuple[str, str, str]:
    metadata = finding.get("metadata") if isinstance(finding.get("metadata"), dict) else {}
    return (
        str(finding.get("category") or "-"),
        str(metadata.get("panel_extraction_quality") or "unknown"),
        str(metadata.get("match_method") or "-"),
    )


def _cluster_scope(group: list[dict[str, Any]]) -> str:
    scopes = {_finding_scope(finding) for finding in group}
    return "cross_figure" if "cross_figure" in scopes else "same_figure"


def _component_groups(
    findings: list[dict[str, Any]],
) -> list[tuple[tuple[str, str, str], list[str], list[dict[str, Any]]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if isinstance(finding, dict):
            grouped[_visual_cluster_key(finding)].append(finding)

    components: list[tuple[tuple[str, str, str], list[str], list[dict[str, Any]]]] = []
    for base_key, group in grouped.items():
        adjacency: dict[str, set[str]] = defaultdict(set)
        indexed: list[tuple[dict[str, Any], str, str]] = []
        for finding in group:
            src_figure, tgt_figure = _finding_parent_figures(finding)
            if not src_figure:
                src_figure = tgt_figure or str(finding.get("source_panel_id") or "-")
            if not tgt_figure:
                tgt_figure = src_figure or str(finding.get("target_panel_id") or "-")
            adjacency[src_figure].add(tgt_figure)
            adjacency[tgt_figure].add(src_figure)
            indexed.append((finding, src_figure, tgt_figure))

        visited: set[str] = set()
        for start in sorted(adjacency):
            if start in visited:
                continue
            stack = [start]
            component: set[str] = set()
            while stack:
                node = stack.pop()
                if node in component:
                    continue
                component.add(node)
                stack.extend(sorted(adjacency[node] - component))
            visited.update(component)
            component_findings = [
                finding
                for finding, src_figure, tgt_figure in indexed
                if src_figure in component and tgt_figure in component
            ]
            if component_findings:
                components.append((base_key, sorted(component), component_findings))
    return components


def _visual_review_question(category: str, extraction_quality: str) -> str:
    base = {
        "copy_move_single": "复核同一图内匹配区域是否代表独立 panel、合法对照复用或图像组装候选问题。",
        "copy_move_cross": "复核跨图匹配区域是否来自同一实验主体、共享对照或不应重复出现的局部区域。",
        "exact_duplicate": "复核字节级重复文件是否为合法导出/引用同一原图，或是否错误复用到不同图表语义。",
        "dhash_similar": "复核感知哈希相似图像是否由相似实验条件、压缩、缩放或真实重复导致。",
    }.get(category, "复核视觉相似候选的图注、panel 语义、原始图和导出流程。")
    if extraction_quality == "whole_figure_fallback":
        return base + " 该任务包含 whole_figure_fallback panel，优先确认是否需要重新拆 panel 后再判断。"
    return base


def build_visual_finding_clusters(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for index, (base_key, component_figures, group) in enumerate(
        sorted(
            _component_groups(findings),
            key=lambda item: (
                -max(_risk_rank(finding.get("risk_level")) for finding in item[2]),
                -len(item[2]),
                item[0],
                item[1],
            ),
        ),
        start=1,
    ):
        category, extraction_quality, match_method = base_key
        representatives = sorted(
            group,
            key=lambda finding: (
                -_risk_rank(finding.get("risk_level")),
                -float(finding.get("score") or 0.0),
                str(finding.get("finding_id") or ""),
            ),
        )[:8]
        risk_level = _risk_max([finding.get("risk_level") for finding in group])
        scores = [float(finding.get("score") or 0.0) for finding in group]
        finding_ids = _dedupe([finding.get("finding_id") for finding in representatives])
        all_relationship_ids = _dedupe([finding.get("relationship_id") for finding in group])
        relationship_ids = all_relationship_ids[:12]
        source_panels = _dedupe([finding.get("source_panel_id") for finding in group], limit=12)
        target_panels = _dedupe([finding.get("target_panel_id") for finding in group], limit=12)
        overlays = _dedupe([finding.get("overlay_path") for finding in group if finding.get("overlay_path")], limit=8)
        metadata_items = [
            finding.get("metadata")
            for finding in group
            if isinstance(finding.get("metadata"), dict)
        ]
        figure_ids = _dedupe(
            component_figures
            + [
                *(metadata.get("source_parent_figure_id") for metadata in metadata_items),
                *(metadata.get("target_parent_figure_id") for metadata in metadata_items),
            ],
            limit=12,
        )
        figure_group = "::".join(figure_ids[:8])
        if len(figure_ids) > 8:
            figure_group = f"{figure_group} (+{len(figure_ids) - 8} more)"
        benign: list[str] = []
        questions: list[str] = []
        for finding in group:
            benign.extend(str(item) for item in (finding.get("benign_explanations") or [])[:2])
            questions.extend(str(item) for item in (finding.get("manual_review_questions") or [])[:2])
        clusters.append(
            {
                "cluster_id": f"VFC-{index:04d}",
                "category": category,
                "risk_level": risk_level,
                "confidence": "low" if extraction_quality == "whole_figure_fallback" else "medium",
                "scope": _cluster_scope(group),
                "figure_pair": figure_group,
                "figure_ids": figure_ids,
                "component_figure_count": len(figure_ids),
                "match_method": match_method,
                "panel_extraction_quality": extraction_quality,
                "finding_count": len(group),
                "relationship_count": len(all_relationship_ids),
                "max_score": round(max(scores) if scores else 0.0, 4),
                "mean_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
                "representative_finding_ids": finding_ids,
                "relationship_ids": relationship_ids,
                "source_panel_ids": source_panels,
                "target_panel_ids": target_panels,
                "overlay_paths": overlays,
                "evidence_refs": [f"visual_findings.json:{finding_id}" for finding_id in finding_ids],
                "review_question": _visual_review_question(category, extraction_quality),
                "benign_explanations": _dedupe(benign, limit=5),
                "manual_review_questions": _dedupe(questions, limit=5),
            }
        )
    return clusters


def visual_review_queue(clusters: list[dict[str, Any]], *, max_items: int = 20) -> list[dict[str, Any]]:
    queue = []
    for index, cluster in enumerate(clusters[:max_items], start=1):
        quality = str(cluster.get("panel_extraction_quality") or "unknown")
        priority = str(cluster.get("risk_level") or "medium")
        if quality == "whole_figure_fallback":
            priority = _cap_risk_level(priority, "medium")
        queue.append(
            {
                "task_id": f"VRT-{index:03d}",
                "priority": priority,
                "cluster_id": cluster.get("cluster_id"),
                "category": cluster.get("category"),
                "scope": cluster.get("scope"),
                "figure_ids": cluster.get("figure_ids") or [],
                "finding_count": cluster.get("finding_count", 0),
                "relationship_count": cluster.get("relationship_count", 0),
                "panel_extraction_quality": quality,
                "question": (
                    f"复核 {cluster.get('category')} visual cluster {cluster.get('cluster_id')}："
                    f"{cluster.get('finding_count', 0)} 条 findings、{cluster.get('relationship_count', 0)} 条 relationships。"
                    f"{cluster.get('review_question')}"
                ),
                "evidence_refs": cluster.get("evidence_refs") or [],
                "representative_finding_ids": cluster.get("representative_finding_ids") or [],
            }
        )
    return queue
