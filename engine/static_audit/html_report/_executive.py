"""Executive summary, hero section, verdict, and limitations."""
# All f-string interpolations MUST use h() or h_attr() for XSS protection.

from __future__ import annotations

from typing import Any

from engine.static_audit.html_report._html_utils import h
from engine.static_audit.html_report._config import (
    AUDIT_DEPTH_LABELS,
    DEFAULT_ACTION_QUESTIONS,
    MAX_HERO_ACTIONS,
    MAX_ACTION_QUESTION_LENGTH,
    MAX_HERO_PATTERNS,
    MAX_LIMITATIONS_FROM_BUNDLE,
    MAX_LIMITATIONS_FROM_JUDGE,
    MIN_SOURCE_DATA_PATTERNS_FOR_MULTI_SUMMARY,
    SOURCE_DATA_PATTERN_KEYS,
    VERDICT_DISCLAIMER,
    VERDICT_HEADLINES,
    VERDICT_LABELS,
)
from engine.static_audit.html_report._shared import (
    _confidence_badge,
    clean_report_text,
    dedupe,
    list_items,
    risk_score,
    shorten,
)


# ---------------------------------------------------------------------------
# Verdict & depth
# ---------------------------------------------------------------------------


def audit_depth_label(bundle: dict[str, Any], tool_runs: list[dict[str, Any]]) -> str:
    """Determine the audit coverage depth label based on what was executed."""
    step_keys = {
        str(step.get("key") or step.get("step_key"))
        for step in tool_runs
        if isinstance(step, dict)
    }
    evidence_count = len(bundle.get("evidence_items") or [])
    claim_mapping_count = len(bundle.get("claim_mappings") or [])
    execution_status = (bundle.get("execution_status") or {}).get("status")
    if not evidence_count and not step_keys:
        return AUDIT_DEPTH_LABELS["v0"]
    if execution_status == "ran":
        return AUDIT_DEPTH_LABELS["v4"]
    if claim_mapping_count or len(bundle.get("agent_traces") or []):
        return AUDIT_DEPTH_LABELS["v3"]
    if {
        "source_data_profile",
        "source_data_findings",
        "source_data_pair_forensics",
        "exact_image_duplicates",
    } & step_keys:
        return AUDIT_DEPTH_LABELS["v2"]
    return AUDIT_DEPTH_LABELS["v1"]


def report_verdict(
    findings: list[dict[str, Any]],
    manual_tasks: list[dict[str, Any]],
    tool_runs: list[dict[str, Any]],
    bundle: dict[str, Any],
) -> dict[str, str]:
    """Determine the overall verdict for the report based on findings and tool status."""
    from engine.static_audit.html_report._findings import finding_display_score

    statuses = {str(step.get("status")) for step in tool_runs if isinstance(step, dict)}
    max_risk = max((finding_display_score(finding) for finding in findings), default=0)
    has_review_work = bool(findings or manual_tasks)
    has_failed_tool = "failed" in statuses
    has_warning_tool = "warning" in statuses

    if max_risk >= risk_score("critical"):
        verdict_key = "fail"
    elif has_review_work or has_failed_tool or has_warning_tool:
        verdict_key = "warning"
    else:
        verdict_key = "pass"

    return {
        "label": VERDICT_LABELS[verdict_key],
        "headline": VERDICT_HEADLINES[verdict_key],
        "result": verdict_key,
        "depth": audit_depth_label(bundle, tool_runs),
    }


# ---------------------------------------------------------------------------
# Executive summary
# ---------------------------------------------------------------------------


def _has_pattern_type(patterns: list[dict[str, Any]], key_substring: str) -> bool:
    return any(
        key_substring in str(pattern.get("pattern_key", "")) for pattern in patterns
    )


def _count_pattern_findings(patterns: list[dict[str, Any]], key_substring: str) -> int:
    total = 0
    for pattern in patterns:
        if key_substring in str(pattern.get("pattern_key", "")):
            total += len(pattern.get("findings") or [])
    return total


def source_coverage_value(profile_summary: dict[str, Any]) -> str:
    workbook_count = profile_summary.get("workbook_count")
    sheet_count = profile_summary.get("sheet_count")
    if workbook_count is None and sheet_count is None:
        return "未选择"
    return f"{workbook_count if workbook_count is not None else '-'} / {sheet_count if sheet_count is not None else '-'}"


