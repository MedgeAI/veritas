"""Shared constants and small utility functions for HTML report generation.

This module is the lowest-level dependency in the html_report package.
All other sub-modules may import from here; this module must not import
from sibling sub-modules (except _html_utils).
"""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any

from engine.static_audit.html_report._html_utils import h

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_EVIDENCE_CARDS = 8
SOURCE_DATA_FINDINGS_ARTIFACT = "source_data_findings.json"
SOURCE_DATA_PAIR_FORENSICS_ARTIFACT = "source_data_pair_forensics.json"
ROW_VECTOR_SIGNAL_TOKENS = ("drv-", "duplicate_row_vector", "row vector", "行向量重复")
STRONGER_SIGNAL_TOKENS = (
    "dc-",
    "fr-",
    "fd-",
    "prr-",
    "pds-",
    "roe-",
    "vfc-",
    "数值列重复",
    "固定比例",
    "固定差",
    "配对比例",
    "配对差异",
    "区域完整性",
    "trufor",
    "copy",
)
CONF_BADGE_RE = re.compile(
    r"<span\s+class=[\"']conf-badge[^\"']*[\"'][^>]*>.*?</span>",
    re.IGNORECASE | re.DOTALL,
)
HUMAN_TEXT_REPLACEMENTS = (
    ("可疑伪造区域", "区域完整性记录"),
    ("伪造区域", "区域完整性记录"),
    ("伪造检测", "完整性检测"),
    ("非伪造的图像编辑", "常规图像编辑"),
    ("篡改可能性", "完整性差异"),
    ("图像 manipulations", "图像局部复用问题"),
    ("manipulations", "局部复用问题"),
    ("copy-move 伪造", "局部复用记录"),
    ("增加了机械构造的可能性", "需要确认是否由固定公式或导出流程造成"),
    ("机械构造", "固定生成过程"),
    ("极为罕见", "需要重点确认"),
    ("异常模式指向", "记录集中在"),
    ("异常模式", "记录模式"),
    ("异常狭窄", "过窄"),
    ("异常", "偏离预期"),
    ("可疑模式", "集中模式"),
    ("可疑", "需复核"),
    ("疑似人工凑整", "末位数字集中"),
    ("人为凑整信号", "末位数字集中"),
    ("疑似 p 值集中", "p 值集中"),
    ("疑似", "需复核"),
    ("p-hacking", "p 值集中"),
    ("风险较低", "优先级较低"),
    ("初步判断为", "当前记录显示为"),
    (
        "高 score 表示神经网络认为这些区域存在完整性差异",
        "score 较高，需查看 heatmap 和原图",
    ),
    ("虽然可能是", "需确认是否为"),
    ("可能表示", "需确认是否为"),
    ("可能反映", "需确认是否反映"),
    ("可能来自", "需确认是否来自"),
    ("可能由", "需确认是否由"),
    ("可能是", "需确认是否为"),
    ("造假", "数据完整性问题"),
    ("学术不端", "最终判断"),
    ("duplicate_numeric_columns", "数值列重复"),
    ("duplicate_row_vector", "行向量重复"),
    ("paired_difference_too_narrow", "配对差异过窄"),
    ("paired_ratio_reuse", "配对比例复用"),
    ("row_offset_exact_reuse", "固定行偏移重复"),
    ("paperfraud.fraud_detection", "数值取证提示"),
    ("paperfraud.methodology_review", "方法学提示"),
    ("fraud_detection", "数值取证提示"),
    ("fraud-pattern", "取证提示"),
    ("PaperFraud", "规则库"),
    ("claim-to-evidence", "论文表述与证据"),
    ("claim-to-code", "论文表述与代码"),
    ("finding reviews", "复核记录"),
    ("finding review", "复核记录"),
    ("manual tasks", "复核任务"),
    ("Agent review output", "复核输出"),
    ("copy-move", "局部相似"),
    ("copy_move", "局部相似"),
    ("support_rate", "支持率"),
    ("findings", "记录"),
    ("finding", "记录"),
    ("claims", "论文表述"),
    ("claim", "论文表述"),
    ("critical", "高优先级"),
    ("clusters", "证据簇"),
    ("cluster", "证据簇"),
    ("visual.局部相似_dense", "visual.copy_move_dense"),
    ("visual.局部相似", "visual.copy_move"),
    ("论文表述_extractor", "claim_extractor"),
    ("opencode Agent", "opencode 复核"),
    ("Agent Investigation Tool", "调查工具"),
    ("AgentInvestigationPlanner", "调查规划器"),
    ("规则库 规则库", "规则库"),
)

