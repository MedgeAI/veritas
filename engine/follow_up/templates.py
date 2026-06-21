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


def generate_fallback_questions(finding: dict) -> list[str]:
    """Generate follow-up questions from templates when LLM is unavailable.

    Questions reference concrete data from the finding (columns, rows, values)
    and use PI-friendly language without accusatory terms.
    """
    category = str(finding.get("category", ""))
    metadata = _metadata(finding)
    summary = finding.get("summary", "发现异常")

    # Category-specific templates
    if category in ("duplicate_column", "duplicate_numeric_columns"):
        columns = _column_ref(metadata)
        support = _support_ref(metadata)
        location = _sheet_ref(metadata)
        return [
            f"{location} 中列 {columns} 在 {support}数据内完全相同，"
            f"这是同一实验的重复测量，还是数据录入时的复制？"
        ]

    if category in ("fixed_difference", "fixed_ratio", "formula_derived_column"):
        columns = _column_ref(metadata)
        support = _support_ref(metadata)
        rel_type = "差值" if "difference" in category else "比例"
        relation = f"固定{rel_type}关系"
        if category == "formula_derived_column":
            rel_type = "公式派生"
            relation = "公式派生关系"
        value = _first(metadata, "value", "fixed_value", "difference", "ratio")
        value_str = f"（{rel_type} = {value}）" if value else ""
        return [
            f"{_sheet_ref(metadata)} 中列 {columns} 在 {support} 内存在{relation}{value_str}，"
            f"请提供对应公式、单位换算或原始测量记录来核对。"
        ]

    if category in (
        "paired_ratio_reuse",
        "paired_difference_too_narrow",
        "long_format_paired_ratio_reuse",
        "duplicate_row_vector",
        "row_offset_exact_reuse",
    ):
        columns = _column_ref(metadata)
        support = _support_ref(metadata)
        offset = _first(metadata, "row_offset")
        ratio_places = _first(metadata, "ratio_places")
        details = []
        if offset:
            details.append(f"row_offset={offset}")
        if ratio_places:
            details.append(f"ratio_places={ratio_places}")
        suffix = f"（{', '.join(details)}）" if details else ""
        return [
            f"{_sheet_ref(metadata)} 中列 {columns} 出现 {support} 的成对复用模式{suffix}，"
            f"请核对这些行是否来自同一批原始记录或复制粘贴后的派生表。"
        ]

    if category in ("copy_move_detected", "copy_move_single", "copy_move_cross"):
        panels = _panel_ref(metadata)
        method = _first(metadata, "match_method", "method")
        score = _score_ref(metadata)
        score_str = f"，score={score}" if score else ""
        method_str = f"，method={method}" if method else ""
        overlay = _first(metadata, "overlay_path")
        overlay_str = f"，overlay={overlay}" if overlay else ""
        return [
            f"Panel {panels} 检测到 copy-move 候选{score_str}{method_str}{overlay_str}，"
            f"请用原始图像或实验记录确认这些区域是否来自同一曝光/同一视野。"
        ]

    if category == "source_data_missing":
        fig_id = _first(metadata, "figure_id", "figure", "target")
        return (
            [
                f"论文引用了 {fig_id} 的数据，但 Source Data 文件中未找到对应数据，"
                f"请补充完整的原始数据文件。"
            ]
            if fig_id
            else ["论文引用了数据但 Source Data 未提供，请补充完整的原始数据文件。"]
        )

    if category == "exact_image_duplicate":
        images = _fmt_list(
            metadata.get("images")
            or metadata.get("file_a")
            or metadata.get("figure_ids", [])
        )
        return [
            f"图片 {images} 字节级完全相同，请确认是否为同一实验的不同命名或重复提交。"
        ]

    if category in ("overlap_reuse_detected", "overlap_reuse"):
        fig_a = _first(metadata, "figure_a", "panel_a", "source_panel_id")
        fig_b = _first(metadata, "figure_b", "panel_b", "target_panel_id")
        shared_area = _first(metadata, "shared_area", "overlap_area")
        area_str = f"，shared_area={shared_area}" if shared_area else ""
        return [
            f"图片 {fig_a} 与 {fig_b} 存在局部重叠候选{area_str}，"
            f"请说明这两张图的样本、条件和采集视野关系。"
        ]

    if category == "forged_region_suspicious":
        panels = _panel_ref(metadata)
        score = _score_ref(metadata)
        heatmap = _first(metadata, "heatmap_path", "mask_path")
        score_str = f" score={score}" if score else ""
        heatmap_str = f"，heatmap={heatmap}" if heatmap else ""
        return [
            f"Panel {panels} 出现伪造区域模型候选{score_str}{heatmap_str}，"
            f"请提供原始未压缩图片以便人工复核热区是否为压缩或处理伪影。"
        ]

    if category.startswith("paperfraud."):
        rule_id = _first(metadata, "rule_id", "rule", default=category)
        return [
            f"PaperFraud 规则 {rule_id} 命中：{summary}。"
            f"请提供该方法声明对应的原始数据、统计过程或注册材料供复核。"
        ]

    # Generic fallback
    finding_id = finding.get("finding_id", "")
    prefix = f"{finding_id} " if finding_id else ""
    return [f"{prefix}{summary}。请基于原始数据、图像或实验记录说明该技术事实的来源。"]
