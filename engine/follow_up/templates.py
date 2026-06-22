"""Fallback template-based follow-up question generator.

Used when LLM is unavailable. Templates are designed for PI (non-technical)
language and reference concrete data from the finding metadata.
"""

from __future__ import annotations


def _fmt_list(items: list | str | None) -> str:
    """Format a list or string for display in a question."""
    if isinstance(items, list):
        return ", ".join(str(i) for i in items)
    return str(items) if items else "N/A"


def _metadata(finding: dict) -> dict:
    raw = finding.get("metadata") or {}
    if not isinstance(raw, dict):
        return {}
    nested = raw.get("metadata")
    merged = dict(nested) if isinstance(nested, dict) else {}
    merged.update(raw)
    return merged


def _first(metadata: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, "", []):
            return str(value)
    return default


def _column_ref(metadata: dict) -> str:
    return _fmt_list(
        metadata.get("column_labels")
        or metadata.get("columns")
        or metadata.get("column_pair")
        or [metadata.get("col_a"), metadata.get("col_b")]
    )


def _sheet_ref(metadata: dict) -> str:
    workbook = _first(metadata, "workbook", "file", "source_file")
    sheet = _first(metadata, "sheet", "sheet_name")
    if workbook and sheet:
        return f"{workbook} / {sheet}"
    return sheet or workbook or "Source Data"


def _support_ref(metadata: dict) -> str:
    equal_rows = _first(metadata, "equal_rows")
    overlap_rows = _first(metadata, "overlap_rows")
    matched_pairs = _first(metadata, "matched_pairs")
    overlap_pairs = _first(metadata, "overlap_pairs")
    support_rate = _first(metadata, "support_rate")
    if equal_rows and overlap_rows:
        return f"{equal_rows}/{overlap_rows} 行"
    if matched_pairs and overlap_pairs:
        return f"{matched_pairs}/{overlap_pairs} 对"
    if support_rate:
        return f"support_rate={support_rate}"
    return _first(metadata, "support_rows", "n_rows", default="?")


def _panel_ref(metadata: dict) -> str:
    return _fmt_list(
        metadata.get("panels")
        or metadata.get("panel_ids")
        or [
            _first(metadata, "source_panel_id", "panel_a", "figure_a"),
            _first(metadata, "target_panel_id", "panel_b", "figure_b"),
        ]
    )


def _score_ref(metadata: dict) -> str:
    score = metadata.get("score", metadata.get("confidence"))
    if isinstance(score, float):
        return f"{score:.3f}"
    return str(score) if score not in (None, "") else ""


# ---------------------------------------------------------------------------
# Per-category question generators
# Signature: (finding, metadata, summary) -> list[str]
# ---------------------------------------------------------------------------


def _gen_duplicate_column(finding: dict, m: dict, summary: str) -> list[str]:
    columns = _column_ref(m)
    support = _support_ref(m)
    location = _sheet_ref(m)
    return [
        f"{location} 中列 {columns} 在 {support}数据内完全相同，"
        f"这是同一实验的重复测量，还是数据录入时的复制？"
    ]


def _gen_fixed_relation(finding: dict, m: dict, summary: str) -> list[str]:
    category = str(finding.get("category", ""))
    columns = _column_ref(m)
    support = _support_ref(m)
    if category == "formula_derived_column":
        rel_type, relation = "公式派生", "公式派生关系"
    elif "difference" in category:
        rel_type, relation = "差值", "固定差值关系"
    else:
        rel_type, relation = "比例", "固定比例关系"
    value = _first(m, "value", "fixed_value", "difference", "ratio")
    value_str = f"（{rel_type} = {value}）" if value else ""
    return [
        f"{_sheet_ref(m)} 中列 {columns} 在 {support} 内存在{relation}{value_str}，"
        f"请提供对应公式、单位换算或原始测量记录来核对。"
    ]


def _gen_paired_reuse(finding: dict, m: dict, summary: str) -> list[str]:
    columns = _column_ref(m)
    support = _support_ref(m)
    offset = _first(m, "row_offset")
    ratio_places = _first(m, "ratio_places")
    details = []
    if offset:
        details.append(f"row_offset={offset}")
    if ratio_places:
        details.append(f"ratio_places={ratio_places}")
    suffix = f"（{', '.join(details)}）" if details else ""
    return [
        f"{_sheet_ref(m)} 中列 {columns} 出现 {support} 的成对复用模式{suffix}，"
        f"请核对这些行是否来自同一批原始记录或复制粘贴后的派生表。"
    ]


def _gen_copy_move(finding: dict, m: dict, summary: str) -> list[str]:
    panels = _panel_ref(m)
    method = _first(m, "match_method", "method")
    score = _score_ref(m)
    score_str = f"，score={score}" if score else ""
    method_str = f"，method={method}" if method else ""
    overlay = _first(m, "overlay_path")
    overlay_str = f"，overlay={overlay}" if overlay else ""
    return [
        f"Panel {panels} 检测到 copy-move 候选{score_str}{method_str}{overlay_str}，"
        f"请用原始图像或实验记录确认这些区域是否来自同一曝光/同一视野。"
    ]