def source_coverage_text(profile_summary: dict[str, Any]) -> str:
    workbook_count = profile_summary.get("workbook_count")
    sheet_count = profile_summary.get("sheet_count")
    if workbook_count is None and sheet_count is None:
        return "未形成 Source Data workbook/sheet 覆盖指标"
    return f"已覆盖 {workbook_count if workbook_count is not None else '-'} 个 workbook / {sheet_count if sheet_count is not None else '-'} 个 sheet"


def summary_pattern_clause(patterns: list[dict[str, Any]]) -> str:
    pattern_titles = [
        str(pattern.get("title")) for pattern in patterns[:3] if pattern.get("title")
    ]
    if not pattern_titles:
        return "未形成重点摘要；原始证据记录保留在原始证据记录区。"
    return f"形成 {len(patterns)} 类重点摘要：{'、'.join(pattern_titles)}。"


def executive_summary(
    patterns: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    bundle_counts: dict[str, int],
    profile_summary: dict[str, Any],
    exact_images: dict[str, Any],
) -> str:
    """Generate the executive summary paragraph based on findings and patterns."""
    source_coverage = source_coverage_text(profile_summary)
    image_count = exact_images.get("image_count", "-")
    workbook_count = profile_summary.get("workbook_count", "-")
    sheet_count = profile_summary.get("sheet_count", "-")
    claim_mapping_count = bundle_counts.get("claim_mappings", 0)
    pattern_clause = summary_pattern_clause(patterns)
    disclaimer = VERDICT_DISCLAIMER

    if not findings:
        return (
            "本次静态技术复核未生成高优先级复核记录。"
            f"当前 {source_coverage}、"
            f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            "仍需结合材料完整性和人工抽查确认。"
        )

    has_visual_critical = _has_pattern_type(patterns, "visual_forensics") and any(
        str(f.get("risk_level")) in {"critical", "high"}
        for p in patterns
        if "visual_forensics" in str(p.get("pattern_key", ""))
        for f in (p.get("findings") or [])
    )
    source_data_pattern_keys = {
        str(p.get("pattern_key", ""))
        for p in patterns
        if str(p.get("pattern_key", "")) in SOURCE_DATA_PATTERN_KEYS
    }
    has_multiple_sd_patterns = (
        len(source_data_pattern_keys) >= MIN_SOURCE_DATA_PATTERNS_FOR_MULTI_SUMMARY
    )
    has_source_data_findings = (
        _has_pattern_type(patterns, "paired_offset")
        or _has_pattern_type(patterns, "row_vector")
        or _has_pattern_type(patterns, "duplicate_numeric_columns")
        or _has_pattern_type(patterns, "partial_copy_rounding_bias")
        or _has_pattern_type(patterns, "formula_derivation")
        or _has_pattern_type(patterns, "numeric_forensics")
    )
    has_only_completeness = (
        all(
            str(p.get("pattern_key", "")) in {"other", "category:source_data_missing"}
            for p in patterns
        )
        and patterns
    )

    if has_visual_critical and has_source_data_findings:
        visual_count = _count_pattern_findings(patterns, "visual_forensics")
        sd_count = len(findings) - visual_count
        return (
            f"本次静态技术复核形成 {visual_count} 条图像复核记录、"
            f"{sd_count} 条 Source Data 复核记录，{pattern_clause}"
            f"当前已覆盖 {workbook_count} 个 workbook / {sheet_count} 个 sheet、"
            f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            f"{disclaimer}"
        )

    if has_multiple_sd_patterns:
        sd_count = len(findings)
        sheet_set: set[str] = set()
        for p in patterns:
            if str(p.get("pattern_key", "")) in SOURCE_DATA_PATTERN_KEYS:
                sheet_set.update(str(s) for s in (p.get("sheets") or []))
        sheet_text = "、".join(sorted(sheet_set)[:3]) or "多个 sheet"
        return (
            f"本次静态技术复核在 Source Data 中形成 {sd_count} 条复核记录，"
            f"涉及 {len(source_data_pattern_keys)} 类模式，跨 {sheet_text} 等多个 sheet，{pattern_clause}"
            f"当前已覆盖 {workbook_count} 个 workbook / {sheet_count} 个 sheet、"
            f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            f"{disclaimer}"
        )

    if has_visual_critical:
        visual_count = _count_pattern_findings(patterns, "visual_forensics")
        return (
            f"本次静态技术复核在图像层面形成 {visual_count} 条复核记录，"
            f"{pattern_clause}"
            f"当前 {source_coverage}、"
            f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            f"{disclaimer}"
        )

    if has_source_data_findings:
        return (
            f"本次静态技术复核在 Source Data 层面形成 {len(findings)} 条复核记录，"
            f"{pattern_clause}"
            f"当前 {source_coverage}、"
            f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            f"{disclaimer}"
        )

    if has_only_completeness:
        missing_count = sum(
            1
            for f in findings
            if str(f.get("category")) == "source_data_missing"
            and str(f.get("finding_id", "")).startswith("SDM-SUMMARY-")
        )
        return (
            f"本次静态技术复核主要发现材料完整性问题：{missing_count} 个 figure 缺少对应 Source Data，"
            f"{pattern_clause}"
            f"当前 {source_coverage}、{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
            "材料缺失只说明当前提交包不完整，需先补充材料后再做技术复核。"
        )

    return (
        f"本次静态技术复核生成 {len(findings)} 条高优先级复核记录，"
        f"{pattern_clause}"
        f"当前 {source_coverage}、"
        f"{claim_mapping_count} 条表述映射和 {image_count} 张 PDF 提取图片；"
        f"{disclaimer}"
    )


