"""Benign explanations and context-aware review questions.
# All f-string interpolations MUST use h() or h_attr() for XSS protection.

Contains the parameterized benign explanation dispatchers and the
review-question handlers that generate finding-specific review text
from actual data rather than hardcoded templates.
"""

from __future__ import annotations

from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._shared import (
    _confidence_badge,
    category_label,
    clean_report_text,
    dedupe,
    pattern_key_for_finding,
)

# ---------------------------------------------------------------------------
# Source-data benign explanation helpers
# ---------------------------------------------------------------------------


def _collect_source_sheets_cols(findings: list[dict[str, Any]]) -> tuple[str, str]:
    """Return ``(sheet_text, col_text)`` for source-data pattern explanations."""
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    sheet_text = "、".join(sheets[:4]) or "未知 sheet"
    col_pairs: list[str] = []
    for f in findings:
        for k in ("column_pair", "columns", "column"):
            val = f.get(k)
            if val:
                col_pairs.append(
                    str(val)
                    if not isinstance(val, list)
                    else ", ".join(str(v) for v in val)
                )
    col_text = "、".join(dedupe(col_pairs)[:4]) or "未记录列对"
    return sheet_text, col_text


def _benign_explanation_paired_offset(findings: list[dict[str, Any]]) -> list[str]:
    sheet_text, col_text = _collect_source_sheets_cols(findings)
    offsets = sorted(
        {
            f.get("row_offset") or f.get("pair_id_offset")
            for f in findings
            if f.get("row_offset") is not None or f.get("pair_id_offset") is not None
        }
    )
    offset_text = ", ".join(str(o) for o in offsets[:4]) or "未记录"
    rates = [
        f.get("support_rate") or f.get("ratio")
        for f in findings
        if f.get("support_rate") is not None
    ]
    rate_text = (
        ", ".join(f"{r:.2f}" if isinstance(r, float) else str(r) for r in rates[:3])
        or "未记录"
    )
    items = [
        f"sheet {sheet_text} 中列 {col_text} 在行偏移 {offset_text} 处出现比例/标量关系，"
        f"support_rate={rate_text}，可能来自合法配对排序、归一化分母或批量派生。"
    ]
    all_complete = all(
        f.get("pattern_strength") == "complete"
        for f in findings
        if f.get("pattern_strength")
    )
    if all_complete and findings:
        items.append(
            "所有匹配行均满足该模式（pattern_strength=complete），无例外行，提示该规律可能是系统性数据处理步骤而非随机编辑。"
        )
    elif rates and all(isinstance(r, (int, float)) and float(r) == 1.0 for r in rates):
        n_offsets = len(offsets)
        if n_offsets > 3:
            items.append(
                f"support_rate=1.0 且跨 {n_offsets} 个偏移值完美一致，提示可能是模板化导出或固定公式。"
            )
    return items


def _benign_explanation_row_vector(findings: list[dict[str, Any]]) -> list[str]:
    sheet_text, col_text = _collect_source_sheets_cols(findings)
    dup_counts = [
        f.get("duplicate_row_count") or f.get("exact_reuse_pairs")
        for f in findings
        if f.get("duplicate_row_count") or f.get("exact_reuse_pairs")
    ]
    dup_text = ", ".join(str(d) for d in dup_counts[:3]) or "未记录"
    return [
        f"sheet {sheet_text} 中列 {col_text} 出现行向量重复（重复行数/对数: {dup_text}），"
        f"可能来自 censoring 模板、分组标签、重复测量或导出时批量复制。"
    ]


def _benign_explanation_duplicate_numeric(findings: list[dict[str, Any]]) -> list[str]:
    sheet_text, col_text = _collect_source_sheets_cols(findings)
    return [
        f"sheet {sheet_text} 中列 {col_text} 高度相同，"
        f"可能来自索引列、共享时间点、全零矩阵、同一指标重复展示或导出模板。"
    ]


def _benign_explanation_partial_copy(findings: list[dict[str, Any]]) -> list[str]:
    sheet_text, col_text = _collect_source_sheets_cols(findings)
    return [
        f"sheet {sheet_text} 中列 {col_text} 出现部分复用或舍入相似，"
        f"可能来自合法四舍五入、格式化导出或批量处理。"
    ]


