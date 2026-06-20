"""Phase 3 — Design specification for new detection capabilities.

Generates a structured design spec for each gap that requires a NEW_DETECTOR.
The spec defines input/output/test contracts and includes anti-overfit checks.
**Human approval is required before proceeding to implementation.**
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from engine.ground_truth.gap_analyzer import GapRecord


@dataclass
class DesignSpec:
    """Design specification for a new detection capability."""

    capability_id: str
    driven_by: str
    input_contract: dict[str, str]
    output_contract: dict[str, str]
    test_contract: list[str]
    anti_overfit_checklist: list[dict[str, str]] = field(default_factory=list)
    human_approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_TEMPLATES: dict[str, dict[str, Any]] = {
    "visual": {
        "input_contract": {
            "images": "Directory of figure images (PNG/JPG)",
            "panel_evidence": "visual/panel_evidence.json with crop paths",
        },
        "output_contract": {
            "relationships": "List of image_relationship records",
            "artifact": "visual/<tool_name>.json with schema_version",
        },
    },
    "source_data": {
        "input_contract": {
            "source_data_dir": "Directory containing XLSX/CSV source data files",
            "sheet_vectors": "Parsed numeric columns per sheet",
        },
        "output_contract": {
            "findings": "List of finding records with category, risk_level, support",
            "artifact": "source_data/<tool_name>.json with schema_version",
        },
    },
    "numeric": {
        "input_contract": {
            "numeric_columns": "Extracted numeric columns from source data",
        },
        "output_contract": {
            "anomalies": "List of numeric anomaly records",
            "artifact": "numeric/<tool_name>.json",
        },
    },
    "completeness": {
        "input_contract": {
            "material_inventory": "materials/material_inventory.json",
            "claims": "Extracted claims referencing specific materials",
        },
        "output_contract": {
            "gaps": "List of missing material records",
            "artifact": "source_data/completeness.json",
        },
    },
}


def generate_design_spec(gap: GapRecord) -> DesignSpec:
    """Generate a design specification for a new detector.

    The spec is populated from templates based on the capability category.
    Anti-overfit checklist is always included.
    """
    category = (
        gap.capability_id.split(".")[0] if "." in gap.capability_id else "unknown"
    )
    template = _TEMPLATES.get(category, _TEMPLATES["visual"])

    return DesignSpec(
        capability_id=gap.capability_id,
        driven_by=gap.claim_description,
        input_contract=template["input_contract"],
        output_contract=template["output_contract"],
        test_contract=[
            f"Test 1: {gap.claim_target} — reproduces the ground-truth claim",
            "Test 2: negative control — similar but not matching input produces no finding",
            "Test 3: boundary control — edge-case input behaves predictably",
        ],
        anti_overfit_checklist=[
            {"rule": "通用接口", "check": "函数签名中无 paper-specific 参数"},
            {
                "rule": "无硬编码",
                "check": "代码中无特定 figure number / sheet name / row offset 字面量",
            },
            {
                "rule": "跨论文验证",
                "check": "至少 3 篇论文验证（1 ground truth + 2 对照）",
            },
            {
                "rule": "阈值分布",
                "check": "阈值从统计分布推导，distribution_analysis.md 作为 artifact",
            },
            {"rule": "测试先行", "check": "测试文件创建时间 ≤ 实现文件创建时间"},
        ],
    )