# ---------------------------------------------------------------------------
# Hero helpers
# ---------------------------------------------------------------------------


def hero_report_header_label() -> str:
    """Render the formal 'VERITAS INDEPENDENT CERTIFICATION REPORT' label."""
    return (
        '<div class="report-header-label">'
        "Veritas Independent Certification Report"
        "</div>"
    )


def hero_report_id(report_id: str | None) -> str:
    """Render the large monospace report ID as visual focal point.

    Returns empty string if report_id is None/empty.
    """
    if not report_id:
        return ""
    return f'<div class="report-id-hero">{h(report_id)}</div>'


def hero_immutable_statement(report_id: str | None) -> str:
    """Render the immutable certification statement at the bottom of the hero.

    This is the "notarization" line, set in italic serif font.
    """
    id_suffix = f" — {h(report_id)}" if report_id else ""
    return (
        '<div class="immutable-statement">'
        "本认证由 Veritas 独立签发，不受任何利益方影响。"
        f"Immutable Record{id_suffix}"
        "</div>"
    )


def hero_metric(label: str, value: Any) -> str:
    return f"<div class='hero-stat'><div class='num'>{h(value)}</div><div class='label'>{h(label)}</div></div>"


def hero_pattern_list(patterns: list[dict[str, Any]]) -> str:
    """Render the top patterns in the hero section."""
    if not patterns:
        return "<p class='muted'>未形成重点摘要。请查看原始证据记录。</p>"
    rows = []
    for index, pattern in enumerate(patterns[:MAX_HERO_PATTERNS], start=1):
        source = str(pattern.get("summary_source") or "rule")
        rows.append(
            "<li>"
            f"<span class='rank'>{h(index)}</span>"
            "<span>"
            f"{_confidence_badge(source)}<span class='evidence-kicker'>{h(pattern.get('title'))}</span><br/>"
            f"{h(clean_report_text(pattern.get('thesis')))}"
            "</span>"
            "</li>"
        )
    return "<ol class='hero-evidence-list'>" + "".join(rows) + "</ol>"


def hero_action_list(tasks: list[dict[str, Any]]) -> str:
    """Render the action list in the hero section."""
    from engine.static_audit.html_report._manual_tasks import (
        is_context_only_manual_task,
        manual_task_focus_score,
    )

    visible_tasks = [
        task
        for task in tasks
        if isinstance(task, dict) and not is_context_only_manual_task(task)
    ]
    visible_tasks = sorted(visible_tasks, key=manual_task_focus_score)
    questions = [
        shorten(clean_report_text(task.get("question", "")), MAX_ACTION_QUESTION_LENGTH)
        for task in visible_tasks[:MAX_HERO_ACTIONS]
        if task.get("question")
    ]
    if not questions:
        questions = DEFAULT_ACTION_QUESTIONS
    return "<ul class='action-list'>" + list_items(questions) + "</ul>"


