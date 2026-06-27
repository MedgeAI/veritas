"""Step key -> user-friendly label mapping for the static audit pipeline.

This module is the single source of truth for mapping internal step keys
(e.g. ``visual_panel_extraction``) to user-friendly display names and
phase groupings consumed by the front-end progress UI.

The mapping covers every step key emitted by ``pipeline.py``,
``_pipeline_steps.py``, ``visual_pipeline.py``, ``figure_classification.py``,
and ``investigation_dispatch.py``.

Unknown keys fall back to a generated title (underscores replaced with
spaces, title-cased) so the front-end always has *something* to display.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Phase ordering constants
# ---------------------------------------------------------------------------
_PHASE_PREPARE = "准备"
_PHASE_DOC_PARSE = "文档解析"
_PHASE_NUMERIC = "数值取证"
_PHASE_DATA_ANALYSIS = "数据分析"
_PHASE_VISUAL = "视觉取证"
_PHASE_AGENT = "Agent 审查"
_PHASE_REPORT = "报告生成"

_ORDER_PREPARE = 1
_ORDER_DOC_PARSE = 2
_ORDER_NUMERIC = 3
_ORDER_DATA_ANALYSIS = 4
_ORDER_VISUAL = 5
_ORDER_AGENT = 6
_ORDER_REPORT = 7

# ---------------------------------------------------------------------------
# Step label mapping
# ---------------------------------------------------------------------------

STEP_LABELS: dict[str, dict[str, Any]] = {
    # -- Phase 1: 准备 -------------------------------------------------------
    "discover": {
        "title": "发现输入材料",
        "phase": _PHASE_PREPARE,
        "phase_order": _ORDER_PREPARE,
    },
    "material_inventory": {
        "title": "材料清单扫描",
        "phase": _PHASE_PREPARE,
        "phase_order": _ORDER_PREPARE,
    },
    "figure_classification": {
        "title": "图像类型分类",
        "phase": _PHASE_PREPARE,
        "phase_order": _ORDER_PREPARE,
    },
    "agent_material_plan": {
        "title": "材料计划",
        "phase": _PHASE_PREPARE,
        "phase_order": _ORDER_PREPARE,
    },
    "agent_plan": {
        "title": "审查计划",
        "phase": _PHASE_PREPARE,
        "phase_order": _ORDER_PREPARE,
    },
    # -- Phase 2: 文档解析 ---------------------------------------------------
    "mineru": {
        "title": "PDF 解析",
        "phase": _PHASE_DOC_PARSE,
        "phase_order": _ORDER_DOC_PARSE,
    },
    "evidence_ledger": {
        "title": "构建证据索引",
        "phase": _PHASE_DOC_PARSE,
        "phase_order": _ORDER_DOC_PARSE,
    },
    # -- Phase 3: 数值取证 ---------------------------------------------------
    "numeric_forensics": {
        "title": "数值取证",
        "phase": _PHASE_NUMERIC,
        "phase_order": _ORDER_NUMERIC,
    },
    "paperconan_scan": {
        "title": "GRIM/GRIMMER 检测",
        "phase": _PHASE_NUMERIC,
        "phase_order": _ORDER_NUMERIC,
    },
    "paperfraud_rule_match": {
        "title": "规则库匹配",
        "phase": _PHASE_NUMERIC,
        "phase_order": _ORDER_NUMERIC,
    },
    # -- Phase 4: 数据分析 ---------------------------------------------------
    "source_data_profile": {
        "title": "Source Data 画像",
        "phase": _PHASE_DATA_ANALYSIS,
        "phase_order": _ORDER_DATA_ANALYSIS,
    },
    "source_data_findings": {
        "title": "Source Data 发现",
        "phase": _PHASE_DATA_ANALYSIS,
        "phase_order": _ORDER_DATA_ANALYSIS,
    },
    "source_data_pair_forensics": {
        "title": "数值对取证",
        "phase": _PHASE_DATA_ANALYSIS,
        "phase_order": _ORDER_DATA_ANALYSIS,
    },
    "source_data_cross_sheet": {
        "title": "跨 Sheet 检测",
        "phase": _PHASE_DATA_ANALYSIS,
        "phase_order": _ORDER_DATA_ANALYSIS,
    },
    "source_data_briefings": {
        "title": "Sheet 简报",
        "phase": _PHASE_DATA_ANALYSIS,
        "phase_order": _ORDER_DATA_ANALYSIS,
    },
    "source_data_verdict": {
        "title": "Source Data 裁决",
        "phase": _PHASE_DATA_ANALYSIS,
        "phase_order": _ORDER_DATA_ANALYSIS,
    },
    # -- Phase 5: 视觉取证 ---------------------------------------------------
    "exact_image_duplicates": {
        "title": "图片字节级去重",
        "phase": _PHASE_VISUAL,
        "phase_order": _ORDER_VISUAL,
    },
    "image_similarity_candidates": {
        "title": "图片近似相似候选",
        "phase": _PHASE_VISUAL,
        "phase_order": _ORDER_VISUAL,
    },
    "visual_panel_extraction": {
        "title": "图片拆分",
        "phase": _PHASE_VISUAL,
        "phase_order": _ORDER_VISUAL,
    },
    "visual_tru_for": {
        "title": "TruFor 伪造检测",
        "phase": _PHASE_VISUAL,
        "phase_order": _ORDER_VISUAL,
    },
    "visual_copy_move": {
        "title": "Copy-Move 检测",
        "phase": _PHASE_VISUAL,
        "phase_order": _ORDER_VISUAL,
    },
    "visual_copy_move_dense": {
        "title": "SILA 密集 Copy-Move",
        "phase": _PHASE_VISUAL,
        "phase_order": _ORDER_VISUAL,
    },
    "visual_image_quality": {
        "title": "图片质量异常",
        "phase": _PHASE_VISUAL,
        "phase_order": _ORDER_VISUAL,
    },
    "visual_provenance_graph": {
        "title": "溯源图构建",
        "phase": _PHASE_VISUAL,
        "phase_order": _ORDER_VISUAL,
    },
    "visual_finding_pipeline": {
        "title": "视觉证据聚合",
        "phase": _PHASE_VISUAL,
        "phase_order": _ORDER_VISUAL,
    },
    "visual_overlap_reuse": {
        "title": "Overlap/Reuse 检测",
        "phase": _PHASE_VISUAL,
        "phase_order": _ORDER_VISUAL,
    },
    # -- Phase 6: Agent 审查 -------------------------------------------------
    "investigation": {
        "title": "Agent 调查轮次",
        "phase": _PHASE_AGENT,
        "phase_order": _ORDER_AGENT,
    },
    "investigation_fallback": {
        "title": "调查 fallback 工具",
        "phase": _PHASE_AGENT,
        "phase_order": _ORDER_AGENT,
    },
    "agent_review": {
        "title": "Agent 审查",
        "phase": _PHASE_AGENT,
        "phase_order": _ORDER_AGENT,
    },
    "agent_roles": {
        "title": "Agent 角色层",
        "phase": _PHASE_AGENT,
        "phase_order": _ORDER_AGENT,
    },
    # -- Phase 7: 报告生成 ---------------------------------------------------
    "static_audit_bundle": {
        "title": "生成审查包",
        "phase": _PHASE_REPORT,
        "phase_order": _ORDER_REPORT,
    },
    "certification_grade": {
        "title": "认证评级计算",
        "phase": _PHASE_REPORT,
        "phase_order": _ORDER_REPORT,
    },
    "report": {
        "title": "生成 Markdown 报告",
        "phase": _PHASE_REPORT,
        "phase_order": _ORDER_REPORT,
    },
    "html_report": {
        "title": "生成 HTML 报告",
        "phase": _PHASE_REPORT,
        "phase_order": _ORDER_REPORT,
    },
}

_UNKNOWN_PHASE = "Unknown"
_UNKNOWN_PHASE_ORDER = 99


def get_step_label(key: str) -> dict[str, Any]:
    """Return a display label dict for the given step *key*.

    Returns a dict with ``title``, ``phase``, and ``phase_order`` keys.
    If *key* is not in :data:`STEP_LABELS`, a fallback is generated:
    underscores are replaced with spaces and the result is title-cased,
    phase is ``"Unknown"``, and ``phase_order`` is ``99``.
    """
    if key in STEP_LABELS:
        return STEP_LABELS[key]
    return {
        "title": key.replace("_", " ").title(),
        "phase": _UNKNOWN_PHASE,
        "phase_order": _UNKNOWN_PHASE_ORDER,
    }