ISSUE_CATEGORY_LABELS = {
    "consistency": "一致性问题",
    "matching": "匹配问题",
    "completeness": "完整性问题",
}

CHAPTER_NUMBERS = {
    "consistency": "一",
    "matching": "二",
    "completeness": "三",
}


# ---------------------------------------------------------------------------
# Small utility functions
# ---------------------------------------------------------------------------


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def clean_report_text(value: Any) -> str:
    """Strip internal HTML badges if they accidentally enter text artifacts."""
    text = unescape(str(value or ""))
    text = CONF_BADGE_RE.sub("", text)
    text = " ".join(text.split())
    for source, target in HUMAN_TEXT_REPLACEMENTS:
        text = text.replace(source, target)
    return text


def shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def metric(label: str, value: Any) -> str:
    return f"<div class='metric'><div class='num'>{h(value)}</div><div class='label'>{h(label)}</div></div>"


def list_items(items: list[Any]) -> str:
    if not items:
        return "<li class='muted'>未记录。</li>"
    return "".join(f"<li>{h(clean_report_text(item))}</li>" for item in items)


def status_label(status: Any) -> str:
    labels = {
        "ran": "已执行",
        "reused": "已复用",
        "skipped": "已跳过",
        "warning": "警告",
        "failed": "失败",
        "not_run": "未运行",
        "not_provided": "未提供",
        "missing_material": "材料缺失",
        "selected": "已选择",
        "unsupported": "暂不支持",
        "present": "已生成",
        "missing": "缺失",
        "ok": "正常",
        "not_available": "不可用",
    }
    return labels.get(str(status), str(status))


def risk_label(risk: Any) -> str:
    labels = {
        "critical": "最高优先级",
        "high": "高优先级",
        "medium": "中优先级",
        "low": "低优先级",
        "info": "提示",
        "context": "上下文记录",
    }
    return labels.get(str(risk), str(risk))


def risk_score(risk: Any) -> int:
    return {
        "critical": 4,
        "high": 3,
        "medium": 2,
        "low": 1,
        "info": 0,
        "context": 0,
    }.get(str(risk), 0)


def category_label(category: Any) -> str:
    labels = {
        "duplicate_numeric_columns": "数值列重复",
        "fixed_difference": "固定差关系",
        "fixed_ratio": "固定比例关系",
        "formula_derived_columns": "公式派生列",
        "row_offset_scalar_multiple": "固定行偏移标量关系",
        "long_format_paired_ratio_reuse": "配对比例复用",
        "duplicate_row_vector": "行向量重复",
        "long_format_within_pair_ratio_enrichment": "配对内部比例富集",
        "row_offset_partial_copy_rounding_bias": "行偏移复制/舍入偏差",
        "copy_move_single": "单图内局部相似",
        "copy_move_cross": "跨图局部相似",
        "exact_duplicate": "字节级完全重复",
        "dhash_similar": "感知哈希相似",
        "overlap_reuse_cross_panel": "跨 Panel 局部重叠",
        "forged_region_suspicious": "区域完整性记录",
        "paperfraud.methodology_review": "方法学提示",
        "paperfraud.fraud_detection": "数值取证提示",
    }
    return labels.get(str(category), str(category))