def _benign_explanation_formula_derivation(findings: list[dict[str, Any]]) -> list[str]:
    sheet_text, col_text = _collect_source_sheets_cols(findings)
    formulas = sorted(
        {
            str(f.get("dominant_formula_pattern") or f.get("category"))
            for f in findings
            if f.get("dominant_formula_pattern") or f.get("category")
        }
    )
    formula_text = "、".join(formulas[:3]) or "固定公式"
    return [
        f"sheet {sheet_text} 中列 {col_text} 呈现 {formula_text} 模式，"
        f"可能是合法的单位换算、归一化逻辑或公式派生列，需确认论文引用的是原始值还是派生值。"
    ]


_SOURCE_BENIGN_HANDLERS: dict[str, Any] = {
    "paired_offset_ratio_reuse": _benign_explanation_paired_offset,
    "row_vector_reuse_rounding": _benign_explanation_row_vector,
    "row_vector_reuse": _benign_explanation_row_vector,
    "duplicate_numeric_columns": _benign_explanation_duplicate_numeric,
    "partial_copy_rounding_bias": _benign_explanation_partial_copy,
    "formula_derivation": _benign_explanation_formula_derivation,
}


def _benign_explanation_visual_forensics(findings: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    copy_move = [
        f
        for f in findings
        if str(f.get("category")) in {"copy_move_single", "copy_move_cross"}
    ]
    forged = [
        f for f in findings if str(f.get("category")) == "forged_region_suspicious"
    ]
    if copy_move:
        panel_ids: list[str] = []
        scores: list[str] = []
        fig_labels: list[str] = []
        for f in copy_move:
            panel_ids.extend(
                [str(f.get("source_panel_id", "-")), str(f.get("target_panel_id", "-"))]
            )
            if f.get("score") is not None:
                scores.append(f"{f['score']:.3f}")
            if f.get("figure_label"):
                fig_labels.append(str(f["figure_label"]))
        panel_text = "、".join(dedupe(panel_ids)[:4]) or "未记录 panel"
        score_text = ", ".join(scores[:3]) or "未记录"
        fig_text = "、".join(dedupe(fig_labels)[:3])
        base = f"panel {panel_text} 检测到局部相似记录（score={score_text}）"
        if fig_text:
            base += f"，涉及 figure {fig_text}"
        base += "，可能来自同一主体多通道成像、合法 control 复用、裁剪导出或压缩伪影。"
        items.append(base)
    if forged:
        fig_ids = sorted(
            {str(f.get("figure_id") or f.get("figure") or "-") for f in forged}
        )
        integrity = [
            f"{f['integrity_score']:.3f}"
            for f in forged
            if f.get("integrity_score") is not None
        ]
        items.append(
            f"figure {'、'.join(fig_ids[:3])} 检测到区域完整性记录"
            f"（integrity_score={', '.join(integrity[:3]) or '未记录'}），"
            f"可能来自图像处理软件伪影、合理标注或后期调整。"
        )
    if not items:
        items.append(
            "图像工具生成了区域或相似关系记录，可能来自同一主体多通道成像、合法 control 复用、裁剪导出或压缩伪影；需结合原图、panel/caption 和实验条件判断。"
        )
    return items


def _benign_explanation_paperfraud(findings: list[dict[str, Any]]) -> list[str]:
    rules = sorted(
        {str(f.get("rule_id") or f.get("category") or "-") for f in findings}
    )
    return [
        f"PaperFraud 规则 {', '.join(rules[:4])} 命中，属于方法学提示项，需结合原始数据和论文表述判断。"
    ]


def _benign_explanation_other(findings: list[dict[str, Any]]) -> list[str]:
    missing = [
        f for f in findings
        if str(f.get("category")) == "source_data_missing"
        and str(f.get("finding_id", "")).startswith("SDM-SUMMARY-")
    ]
    if not missing:
        missing = [f for f in findings if str(f.get("category")) == "source_data_missing"]
    if missing:
        fig_labels = sorted(
            {str(f.get("figure_label") or f.get("figure") or "-") for f in missing}
        )
        return [
            f"figure {'、'.join(fig_labels[:5])} 缺少对应 Source Data，"
            f"可能来自材料未提交、公开仓库另行提供，或该 figure 不要求单独 Source Data。"
        ]
    return []


def _benign_explanation_execution_evidence() -> list[str]:
    return [
        "该模式可能来自环境差异、随机种子、依赖版本或输入材料不完整。",
        "需要结合 runtime manifest、命令日志、结果文件 hash 和表述映射判断。",
    ]


def _benign_explanation_numeric_forensics() -> list[str]:
    return [
        "PDF 或表格数字检查生成统计线索，可能来自 OCR、表格解析、四舍五入和展示层转写造成的伪影。",
        "需回到原始表格、Source Data 或结果文件，确认数字关系是否能由原始数据和统计流程解释。",
    ]


def _benign_explanation_generic() -> list[str]:
    return [
        "该模式可能来自合法的归一化、批量派生、配对样本排序或模板化导出。",
        "需要结合原始 artifact、导出参数、字段定义和论文表述语义判断。",
    ]


def _parameterized_benign_explanation(
    pattern_key: str, findings: list[dict[str, Any]]
) -> list[str]:
    """Generate context-specific benign explanations from actual finding data."""
    handler = _SOURCE_BENIGN_HANDLERS.get(pattern_key)
    if handler is not None:
        return handler(findings)
    if pattern_key == "visual_forensics":
        return _benign_explanation_visual_forensics(findings)
    if pattern_key.startswith("category:paperfraud") or pattern_key == "paperfraud":
        return _benign_explanation_paperfraud(findings)
    if pattern_key == "other":
        result = _benign_explanation_other(findings)
        if result:
            return result
    if pattern_key == "execution_evidence":
        return _benign_explanation_execution_evidence()
    if pattern_key == "numeric_forensics":
        return _benign_explanation_numeric_forensics()
    return _benign_explanation_generic()


def cluster_benign_explanations(
    findings: list[dict[str, Any]], reviews: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    """Return benign explanations as list of (text, source_type) tuples."""
    items: list[tuple[str, str]] = []
    for review in reviews:
        for item in (review.get("benign_explanations") or [])[:3]:
            items.append((str(item), "agent"))
    for finding in findings:
        for item in (finding.get("benign_explanations") or [])[:2]:
            items.append((str(item), "agent"))
    if not items:
        pattern_keys = {pattern_key_for_finding(finding) for finding in findings}
        if pattern_keys:
            dominant_key = max(
                pattern_keys,
                key=lambda k: sum(
                    1 for f in findings if pattern_key_for_finding(f) == k
                ),
            )
            for text in _parameterized_benign_explanation(dominant_key, findings):
                items.append((text, "data"))
        else:
            items = [
                (
                    "该模式可能来自合法的归一化、批量派生、配对样本排序或模板化导出。",
                    "data",
                ),
                (
                    "需要结合原始 artifact、导出参数、字段定义和论文 claim 语义判断。",
                    "data",
                ),
            ]
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for text, source_type in items:
        if text and text not in seen:
            seen.add(text)
            deduped.append((text, source_type))
    return deduped[:5]


# ---------------------------------------------------------------------------
# Review question handlers
# ---------------------------------------------------------------------------


def _review_question_paired_offset(findings: list[dict[str, Any]]) -> str:
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    offsets = sorted(
        {
            f.get("row_offset") or f.get("pair_id_offset")
            for f in findings
            if f.get("row_offset") is not None or f.get("pair_id_offset") is not None
        }
    )
    ratios: list[str] = []
    for f in findings:
        for k in ("ratio", "support_rate"):
            val = f.get(k)
            if val is not None:
                ratios.append(f"{val:.2f}" if isinstance(val, float) else str(val))
    sheet_text = "、".join(sheets[:3]) or "未记录"
    offset_text = ", ".join(str(o) for o in offsets[:3]) or "未记录"
    ratio_text = ", ".join(dedupe(ratios)[:3]) or "未记录"
    return (
        f"sheet {sheet_text} 在行偏移 {offset_text} 处出现比例/标量关系"
        f"（ratio/support_rate={ratio_text}）：确认这些固定偏移和比例复用是否来自"
        f"合法配对排序、归一化分母或批量派生，而不是同一数据的重复改写。"
    )


def _review_question_row_vector(findings: list[dict[str, Any]]) -> str:
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    dup_counts = [
        f.get("duplicate_row_count") or f.get("exact_reuse_pairs")
        for f in findings
        if f.get("duplicate_row_count") or f.get("exact_reuse_pairs")
    ]
    sheet_text = "、".join(sheets[:3]) or "未记录"
    dup_text = ", ".join(str(d) for d in dup_counts[:3]) or "未记录"
    return (
        f"sheet {sheet_text} 出现行向量重复（重复行数/对数: {dup_text}）："
        f"核对重复行是否有实验或统计语义，例如 censoring 模板、分组标签、重复测量，或导出时批量复制。"
    )


def _review_question_duplicate_numeric(findings: list[dict[str, Any]]) -> str:
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    col_pairs: list[str] = []
    for f in findings:
        val = f.get("column_pair") or f.get("columns")
        if val:
            col_pairs.append(
                str(val)
                if not isinstance(val, list)
                else ", ".join(str(v) for v in val)
            )
    sheet_text = "、".join(sheets[:3]) or "未记录"
    col_text = "、".join(dedupe(col_pairs)[:4]) or "未记录"
    return (
        f"sheet {sheet_text} 中列 {col_text} 高度相同："
        f"核对这些列是否为索引列、时间/事件设计列、全零矩阵或同一指标的合法重复展示。"
    )


def _review_question_partial_copy(findings: list[dict[str, Any]]) -> str:
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    sheet_text = "、".join(sheets[:3]) or "未记录"
    return (
        f"sheet {sheet_text} 出现部分复制或舍入后相似："
        f"核对上游导出、四舍五入、格式化和批量处理过程是否能解释该模式。"
    )


def _review_question_formula_derivation(findings: list[dict[str, Any]]) -> str:
    sheets = sorted({str(f.get("sheet")) for f in findings if f.get("sheet")})
    col_pairs: list[str] = []
    for f in findings:
        for k in ("column_pair", "columns", "column"):
            val = f.get(k)
            if val:
                col_pairs.append(
                    str(val)
                    if not isinstance(val, list)
                    else ", ".join(str(v) for v in val)
                )
    sheet_text = "、".join(sheets[:3]) or "未记录"
    col_text = "、".join(dedupe(col_pairs)[:3]) or "未记录"
    return (
        f"sheet {sheet_text} 列 {col_text} 呈现固定公式派生模式："
        f"确认论文图表引用的是原始测量值还是派生值，并要求作者说明公式来源、单位换算或归一化逻辑。"
    )


def _review_question_visual_forensics(findings: list[dict[str, Any]]) -> str:
    panel_ids: list[str] = []
    scores: list[str] = []
    for f in findings:
        for k in ("source_panel_id", "target_panel_id"):
            val = f.get(k)
            if val:
                panel_ids.append(str(val))
        if f.get("score") is not None:
            scores.append(f"{f['score']:.3f}")
        if f.get("integrity_score") is not None:
            scores.append(f"integrity={f['integrity_score']:.3f}")
    panel_text = "、".join(dedupe(panel_ids)[:4]) or "未记录"
    score_text = ", ".join(scores[:3]) or "未记录"
    return (
        f"panel {panel_text} 检测到视觉相似/复用信号（score={score_text}）："
        f"核对原图、panel、caption、相似方法、分数和最强良性解释，确认是否对应同一主体、合法复用或导出伪影。"
    )


def _review_question_category(pattern_key: str, findings: list[dict[str, Any]]) -> str:
    category = pattern_key.split(":", 1)[1]
    return (
        f"找到 {category_label(category)} 类型记录 {len(findings)} 条："
        f"逐条核对记录的数据语义、生成过程和论文表述影响。"
    )


_REVIEW_QUESTION_HANDLERS: dict[str, Any] = {
    "paired_offset_ratio_reuse": _review_question_paired_offset,
    "row_vector_reuse_rounding": _review_question_row_vector,
    "row_vector_reuse": _review_question_row_vector,
    "duplicate_numeric_columns": _review_question_duplicate_numeric,
    "partial_copy_rounding_bias": _review_question_partial_copy,
    "formula_derivation": _review_question_formula_derivation,
    "visual_forensics": _review_question_visual_forensics,
}


def context_aware_review_question(
    pattern_key: str,
    findings: list[dict[str, Any]],
    clusters: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a specific review question referencing actual finding parameters."""
    from engine.static_audit.html_report._patterns import pattern_definition

    fallback = pattern_definition(pattern_key).get("review_question", "")
    handler = _REVIEW_QUESTION_HANDLERS.get(pattern_key)
    if handler is not None:
        return handler(findings)
    if pattern_key in {"numeric_forensics", "execution_evidence"}:
        return fallback
    if pattern_key.startswith("category:"):
        return _review_question_category(pattern_key, findings)
    return fallback


def _benign_items_to_html(items: list) -> str:
    """Render benign explanation items (strings or (text, source_type) tuples) as badge HTML."""
    if not items:
        return "<p class='muted'>未记录。</p>"
    parts = []
    for item in items:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and isinstance(item[1], str)
        ):
            text, source_type = item
            parts.append(
                f"<li>{_confidence_badge(source_type)}{h(clean_report_text(text))}</li>"
            )
        else:
            parts.append(f"<li>{h(clean_report_text(item))}</li>")
    return "<ul>" + "".join(parts) + "</ul>"
