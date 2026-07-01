"""Certification grade engine for Veritas audit results.

Computes a 4-dimension score and overall grade (A/B/C/D) from a
StaticAuditBundle.  Each dimension is scored independently; the overall
grade is derived from the worst dimension status.

Dimensions:
    1. Reproducibility  — pipeline step success
    2. Numerical Fidelity — consistency findings severity
    3. Methodology — completeness findings and layer-1 issues
    4. Interpretation — methodology_review findings and layer-3 status
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from engine.shared.helpers import classify_finding
from engine.static_audit.models import Finding, StaticAuditBundle, ToolRun

logger = logging.getLogger(__name__)

# Pipeline steps that are mandatory for any meaningful audit.
_REPRODUCIBILITY_CRITICAL_STEPS = frozenset({
    "discover",
    "material_inventory",
    "mineru",
    "evidence_ledger",
})

# Risk levels considered severe enough to fail or warn a dimension.
_CRITICAL_HIGH = frozenset({"critical", "high"})

# Dimension status ordering (worst-first).
_STATUS_SEVERITY: dict[str, int] = {
    "pass": 0,
    "pass_with_notes": 1,
    "warning": 2,
    "fail": 3,
}

DimensionStatus = Literal["pass", "pass_with_notes", "warning", "fail"]


# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    """Score for a single certification dimension."""

    name: str
    label: str
    status: DimensionStatus
    detail: str
    finding_refs: list[str] = field(default_factory=list)


@dataclass
class CertificationGrade:
    """Overall certification grade with per-dimension breakdown."""

    grade: str  # "A", "B", "C", "D"
    label: str  # Chinese label
    dimensions: list[DimensionScore]
    summary: str
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    reproducibility_tier: str = "full"
    grade_cap: str = "A"
    raw_grade: str | None = None


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def _find_step_status(tool_runs: list[ToolRun], step_key: str) -> str | None:
    """Return the status of a pipeline step, or None if not present."""
    for run in tool_runs:
        if run.step_key == step_key:
            return run.status
    return None


def _score_reproducibility(bundle: StaticAuditBundle) -> DimensionScore:
    """Score dimension 1: reproducibility based on pipeline step success."""
    failed_critical: list[str] = []
    for step_key in _REPRODUCIBILITY_CRITICAL_STEPS:
        status = _find_step_status(bundle.tool_runs, step_key)
        if status == "failed":
            failed_critical.append(step_key)

    if failed_critical:
        return DimensionScore(
            name="reproducibility",
            label="可复现性",
            status="fail",
            detail=f"关键流水线步骤失败: {', '.join(failed_critical)}",
        )

    # Check source_data steps: selected but failed → warning.
    failed_source: list[str] = []
    for run in bundle.tool_runs:
        if run.step_key.startswith("source_data") and run.status == "failed":
            failed_source.append(run.step_key)

    if failed_source:
        return DimensionScore(
            name="reproducibility",
            label="可复现性",
            status="warning",
            detail=f"Source data 步骤失败: {', '.join(failed_source)}",
        )

    return DimensionScore(
        name="reproducibility",
        label="可复现性",
        status="pass",
        detail="所有关键流水线步骤成功执行",
    )


def _score_numerical_fidelity(findings: list[Finding]) -> DimensionScore:
    """Score dimension 2: numerical fidelity based on consistency findings."""
    consistency = [f for f in findings if f.issue_category == "consistency"]
    refs = [f.finding_id for f in consistency]

    if not consistency:
        return DimensionScore(
            name="numerical_fidelity",
            label="数字一致性",
            status="pass",
            detail="未发现数据一致性问题",
        )

    has_critical_high = any(f.risk_level in _CRITICAL_HIGH for f in consistency)
    if has_critical_high:
        return DimensionScore(
            name="numerical_fidelity",
            label="数字一致性",
            status="fail",
            detail="发现严重数据一致性问题",
            finding_refs=refs,
        )

    has_medium = any(f.risk_level == "medium" for f in consistency)
    if has_medium:
        return DimensionScore(
            name="numerical_fidelity",
            label="数字一致性",
            status="warning",
            detail="发现中等数据一致性问题",
            finding_refs=refs,
        )

    return DimensionScore(
        name="numerical_fidelity",
        label="数字一致性",
        status="pass_with_notes",
        detail="仅有低风险数据一致性问题",
        finding_refs=refs,
    )


def _score_methodology(findings: list[Finding]) -> DimensionScore:
    """Score dimension 3: methodology based on completeness findings."""
    completeness = [f for f in findings if f.issue_category == "completeness"]
    refs = [f.finding_id for f in completeness]

    has_critical_high = any(f.risk_level in _CRITICAL_HIGH for f in completeness)
    if has_critical_high:
        return DimensionScore(
            name="methodology",
            label="方法学",
            status="warning",
            detail="发现严重方法学完整性问题",
            finding_refs=refs,
        )

    # Layer 1 findings related to data leakage or statistical issues.
    _method_keywords = ("data_leakage", "statistical", "leakage")
    layer1_methodology: list[str] = []
    for f in findings:
        fdict = {"risk_level": f.risk_level, "category": f.category}
        layer = classify_finding(fdict)
        if layer == "layer_1" and any(kw in f.category for kw in _method_keywords):
            layer1_methodology.append(f.finding_id)

    if layer1_methodology:
        return DimensionScore(
            name="methodology",
            label="方法学",
            status="warning",
            detail="发现需要关注的方法学问题",
            finding_refs=list(dict.fromkeys(refs + layer1_methodology)),
        )

    return DimensionScore(
        name="methodology",
        label="方法学",
        status="pass",
        detail="未发现重大方法学问题",
        finding_refs=refs if completeness else [],
    )


def _score_interpretation(findings: list[Finding]) -> DimensionScore:
    """Score dimension 4: interpretation based on methodology_review."""
    methodology_review = [
        f for f in findings if f.category == "paperfraud.methodology_review"
    ]
    refs = [f.finding_id for f in methodology_review]

    if methodology_review:
        return DimensionScore(
            name="interpretation",
            label="解读合理性",
            status="warning",
            detail="发现方法学解读相关问题",
            finding_refs=refs,
        )

    # Layer 3 findings only (non-critical) → pass_with_notes.
    non_layer3: list[Finding] = []
    for f in findings:
        fdict = {"risk_level": f.risk_level, "category": f.category}
        layer = classify_finding(fdict)
        if layer != "layer_3":
            non_layer3.append(f)

    if not non_layer3 and findings:
        all_refs = [f.finding_id for f in findings]
        return DimensionScore(
            name="interpretation",
            label="解读合理性",
            status="pass_with_notes",
            detail="仅有信息级别发现",
            finding_refs=all_refs,
        )

    return DimensionScore(
        name="interpretation",
        label="解读合理性",
        status="pass",
        detail="未发现解读问题",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_GRADE_LABELS: dict[str, str] = {
    "A": "完全通过",
    "B": "有条件通过",
    "C": "待修订",
    "D": "未通过",
}

_GRADE_RANK: dict[str, int] = {
    "A": 0,
    "B": 1,
    "C": 2,
    "D": 3,
}

_REPRODUCIBILITY_TIER_CAPS: dict[str, str] = {
    "full": "A",
    "partial": "B",
    "code_only": "C",
    "static": "C",
}


def _worst_status(dimensions: list[DimensionScore]) -> DimensionStatus:
    """Return the worst status across all dimensions."""
    return max(
        (d.status for d in dimensions),
        key=lambda s: _STATUS_SEVERITY.get(s, 0),
    )


def _cap_grade(raw_grade: str, reproducibility_tier: str) -> tuple[str, str]:
    """Apply the reproducibility-tier ceiling without improving worse grades."""
    cap = _REPRODUCIBILITY_TIER_CAPS.get(reproducibility_tier)
    if cap is None:
        raise ValueError(
            "Invalid reproducibility_tier: "
            f"{reproducibility_tier}. Must be one of: "
            f"{', '.join(_REPRODUCIBILITY_TIER_CAPS.keys())}"
        )
    if _GRADE_RANK[raw_grade] < _GRADE_RANK[cap]:
        return cap, cap
    return raw_grade, cap


def compute_grade(
    bundle: StaticAuditBundle,
    *,
    reproducibility_tier: str = "full",
) -> CertificationGrade:
    """Compute certification grade from audit bundle.

    The function evaluates four independent dimensions and derives an
    overall grade:
        A — all dimensions pass or pass_with_notes
        B — at least one warning, no dimension fails
        C — a dimension fails but reproducibility is not fully broken
        D — reproducibility fails (environment/data broken)
    """
    findings = bundle.findings

    reproducibility = _score_reproducibility(bundle)
    numerical_fidelity = _score_numerical_fidelity(findings)
    methodology = _score_methodology(findings)
    interpretation = _score_interpretation(findings)

    dimensions = [reproducibility, numerical_fidelity, methodology, interpretation]
    worst = _worst_status(dimensions)

    if worst == "fail":
        if reproducibility.status == "fail":
            raw_grade = "D"
        else:
            raw_grade = "C"
    elif worst == "warning":
        raw_grade = "B"
    else:
        raw_grade = "A"

    grade, grade_cap = _cap_grade(raw_grade, reproducibility_tier)

    total = len(findings)
    critical_count = sum(1 for f in findings if f.risk_level == "critical")
    high_count = sum(1 for f in findings if f.risk_level == "high")
    medium_count = sum(1 for f in findings if f.risk_level == "medium")

    summary = _build_summary(raw_grade, total)
    if grade != raw_grade:
        summary = f"{summary}；受材料可复现等级限制，最高评级为 {grade_cap}"

    return CertificationGrade(
        grade=grade,
        label=_GRADE_LABELS[grade],
        dimensions=dimensions,
        summary=summary,
        total_findings=total,
        critical_count=critical_count,
        high_count=high_count,
        medium_count=medium_count,
        reproducibility_tier=reproducibility_tier,
        grade_cap=grade_cap,
        raw_grade=raw_grade,
    )


def _build_summary(grade: str, total: int) -> str:
    """Build a one-line summary string for the report header."""
    if grade == "A":
        if total == 0:
            return "审计完成，未发现风险问题"
        return f"审计完成，发现 {total} 个问题，均为低风险"
    if grade == "B":
        return f"审计完成，发现 {total} 个问题，存在需要关注的风险项"
    if grade == "C":
        return f"审计完成，发现 {total} 个问题，存在需要修订的风险项"
    return f"审计完成，发现 {total} 个问题，流水线执行异常，无法完成完整评估"
