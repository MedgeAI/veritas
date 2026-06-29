"""Finding clustering, review-task generation, and ID assignment."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ._shared import risk_rank


def assign_ids(findings: list[dict[str, Any]]) -> None:
    counters: Counter[str] = Counter()
    prefixes = {
        "row_offset_exact_reuse": "ROE",
        "row_offset_scalar_multiple": "ROS",
        "paired_ratio_reuse": "PRR",
        "duplicate_row_vector": "DRV",
        "long_format_paired_ratio_reuse": "LPR",
        "long_format_within_pair_ratio_enrichment": "LPE",
        "row_offset_partial_copy_rounding_bias": "RBR",
        "paired_difference_too_narrow": "PDS",
        "cross_block_paired_diff_too_narrow": "CBD",
    }
    for finding in findings:
        category = finding["category"]
        counters[category] += 1
        finding["finding_id"] = (
            f"{prefixes.get(category, 'PF')}-{counters[category]:04d}"
        )


def _finding_offset(finding: dict[str, Any]) -> Any:
    return finding.get("row_offset") or finding.get("pair_id_offset") or "-"


def _finding_relationship(finding: dict[str, Any]) -> Any:
    return finding.get("relationship_value") or finding.get("ratio_places") or "-"


def _finding_columns_text(finding: dict[str, Any]) -> str:
    columns = (
        finding.get("columns")
        or finding.get("column_pair")
        or finding.get("column")
        or []
    )
    if isinstance(columns, list):
        return ", ".join(str(item) for item in columns)
    return str(columns)


def _finding_support(finding: dict[str, Any]) -> tuple[int, int]:
    support = (
        finding.get("support_rows")
        or finding.get("matched_pairs")
        or finding.get("matched_pair_groups")
        or finding.get("duplicate_row_count")
        or finding.get("pair_count")
        or finding.get("exact_reuse_pairs")
        or 0
    )
    overlap = (
        finding.get("overlap_rows")
        or finding.get("overlap_pairs")
        or finding.get("overlap_pair_groups")
        or finding.get("duplicate_row_count")
        or 0
    )
    try:
        support_int = int(support)
    except (TypeError, ValueError):
        support_int = 0
    try:
        overlap_int = int(overlap)
    except (TypeError, ValueError):
        overlap_int = 0
    return support_int, overlap_int


def _cluster_key(finding: dict[str, Any]) -> tuple[str, str, str, str, str]:
    category = str(finding.get("category") or "-")
    workbook = str(finding.get("workbook") or "-")
    sheet = str(finding.get("sheet") or "-")
    offset = str(_finding_offset(finding))
    if category in {
        "row_offset_scalar_multiple",
        "row_offset_exact_reuse",
        "long_format_within_pair_ratio_enrichment",
        "row_offset_partial_copy_rounding_bias",
    }:
        signature = f"offset={offset};relationship={_finding_relationship(finding)}"
    elif category == "duplicate_row_vector":
        signature = f"width={finding.get('width', '-')}"
    else:
        signature = f"offset={offset}"
    return category, workbook, sheet, offset, signature


def _category_review_question(category: str) -> str:
    questions = {
        "paired_ratio_reuse": "同一 sheet 内多组列对在固定行偏移下复用相同比例，需确认这些行是否为独立样本或合法派生。",
        "long_format_paired_ratio_reuse": "long-format pair 在固定 pair id 偏移下复用相同比例，需确认 pair id 是否代表独立样本/患者。",
        "row_offset_scalar_multiple": "同一列在固定行偏移下呈固定倍数关系，需确认是否来自单位换算、归一化或复制派生。",
        "row_offset_exact_reuse": "同一列在固定行偏移下重复数值，需确认是否为合法重复测量或复制粘贴。",
        "duplicate_row_vector": "多行低宽度数值向量重复，需确认重复行是否代表同一样本、模板行或独立测量。",
        "long_format_within_pair_ratio_enrichment": "多个 long-format pair 出现相同比例富集，需确认是否由阈值化/归一化预期产生。",
        "row_offset_partial_copy_rounding_bias": "固定行偏移同时出现精度变化和部分复用，需确认后半区是否为独立原始记录。",
        "paired_difference_too_narrow": "配对列之间的差异分布异常狭窄，需确认配对测量是否来自独立生物学重复或高精度技术重复。",
        "cross_block_paired_diff_too_narrow": "被文本分隔行分开的两个数据块中，对应位置的列值差异异常狭窄，需确认两个块是否代表独立实验条件。",
    }
    return questions.get(
        category, "该 Source Data pattern 需要结合样本语义和原始记录人工复核。"
    )


def cluster_pair_forensics_findings(
    findings: list[dict[str, Any]],
    *,
    max_representatives: int = 8,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(
        list
    )
    for finding in findings:
        if isinstance(finding, dict):
            grouped[_cluster_key(finding)].append(finding)

    clusters: list[dict[str, Any]] = []
    for index, (key, group) in enumerate(
        sorted(
            grouped.items(),
            key=lambda item: (
                -max(
                    risk_rank(str(finding.get("risk_level", ""))) for finding in item[1]
                ),
                -len(item[1]),
                item[0],
            ),
        ),
        start=1,
    ):
        category, workbook, sheet, offset, signature = key
        representatives = sorted(
            group,
            key=lambda finding: (
                -risk_rank(str(finding.get("risk_level", ""))),
                -_finding_support(finding)[0],
                str(finding.get("finding_id", "")),
            ),
        )[:max_representatives]
        support_total = 0
        overlap_total = 0
        max_support_rate = 0.0
        columns_sample: list[str] = []
        for finding in group:
            support, overlap = _finding_support(finding)
            support_total += support
            overlap_total += overlap
            try:
                max_support_rate = max(
                    max_support_rate, float(finding.get("support_rate") or 0.0)
                )
            except (TypeError, ValueError):
                pass
            columns_text = _finding_columns_text(finding)
            if columns_text and columns_text not in columns_sample:
                columns_sample.append(columns_text)

        risk_level = max(
            (str(finding.get("risk_level", "medium")) for finding in group),
            key=risk_rank,
            default="medium",
        )
        cluster_id = f"PFC-{index:04d}"
        representative_ids = [
            str(finding.get("finding_id"))
            for finding in representatives
            if finding.get("finding_id")
        ]
        first = representatives[0] if representatives else group[0]
        clusters.append(
            {
                "cluster_id": cluster_id,
                "category": category,
                "risk_level": risk_level,
                "confidence": "high"
                if any(finding.get("confidence") == "high" for finding in group)
                else "medium",
                "workbook": workbook,
                "sheet": sheet,
                "pattern_signature": signature,
                "offset": offset,
                "finding_count": len(group),
                "support_total": support_total,
                "overlap_total": overlap_total,
                "max_support_rate": round(max_support_rate, 4),
                "columns_sample": columns_sample[:12],
                "representative_finding_ids": representative_ids,
                "evidence_refs": [
                    f"source_data_pair_forensics.json:{finding_id}"
                    for finding_id in representative_ids
                ],
                "review_question": _category_review_question(category),
                "benign_explanations": (first.get("benign_explanations") or [])[:3],
                "next_steps": (first.get("next_steps") or [])[:4],
            }
        )
    return clusters


def pair_forensics_review_tasks(
    clusters: list[dict[str, Any]], *, max_tasks: int = 20
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for cluster in clusters:
        if isinstance(cluster, dict):
            grouped[
                (
                    str(cluster.get("category") or "-"),
                    str(cluster.get("workbook") or "-"),
                    str(cluster.get("sheet") or "-"),
                )
            ].append(cluster)

    task_groups = sorted(
        grouped.items(),
        key=lambda item: (
            -max(risk_rank(str(cluster.get("risk_level", ""))) for cluster in item[1]),
            -sum(int(cluster.get("finding_count") or 0) for cluster in item[1]),
            item[0],
        ),
    )
    tasks = []
    for index, (key, group) in enumerate(task_groups[:max_tasks], start=1):
        category, workbook, sheet = key
        group = sorted(
            group,
            key=lambda cluster: (
                -risk_rank(str(cluster.get("risk_level", ""))),
                -int(cluster.get("finding_count") or 0),
                str(cluster.get("cluster_id", "")),
            ),
        )
        risk_level = max(
            (str(cluster.get("risk_level", "medium")) for cluster in group),
            key=risk_rank,
            default="medium",
        )
        finding_count = sum(int(cluster.get("finding_count") or 0) for cluster in group)
        cluster_ids = [
            str(cluster.get("cluster_id"))
            for cluster in group
            if cluster.get("cluster_id")
        ]
        representative_ids: list[str] = []
        evidence_refs: list[str] = []
        signatures: list[str] = []
        for cluster in group:
            for finding_id in cluster.get("representative_finding_ids") or []:
                if finding_id not in representative_ids:
                    representative_ids.append(str(finding_id))
            for ref in cluster.get("evidence_refs") or []:
                if ref not in evidence_refs:
                    evidence_refs.append(str(ref))
            signature = str(cluster.get("pattern_signature") or "")
            if signature and signature not in signatures:
                signatures.append(signature)
        tasks.append(
            {
                "task_id": f"PFRT-{index:03d}",
                "priority": risk_level,
                "cluster_id": cluster_ids[0] if cluster_ids else None,
                "cluster_ids": cluster_ids[:12],
                "cluster_count": len(group),
                "category": category,
                "workbook": workbook,
                "sheet": sheet,
                "finding_count": finding_count,
                "pattern_signatures": signatures[:12],
                "question": (
                    f"复核 {workbook} / {sheet} 的 {category} patterns："
                    f"{len(group)} 个 clusters、{finding_count} 条 raw findings。"
                    f"{_category_review_question(category)}"
                ),
                "evidence_refs": evidence_refs[:12],
                "representative_finding_ids": representative_ids[:12],
            }
        )
    return tasks
