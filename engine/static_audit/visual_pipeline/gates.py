"""5-gate visual finding pipeline.

Each gate is a pure function: ``GateContext`` in → ``GateResult`` out.
Gates are composed into a pipeline that replaces the scattered
conditional logic in ``_build_relationship_finding`` and
``_build_trufor_finding``.

Gate order:
  1. **modality_gate** — skip code-generated panels (Graphs)
  2. **artifact_quality_gate** — cap/demote for whole_figure_fallback
  3. **local_evidence_gate** — score threshold + risk level computation
  4. **geometry_verification_gate** — corroboration-based demotion
  5. **semantic_review_gate** — language compliance + benign explanations

See PRD ``docs/product/Veritas-视觉能力产品化改进PRD-ELIS边界-20260706.md``
§6.1 and §7 Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from engine.static_audit.tools.visual_finding_pipeline import (
    BENIGN_EXPLANATIONS,
    MANUAL_REVIEW_QUESTIONS,
    _cap_risk_level,
    _dominant_modality,
    _generate_summary,
    _generate_trufor_summary,
    _panel_extraction_quality,
    _parent_figure_id,
    _resolve_panel,
    _risk_rank,
    compute_risk_level,
)
from engine.static_audit.visual_pipeline.demotion_filter import (
    DEFAULT_DEMOTION_RULES,
    DEMOTABLE_CATEGORIES,
    _scope_key,
)
from engine.static_audit.visual_schemas import check_language_compliance

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RISK_RANK: dict[str, int] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

#: Panel types that are code-generated and should skip visual findings.
VISUAL_SKIP_PANEL_TYPES: frozenset[str] = frozenset({"Graphs", "Flow Cytometry"})

#: Minimum extraction confidence for modality skip to take effect.
VISUAL_SKIP_CONFIDENCE_THRESHOLD: float = 0.5


# ---------------------------------------------------------------------------
# Gate verdicts
# ---------------------------------------------------------------------------


class GateVerdict(str, Enum):
    """Outcome of a single gate evaluation."""

    PASS = "pass"
    SKIP = "skip"
    CAP = "cap"
    REJECT = "reject"
    DEMOTE = "demote"


# ---------------------------------------------------------------------------
# Gate context and result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateContext:
    """Immutable input to every gate.

    Carries all data a gate might need.  Gates read from this but never
    mutate it.  The pipeline threads a single context through all gates,
    accumulating adjustments.
    """

    # --- Identity ---
    source_panel_id: str
    target_panel_id: str
    source_type: str

    # --- Scores ---
    raw_score: float
    normalized_score: float

    # --- Panel metadata ---
    source_panel: dict[str, Any] = field(default_factory=dict)
    target_panel: dict[str, Any] = field(default_factory=dict)
    panel_type: str | None = None

    # --- Relationship-level ---
    overlay_path: str | None = None
    flip_detected: bool = False
    match_method: str = ""
    inlier_count: int = 0
    relationship_id: str = ""

    # --- TruFor-specific ---
    figure_id: str = ""
    integrity_score: float = 0.0
    confidence_map_path: str | None = None
    forged_region_evidence_id: str = ""

    # --- Corroboration ---
    corroboration_families: frozenset[str] = frozenset()

    # --- Thresholds ---
    high_score_threshold: float = 0.4

    @property
    def is_trufor(self) -> bool:
        return self.source_type == "forged_region_suspicious"


@dataclass
class GateResult:
    """Accumulated result from the gate pipeline."""

    verdict: GateVerdict = GateVerdict.PASS
    risk_level: str = "low"
    displayed_score: float = 0.0
    confidence_adjustments: list[str] = field(default_factory=list)

    # Final finding data
    summary: str = ""
    benign_explanations: list[str] = field(default_factory=list)
    manual_review_questions: list[str] = field(default_factory=list)
    overlay_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Skip/reject/demote provenance
    skip_reason: str = ""


# ---------------------------------------------------------------------------
# Gate 1: Modality Gate
# ---------------------------------------------------------------------------


def modality_gate(ctx: GateContext) -> GateResult:
    """Skip findings on code-generated panels.

    - exact_duplicate / dhash_similar → always PASS
    - copy_move / overlap_reuse on Graphs → SKIP
    - Otherwise → PASS
    """
    # Never skip exact_duplicate or dhash_similar
    if ctx.source_type in ("exact_duplicate", "dhash_similar"):
        return GateResult()

    skippable_types = {
        "copy_move_single",
        "copy_move_cross",
        "overlap_reuse_cross_panel",
        "forged_region_suspicious",
    }
    if ctx.source_type not in skippable_types:
        return GateResult()

    panel_type = ctx.panel_type
    if panel_type not in VISUAL_SKIP_PANEL_TYPES:
        return GateResult()

    # Check extraction confidence
    src_conf = float(ctx.source_panel.get("extraction_confidence", 0) or 0)
    tgt_conf = float(ctx.target_panel.get("extraction_confidence", 0) or 0)
    if max(src_conf, tgt_conf) < VISUAL_SKIP_CONFIDENCE_THRESHOLD:
        return GateResult()

    return GateResult(
        verdict=GateVerdict.SKIP,
        skip_reason=f"code-generated modality: {panel_type}",
    )


# ---------------------------------------------------------------------------
# Gate 2: Artifact Quality Gate
# ---------------------------------------------------------------------------


def artifact_quality_gate(ctx: GateContext, prev: GateResult) -> GateResult:
    """Cap risk when panel extraction quality is degraded."""
    result = GateResult(
        verdict=prev.verdict,
        risk_level=prev.risk_level,
        displayed_score=prev.displayed_score or ctx.normalized_score,
        confidence_adjustments=list(prev.confidence_adjustments),
    )

    quality = _panel_extraction_quality(ctx.source_panel, ctx.target_panel)
    if quality == "whole_figure_fallback":
        result.displayed_score = min(result.displayed_score, 0.39)
        result.risk_level = _cap_risk_level(
            compute_risk_level(result.displayed_score, modality=ctx.panel_type),
            "medium",
        )
        result.confidence_adjustments.append(
            "risk capped because at least one panel is whole_figure_fallback"
        )

    return result


# ---------------------------------------------------------------------------
# Gate 3: Local Evidence Gate
# ---------------------------------------------------------------------------


def local_evidence_gate(ctx: GateContext, prev: GateResult) -> GateResult:
    """Apply score threshold and compute base risk level."""
    result = GateResult(
        verdict=prev.verdict,
        risk_level=prev.risk_level,
        displayed_score=prev.displayed_score or ctx.normalized_score,
        confidence_adjustments=list(prev.confidence_adjustments),
    )

    if ctx.normalized_score < ctx.high_score_threshold:
        result.verdict = GateVerdict.REJECT
        result.skip_reason = (
            f"score {ctx.normalized_score:.3f} < threshold {ctx.high_score_threshold}"
        )
        return result

    # Compute base risk from score + modality
    if not result.risk_level or result.risk_level == "low":
        result.risk_level = compute_risk_level(
            result.displayed_score, modality=ctx.panel_type
        )

    # Source-type-specific risk caps
    if ctx.panel_type in {"Graphs", "Flow Cytometry"} and ctx.source_type in {
        "copy_move_single",
        "copy_move_cross",
        "overlap_reuse_cross_panel",
    }:
        result.risk_level = _cap_risk_level(result.risk_level, "medium")
        result.confidence_adjustments.append(
            f"risk capped because {ctx.panel_type} panels often match "
            "axes, text, legends, or plot geometry"
        )

    if ctx.source_type == "overlap_reuse_cross_panel":
        result.risk_level = _cap_risk_level(result.risk_level, "high")

    return result


# ---------------------------------------------------------------------------
# Gate 4: Geometry Verification Gate
# ---------------------------------------------------------------------------


def geometry_verification_gate(ctx: GateContext, prev: GateResult) -> GateResult:
    """Apply corroboration-based demotion."""
    result = GateResult(
        verdict=prev.verdict,
        risk_level=prev.risk_level,
        displayed_score=prev.displayed_score,
        confidence_adjustments=list(prev.confidence_adjustments),
    )

    if ctx.source_type not in DEMOTABLE_CATEGORIES:
        return result

    rule_map = {r.category: r for r in DEFAULT_DEMOTION_RULES}
    rule = rule_map.get(ctx.source_type)
    if rule is None:
        return result

    corroborating = ctx.corroboration_families & rule.requires_any_of
    if not corroborating:
        result.verdict = GateVerdict.DEMOTE
        result.skip_reason = rule.reason

    return result


# ---------------------------------------------------------------------------
# Gate 5: Semantic Review Gate
# ---------------------------------------------------------------------------


def semantic_review_gate(ctx: GateContext, prev: GateResult) -> GateResult:
    """Generate text fields and enforce language compliance."""
    result = GateResult(
        verdict=prev.verdict,
        risk_level=prev.risk_level,
        displayed_score=prev.displayed_score,
        confidence_adjustments=list(prev.confidence_adjustments),
    )

    # Skip text generation for non-passing findings
    if result.verdict not in (GateVerdict.PASS, GateVerdict.CAP):
        return result

    # Generate text
    if ctx.is_trufor:
        summary = _generate_trufor_summary(ctx.figure_id, ctx.integrity_score)
        benign = list(BENIGN_EXPLANATIONS["forged_region_suspicious"])
        questions = list(MANUAL_REVIEW_QUESTIONS["forged_region_suspicious"])
    else:
        summary = _generate_summary(
            ctx.source_type, ctx.source_panel_id, ctx.target_panel_id
        )
        benign = list(BENIGN_EXPLANATIONS.get(ctx.source_type, []))
        questions = list(MANUAL_REVIEW_QUESTIONS.get(ctx.source_type, []))

    # Flip detection annotation
    if ctx.flip_detected:
        questions.append("检测到水平翻转复制 — 请核实是否为正常实验对称性或镜像操作。")
        summary += " [FLIP DETECTED]"

    # Language compliance
    all_text = [summary] + benign + questions
    for text in all_text:
        if check_language_compliance(text):
            result.verdict = GateVerdict.REJECT
            result.skip_reason = f"language compliance violation in: {text[:50]}"
            return result

    result.summary = summary
    result.benign_explanations = benign
    result.manual_review_questions = questions

    # Overlay path: only for medium+ findings
    if _risk_rank(result.risk_level) >= RISK_RANK["medium"]:
        result.overlay_path = ctx.overlay_path
    else:
        result.overlay_path = None

    return result


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

#: Ordered gate functions
GATE_PIPELINE: tuple[Callable, ...] = (
    modality_gate,
    artifact_quality_gate,
    local_evidence_gate,
    geometry_verification_gate,
    semantic_review_gate,
)


def run_gate_pipeline(
    ctx: GateContext,
    *,
    gates: tuple[Callable, ...] = GATE_PIPELINE,
) -> GateResult:
    """Execute the 5-gate pipeline on a single finding candidate."""
    result = GateResult()

    for i, gate in enumerate(gates):
        if i == 0:
            result = gate(ctx)
        else:
            result = gate(ctx, result)

        # Early exit on terminal verdicts
        if result.verdict in (
            GateVerdict.SKIP,
            GateVerdict.REJECT,
            GateVerdict.DEMOTE,
        ):
            break

    return result


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


def build_gate_context_from_relationship(
    rel: dict,
    panel_map: dict[str, dict],
    high_score_threshold: float,
    corroboration_index: dict[str, set[str]] | None = None,
) -> GateContext:
    """Build GateContext from a relationship dict."""
    src = str(rel.get("source_panel_id", ""))
    tgt = str(rel.get("target_panel_id", ""))
    source_type = str(rel.get("source_type", ""))
    raw_score = float(rel.get("score", 0.0))
    norm_score = max(0.0, min(1.0, raw_score))

    src_panel = _resolve_panel(src, panel_map)
    tgt_panel = _resolve_panel(tgt, panel_map)
    panel_type = _dominant_modality(src, tgt, panel_map)

    # Corroboration at this scope
    scope = _scope_key(rel)
    corr_families = (
        corroboration_index.get(scope, set()) if corroboration_index else set()
    )

    return GateContext(
        source_panel_id=src,
        target_panel_id=tgt,
        source_type=source_type,
        raw_score=raw_score,
        normalized_score=norm_score,
        source_panel=src_panel,
        target_panel=tgt_panel,
        panel_type=panel_type,
        overlay_path=rel.get("overlay_path"),
        flip_detected=bool(rel.get("flip_detected", False)),
        match_method=str(rel.get("match_method", "")),
        inlier_count=int(rel.get("inlier_count", 0) or 0),
        relationship_id=str(rel.get("relationship_id", "")),
        high_score_threshold=high_score_threshold,
        corroboration_families=frozenset(corr_families),
    )


def build_gate_context_from_trufor(
    fre: dict,
    panel_map: dict[str, dict],
    high_score_threshold: float = 0.5,
    corroboration_index: dict[str, set[str]] | None = None,
) -> GateContext:
    """Build GateContext from a TruFor forged_region_evidence dict."""
    figure_id = str(fre.get("figure_id", ""))
    integrity_score = float(fre.get("integrity_score", 0) or 0)
    norm_score = max(0.0, min(1.0, integrity_score))

    # Collect panel types for this figure
    figure_panel_types: set[str] = set()
    for _pid, _pdata in panel_map.items():
        if not isinstance(_pdata, dict):
            continue
        if str(_pdata.get("parent_figure_id", "")) == figure_id:
            pt = _pdata.get("panel_type")
            if pt:
                figure_panel_types.add(str(pt))

    panel_type = next(iter(figure_panel_types)) if figure_panel_types else None

    scope = f"fig:{figure_id}"
    corr_families = (
        corroboration_index.get(scope, set()) if corroboration_index else set()
    )

    return GateContext(
        source_panel_id="",
        target_panel_id="",
        source_type="forged_region_suspicious",
        raw_score=integrity_score,
        normalized_score=norm_score,
        panel_type=panel_type,
        figure_id=figure_id,
        integrity_score=integrity_score,
        confidence_map_path=fre.get("confidence_map_path"),
        forged_region_evidence_id=str(fre.get("forged_region_evidence_id", "")),
        high_score_threshold=high_score_threshold,
        corroboration_families=frozenset(corr_families),
    )


# ---------------------------------------------------------------------------
# Result → Finding conversion
# ---------------------------------------------------------------------------


def gate_result_to_finding(
    ctx: GateContext, result: GateResult, counter: int
) -> dict[str, Any]:
    """Convert a PASS GateResult into the standard finding dict format."""
    return {
        "finding_id": f"VF-{counter:04d}",
        "category": ctx.source_type,
        "risk_level": result.risk_level,
        "summary": result.summary,
        "source_panel_id": ctx.source_panel_id,
        "target_panel_id": ctx.target_panel_id,
        "relationship_id": ctx.relationship_id,
        "score": result.displayed_score,
        "benign_explanations": result.benign_explanations,
        "manual_review_questions": result.manual_review_questions,
        "overlay_path": result.overlay_path,
        "metadata": {
            "match_method": ctx.match_method,
            "inlier_count": ctx.inlier_count,
            "flip_detected": ctx.flip_detected,
            "raw_score": ctx.raw_score,
            "normalized_score": ctx.normalized_score,
            "displayed_score": result.displayed_score,
            "confidence_adjustment": ("; ".join(result.confidence_adjustments) or None),
            "panel_type": ctx.panel_type,
            "source_parent_figure_id": _parent_figure_id(
                ctx.source_panel, ctx.source_panel_id
            ),
            "target_parent_figure_id": _parent_figure_id(
                ctx.target_panel, ctx.target_panel_id
            ),
        },
    }