def summary_text(summary: dict[str, Any]) -> str:
    parts = []
    for key, value in summary.items():
        if isinstance(value, (str, int, float)):
            parts.append(f"{key}={str(value)[:90]}")
    return "; ".join(parts[:4]) or "-"


def _confidence_badge(source_type: str) -> str:
    """Return HTML for a small badge indicating the source of an explanation/text element."""
    badges = {
        "rule": '<span class="conf-badge conf-rule">仅原始记录</span>',
        "data": '<span class="conf-badge conf-data">证据记录</span>',
        "agent": '<span class="conf-badge conf-agent">复核摘要</span>',
    }
    return badges.get(source_type, "")


def has_row_vector_signal_text(text: Any) -> bool:
    normalized = str(text or "").lower()
    return any(token in normalized for token in ROW_VECTOR_SIGNAL_TOKENS)


def has_stronger_signal_text(text: Any) -> bool:
    normalized = str(text or "").lower()
    return any(token in normalized for token in STRONGER_SIGNAL_TOKENS)


def ref_mentions_finding(ref: Any, finding_ids: list[str]) -> bool:
    text = json.dumps(ref, ensure_ascii=False) if isinstance(ref, dict) else str(ref)
    return any(finding_id and finding_id in text for finding_id in finding_ids)


# ---------------------------------------------------------------------------
# Pattern key mapping (placed here to break circular import between
# _patterns.py and _benign.py).
# ---------------------------------------------------------------------------


def pattern_key_for_finding(finding: dict[str, Any]) -> str:
    category = str(finding.get("category", ""))
    source_artifact = str(finding.get("source_artifact", ""))
    if category in {
        "row_offset_scalar_multiple",
        "long_format_paired_ratio_reuse",
        "long_format_within_pair_ratio_enrichment",
    }:
        return "paired_offset_ratio_reuse"
    if category == "duplicate_row_vector":
        return "row_vector_reuse"
    if category == "row_offset_partial_copy_rounding_bias":
        return "partial_copy_rounding_bias"
    if category == "duplicate_numeric_columns":
        return "duplicate_numeric_columns"
    if category in {
        "formula_derived_column",
        "formula_derived_columns",
        "fixed_ratio",
        "fixed_difference",
    }:
        return "formula_derivation"
    category_text = category.lower()
    source_text = source_artifact.lower()
    if any(
        token in category_text or token in source_text
        for token in (
            "image",
            "visual",
            "panel",
            "trufor",
            "copy_move",
            "cbir",
            "similarity",
            "overlap",
        )
    ):
        return "visual_forensics"
    if any(
        token in category_text or token in source_text
        for token in ("numeric", "benford", "number")
    ):
        return "numeric_forensics"
    if any(
        token in category_text or token in source_text
        for token in ("execution", "command", "runtime")
    ):
        return "execution_evidence"
    if category:
        return f"category:{category}"
    return "other"


# ---------------------------------------------------------------------------
# Finding display helpers (placed here so that _source_data.py and
# _findings.py both import from _shared without circular dependency).
# ---------------------------------------------------------------------------


def is_context_only_finding(finding: dict[str, Any]) -> bool:
    return str(finding.get("category") or "") == "duplicate_row_vector"


def display_risk_level_for_finding(finding: dict[str, Any]) -> str:
    if is_context_only_finding(finding):
        return "context"
    return str(finding.get("risk_level") or "medium")


def finding_display_score(finding: dict[str, Any]) -> int:
    return risk_score(display_risk_level_for_finding(finding))


def highest_display_risk(findings: list[dict[str, Any]]) -> str:
    levels = [
        display_risk_level_for_finding(finding)
        for finding in findings
        if isinstance(finding, dict)
    ]
    return max(levels, key=risk_score, default="medium")


def finding_support_value(finding: dict[str, Any]) -> int:
    for key in (
        "support_rows",
        "matched_pairs",
        "matched_pair_groups",
        "duplicate_row_count",
        "exact_reuse_pairs",
        "equal_rows",
    ):
        value = finding.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return 0