def _gen_source_data_missing(finding: dict, m: dict, summary: str) -> list[str]:
    fig_id = _first(m, "figure_id", "figure", "target")
    if fig_id:
        return [
            f"论文引用了 {fig_id} 的数据，但 Source Data 文件中未找到对应数据，"
            f"请补充完整的原始数据文件。"
        ]
    return ["论文引用了数据但 Source Data 未提供，请补充完整的原始数据文件。"]


def _gen_exact_image_duplicate(finding: dict, m: dict, summary: str) -> list[str]:
    images = _fmt_list(
        m.get("images") or m.get("file_a") or m.get("figure_ids", [])
    )
    return [
        f"图片 {images} 字节级完全相同，请确认是否为同一实验的不同命名或重复提交。"
    ]


def _gen_overlap_reuse(finding: dict, m: dict, summary: str) -> list[str]:
    fig_a = _first(m, "figure_a", "panel_a", "source_panel_id")
    fig_b = _first(m, "figure_b", "panel_b", "target_panel_id")
    shared_area = _first(m, "shared_area", "overlap_area")
    area_str = f"，shared_area={shared_area}" if shared_area else ""
    return [
        f"图片 {fig_a} 与 {fig_b} 存在局部重叠候选{area_str}，"
        f"请说明这两张图的样本、条件和采集视野关系。"
    ]


def _gen_forged_region(finding: dict, m: dict, summary: str) -> list[str]:
    panels = _panel_ref(m)
    score = _score_ref(m)
    heatmap = _first(m, "heatmap_path", "mask_path")
    score_str = f" score={score}" if score else ""
    heatmap_str = f"，heatmap={heatmap}" if heatmap else ""
    return [
        f"Panel {panels} 出现伪造区域模型候选{score_str}{heatmap_str}，"
        f"请提供原始未压缩图片以便人工复核热区是否为压缩或处理伪影。"
    ]


def _gen_paperfraud(finding: dict, m: dict, summary: str) -> list[str]:
    rule_id = _first(m, "rule_id", "rule", default=str(finding.get("category", "")))
    return [
        f"PaperFraud 规则 {rule_id} 命中：{summary}。"
        f"请提供该方法声明对应的原始数据、统计过程或注册材料供复核。"
    ]


def _gen_default(finding: dict, m: dict, summary: str) -> list[str]:
    finding_id = finding.get("finding_id", "")
    prefix = f"{finding_id} " if finding_id else ""
    return [f"{prefix}{summary}。请基于原始数据、图像或实验记录说明该技术事实的来源。"]


# Strategy registry: category -> generator function.
# Keys using startswith matching (e.g. "paperfraud.*") are handled in dispatch.
_QUESTION_GENERATORS = {
    "duplicate_column": _gen_duplicate_column,
    "duplicate_numeric_columns": _gen_duplicate_column,
    "fixed_difference": _gen_fixed_relation,
    "fixed_ratio": _gen_fixed_relation,
    "formula_derived_column": _gen_fixed_relation,
    "paired_ratio_reuse": _gen_paired_reuse,
    "paired_difference_too_narrow": _gen_paired_reuse,
    "long_format_paired_ratio_reuse": _gen_paired_reuse,
    "duplicate_row_vector": _gen_paired_reuse,
    "row_offset_exact_reuse": _gen_paired_reuse,
    "copy_move_detected": _gen_copy_move,
    "copy_move_single": _gen_copy_move,
    "copy_move_cross": _gen_copy_move,
    "source_data_missing": _gen_source_data_missing,
    "exact_image_duplicate": _gen_exact_image_duplicate,
    "overlap_reuse_detected": _gen_overlap_reuse,
    "overlap_reuse": _gen_overlap_reuse,
    "forged_region_suspicious": _gen_forged_region,
}


def generate_fallback_questions(finding: dict) -> list[str]:
    """Generate follow-up questions from templates when LLM is unavailable.

    Questions reference concrete data from the finding (columns, rows, values)
    and use PI-friendly language without accusatory terms.

    Dispatch strategy:
      1. Exact match in _QUESTION_GENERATORS by category.
      2. Prefix match for "paperfraud.*" categories.
      3. Default generic fallback.
    """
    category = str(finding.get("category", ""))
    metadata = _metadata(finding)
    summary = finding.get("summary", "发现异常")

    generator = _QUESTION_GENERATORS.get(category)
    if generator is not None:
        return generator(finding, metadata, summary)
    if category.startswith("paperfraud."):
        return _gen_paperfraud(finding, metadata, summary)
    return _gen_default(finding, metadata, summary)