# ---------------------------------------------------------------------------
# Grade badge & dimension summary
# ---------------------------------------------------------------------------

#: Grade letter -> (CSS class, Chinese label)
_GRADE_META: dict[str, tuple[str, str]] = {
    "A": ("grade-a", "完全通过"),
    "B": ("grade-b", "有条件通过"),
    "C": ("grade-c", "待修订"),
    "D": ("grade-d", "未通过"),
}

#: Dimension status -> CSS class
_DIM_STATUS_CLASS: dict[str, str] = {
    "ok": "status-ok",
    "pass": "status-ok",
    "warn": "status-warn",
    "warning": "status-warn",
    "fail": "status-fail",
    "info": "status-info",
    "skipped": "status-info",
}


def grade_badge(grade: dict[str, Any] | None) -> str:
    """Render the certification grade badge for the hero section.

    Expects a dict with keys:
      - grade: "A" | "B" | "C" | "D"
      - label (optional): override Chinese label
    Returns empty string if grade is None or missing.
    """
    if not grade or not isinstance(grade, dict):
        return ""
    letter = str(grade.get("grade", "")).upper().strip()
    css_class, default_label = _GRADE_META.get(letter, ("", letter))
    label = str(grade.get("label") or default_label)
    if not css_class:
        return ""
    return (
        f'<div class="grade-badge-wrap">'
        f'<div class="grade-badge {css_class}">{h(letter)}</div>'
        f'<div class="grade-label">{h(label)}</div>'
        f"</div>"
    )


def dimension_summary(dimensions: list[dict[str, Any]] | None) -> str:
    """Render four dimension cards in a grid.

    Each dict should have: name (str), status (str), detail (str).
    Returns empty string if dimensions is None or empty.
    """
    if not dimensions:
        return ""
    cards = []
    for dim in dimensions[:4]:
        if not isinstance(dim, dict):
            continue
        name = str(dim.get("name", ""))
        status = str(dim.get("status", "info")).lower()
        detail = str(dim.get("detail", ""))
        status_class = _DIM_STATUS_CLASS.get(status, "status-info")
        cards.append(
            f'<div class="dim-card">'
            f'<div class="dim-name">{h(name)}</div>'
            f'<div class="dim-status {status_class}">{h(status.upper())}</div>'
            f'<div class="dim-detail">{h(detail)}</div>'
            f"</div>"
        )
    if not cards:
        return ""
    return f'<div class="dimension-grid">{"".join(cards)}</div>'


# ---------------------------------------------------------------------------
# Limitations
# ---------------------------------------------------------------------------


def collect_limitations(
    bundle: dict[str, Any], agent_judge: dict[str, Any], similarity: dict[str, Any]
) -> list[str]:
    """Collect limitation statements from bundle, judge, and similarity data."""
    limitations = ["本报告不做最终科研诚信判定，只展示技术记录和人工复核入口。"]
    if bundle.get("claim_mappings"):
        limitations.append(
            "论文表述与证据之间的映射仍需按原始 artifact 和 locator 人工确认。"
        )
    else:
        limitations.append("本次未生成稳定的论文表述与证据映射，表述影响需要人工补齐。")
    execution_status = (bundle.get("execution_status") or {}).get("status")
    if execution_status in {None, "", "not_provided", "not_run", "missing_material"}:
        limitations.append(
            f"代码执行审查未形成可用执行证据，execution_status={execution_status or 'unknown'}。"
        )
    if similarity.get("status") == "not_available":
        limitations.append("近似图像相似度未运行；只能说明 exact duplicate 未发现。")
    limitations.extend(
        str(item)
        for item in (bundle.get("limitations") or [])[:MAX_LIMITATIONS_FROM_BUNDLE]
    )
    limitations.extend(
        str(item)
        for item in (agent_judge.get("limitations") or [])[:MAX_LIMITATIONS_FROM_JUDGE]
    )
    return dedupe(limitations)
