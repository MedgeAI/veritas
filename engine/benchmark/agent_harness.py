"""B1 — bare-agent audit harness (the baseline that exposes the three failure modes).

Story arc v4: B1 = LLM + artifacts -> verdict, with NO structured protocol, NO typed verifiers,
NO evidence-graph aggregation, NO risk control. Running B1 on VeritasBench is what DISCOVERS the
three failure modes (grounding instability, cross-verifier conflict, uncontrolled false
accusation). B2–B5 later add one structural layer each; this module is the shared base.

The LLM is a pluggable BOUNDARY (`AgentFn = prompt -> raw dict`) so the harness is testable
mock-first (inject a deterministic stub) and backbone-agnostic (the "competitors" = the same B1
protocol with a Claude-Code / Codex / API backbone). The harness itself is pure: it builds a
per-claim prompt from artifacts (never the GT verdict), parses the agent's structured reply,
aligns it to ground truth, and emits engine.benchmark.metrics.ClaimPrediction records.

Per-claim task (the measurable unit): given a claim + the case artifacts, the agent must (a)
judge consistent / inconsistent / insufficient and (b) GROUND it with an evidence_span. Verdict
drives Claim-F1 / FAR; the evidence_span drives Evidence-Precision (grounding quality); an
`insufficient` verdict is a selective abstention.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from engine.benchmark.decision import Decision, apply_decision
from engine.benchmark.metrics import ClaimPrediction
from engine.benchmark.schema import (
    LABEL_DIRTY,
    VERDICT_CONSISTENT,
    VERDICT_INCONSISTENT,
    VERDICT_INSUFFICIENT,
    VERDICTS,
    BenchmarkCase,
    ClaimInstance,
    parse_evidence_span,
)

# The pluggable model boundary: a prompt in, a parsed structured reply out.
# A real backbone (Claude Code / Codex / API) wraps model-call + JSON-extraction behind this.
AgentFn = Callable[[str], dict[str, Any]]

# Per-claim artifact rendering: turns the claim's relevant artifacts into prompt text. The default
# renderer (render_artifacts) lists only the inventory; a content renderer (e.g. one that loads the
# relevant xlsx sheet) lets the agent actually inspect the data instead of only guessing.
ArtifactRenderer = Callable[["ClaimInstance", "BenchmarkCase"], str]

# What a bare agent is asked to emit per claim.
_RESPONSE_CONTRACT = (
    '{"verdict": "consistent|inconsistent|insufficient", '
    '"evidence_span": "{relation}:{source}->{target}", '
    '"confidence": <0.0-1.0>, "rationale": "<one sentence>"}'
)


@dataclass(frozen=True)
class AuditDecision:
    """One bare-agent decision on one claim (before GT alignment)."""

    verdict: str
    evidence_span: str | None = None
    confidence: float = 0.0
    rationale: str = ""


def render_artifacts(case: BenchmarkCase) -> str:
    """Bare-agent artifact context = just the artifact inventory (paths/names).

    B1 gets only what artifacts EXIST and must locate evidence itself — that is precisely what
    stresses grounding (Failure Mode 1). Richer rendering (loading xlsx/code contents) is a B3
    typed-verifier concern, deliberately absent here.
    """
    lines = []
    for kind, val in sorted(case.artifacts.items()):
        if isinstance(val, list):
            for v in val:
                lines.append(f"- {kind}: {v}")
        else:
            lines.append(f"- {kind}: {val}")
    return "\n".join(lines) if lines else "- (no artifacts listed)"


def build_prompt(claim: ClaimInstance, case: BenchmarkCase, *, artifacts_text: str | None = None) -> str:
    """Per-claim audit prompt. Uses the claim text + artifact inventory only — never the GT verdict."""
    text = claim.claim_text or claim.description or claim.claim_type
    artifacts = artifacts_text if artifacts_text is not None else render_artifacts(case)
    return (
        "You are auditing a scientific paper for claim-provenance consistency. Decide whether the "
        "CLAIM is supported by the ARTIFACTS, and cite where the supporting/contradicting evidence "
        "lives as an evidence_span. If you cannot ground it, answer 'insufficient'.\n\n"
        f"CLAIM ({claim.level}, relation {claim.relation}):\n  {text}\n\n"
        f"ARTIFACTS AVAILABLE:\n{artifacts}\n\n"
        f"Respond as JSON only:\n{_RESPONSE_CONTRACT}"
    )


def parse_decision(raw: dict[str, Any] | None) -> AuditDecision:
    """Defensively parse an agent reply. Malformed/empty -> an `insufficient` abstention at conf 0."""
    raw = raw or {}
    verdict = str(raw.get("verdict", VERDICT_INSUFFICIENT)).strip().lower()
    if verdict not in VERDICTS:
        verdict = VERDICT_INSUFFICIENT
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    span = raw.get("evidence_span")
    return AuditDecision(
        verdict=verdict,
        evidence_span=str(span) if span else None,
        confidence=confidence,
        rationale=str(raw.get("rationale", "")),
    )


def _evidence_matches(pred_span: str | None, gt_span: str | None) -> bool:
    """Grounding hit iff the agent's cited TARGET locus matches the GT edge's target (normalised)."""
    if not pred_span or not gt_span:
        return False
    _, _, pred_target = parse_evidence_span(pred_span)
    _, _, gt_target = parse_evidence_span(gt_span)
    gt_target = gt_target.strip().lower()
    return bool(gt_target) and pred_target.strip().lower() == gt_target


def _dirtiness(verdict: str, confidence: float) -> float:
    """A verdict + verdict-confidence -> a monotone dirtiness score P(dirty) in [0,1].

    This is the score threshold sweeps (recall_at_far, B5 decision) operate on: a confidently
    'consistent' claim must score LOW (not-dirty), a confidently 'inconsistent' one HIGH.
    """
    if verdict == VERDICT_INCONSISTENT:
        return confidence
    if verdict == VERDICT_CONSISTENT:
        return 1.0 - confidence
    return 0.5  # insufficient — maximally uncertain (and normally abstained anyway)


def decision_to_prediction(claim: ClaimInstance, decision: AuditDecision) -> ClaimPrediction:
    """Align one decision to GT -> a ClaimPrediction for engine.benchmark.metrics.

    predicted_flag = verdict is 'inconsistent'; abstained = verdict is 'insufficient';
    evidence_correct = a flag whose cited target matches the GT edge target (grounding);
    confidence = a dirtiness score (P dirty) so downstream threshold sweeps are monotone.
    """
    flagged = decision.verdict == VERDICT_INCONSISTENT
    abstained = decision.verdict == VERDICT_INSUFFICIENT
    evidence_correct = (
        flagged
        and claim.label == LABEL_DIRTY
        and _evidence_matches(decision.evidence_span, claim.evidence_span)
    )
    return ClaimPrediction(
        claim_id=claim.claim_id,
        gt_label=claim.label,
        predicted_flag=flagged,
        confidence=_dirtiness(decision.verdict, decision.confidence),
        abstained=abstained,
        evidence_correct=evidence_correct,
    )


def run_bare_agent(
    case: BenchmarkCase, agent_fn: AgentFn, *, render: ArtifactRenderer | None = None
) -> list[ClaimPrediction]:
    """Run B1 over every claim in a case -> ClaimPredictions (feed to metrics.main_table_row).

    The agent sees each claim + its artifacts (inventory by default, or real content via `render`),
    never the GT label/verdict.
    """
    preds: list[ClaimPrediction] = []
    inventory = render_artifacts(case)
    for claim in case.claims:
        artifacts_text = render(claim, case) if render else inventory
        raw = agent_fn(build_prompt(claim, case, artifacts_text=artifacts_text))
        preds.append(decision_to_prediction(claim, parse_decision(raw)))
    return preds


# ============================================================================================
# B2 — Constrained Agent: + structured protocol (claim normalization + FORCED evidence span).
# Responds to Failure Mode 1 (unstable grounding): a flag must be GROUNDED by a well-formed
# evidence_span, or it is not trusted. This trades some recall for far fewer hallucinated
# false accusations — the grounding discipline B1 lacks.
# ============================================================================================

def _well_formed_span(span: str | None) -> bool:
    """A usable grounding: parses as '{relation}:{source}->{target}' with a non-empty target."""
    if not span:
        return False
    relation, _source, target = parse_evidence_span(span)
    return bool(relation) and bool(target)


def build_constrained_prompt(claim: ClaimInstance, case: BenchmarkCase, *, artifacts_text: str | None = None) -> str:
    base = build_prompt(claim, case, artifacts_text=artifacts_text)
    return (
        base
        + "\n\nPROTOCOL: first NORMALIZE the claim (what quantity, expected source artifact, "
        "expected target locus), then locate the evidence. You may ONLY answer 'inconsistent' if "
        "you can cite a concrete, well-formed evidence_span '{relation}:{source}->{target}' with a "
        "specific target locus. If you cannot ground it there, answer 'insufficient'."
    )


def run_constrained_agent(
    case: BenchmarkCase, agent_fn: AgentFn, *, render: ArtifactRenderer | None = None
) -> list[ClaimPrediction]:
    """B2: like B1 but an ungrounded flag (no well-formed span) is downgraded to a non-flag pass."""
    preds: list[ClaimPrediction] = []
    inventory = render_artifacts(case)
    for claim in case.claims:
        artifacts_text = render(claim, case) if render else inventory
        raw = agent_fn(build_constrained_prompt(claim, case, artifacts_text=artifacts_text))
        d = parse_decision(raw)
        if d.verdict == VERDICT_INCONSISTENT and not _well_formed_span(d.evidence_span):
            # cannot ground the accusation -> refuse to flag (kills FM1-driven false accusations)
            d = AuditDecision(VERDICT_CONSISTENT, None, d.confidence, d.rationale)
        preds.append(decision_to_prediction(claim, d))
    return preds


# ============================================================================================
# B3 — Tool-Augmented Agent: + typed verifiers (deterministic tools per relation).
# Responds to Failure Mode 1+2: a verifier that fires GROUNDS the flag deterministically (correct
# span); if in-scope verifiers ran and none fired, the locus is clean and a bare-agent flag is
# suppressed; only when NO verifier covers the relation does it fall back to the bare agent.
# The existing source-data / statcheck / GRIM detectors wrap into TypedVerifier adapters.
# ============================================================================================

@dataclass(frozen=True)
class VerifierSignal:
    """One typed verifier's structured result on one claim."""

    relation: str
    fired: bool                       # did the verifier find an inconsistency at this locus
    evidence_span: str | None = None  # where (grounded, deterministic)
    confidence: float = 1.0


# A typed verifier: returns a signal when it is IN SCOPE for the claim, else None (not applicable).
TypedVerifier = Callable[[ClaimInstance, BenchmarkCase], "VerifierSignal | None"]


def run_tool_augmented_agent(
    case: BenchmarkCase, agent_fn: AgentFn, verifiers: list[TypedVerifier]
) -> list[ClaimPrediction]:
    """B3: verifiers decide where they apply; the bare agent only fills relations no tool covers."""
    preds: list[ClaimPrediction] = []
    artifacts_text = render_artifacts(case)
    for claim in case.claims:
        signals = [s for s in (v(claim, case) for v in verifiers) if s is not None]
        fired = [s for s in signals if s.fired]
        if fired:
            best = max(fired, key=lambda s: s.confidence)
            d = AuditDecision(VERDICT_INCONSISTENT, best.evidence_span, best.confidence)
        elif signals:
            # in-scope verifiers ran and all say clean -> trust them over a bare LLM hunch
            d = AuditDecision(VERDICT_CONSISTENT, None, max(s.confidence for s in signals))
        else:
            # no typed verifier covers this relation -> fall back to the bare agent
            d = parse_decision(agent_fn(build_prompt(claim, case, artifacts_text=artifacts_text)))
        preds.append(decision_to_prediction(claim, d))
    return preds


# ============================================================================================
# B4 — Graph-Augmented Agent: + evidence-graph aggregation over MULTIPLE verifier signals.
# Responds to Failure Mode 2 (cross-verifier conflict). Where B3 trusts the single strongest
# fired verifier, B4's aggregation function A weighs all signals on a claim:
#   * convergence — signals citing the SAME target are the same semantic mismatch, so they are
#     de-duplicated (not double-counted);
#   * independence — signals on DISTINCT loci are independent corroboration, combined by noisy-OR
#     so genuine multi-source support raises confidence (and isolated single signals do not).
# ============================================================================================

def aggregate_signals(signals: list["VerifierSignal | None"]) -> AuditDecision | None:
    """Fuse verifier signals for one claim. Returns None iff no verifier is in scope (-> agent)."""
    in_scope = [s for s in signals if s is not None]
    if not in_scope:
        return None
    fired = [s for s in in_scope if s.fired]
    if not fired:
        # every in-scope verifier says clean -> confident consistent (certainty = strongest clean)
        return AuditDecision(VERDICT_CONSISTENT, None, max(s.confidence for s in in_scope))
    # convergence: collapse signals on the same target locus, keeping the strongest per target.
    by_locus: dict[str, float] = {}
    for s in fired:
        relation, source, target = parse_evidence_span(s.evidence_span or "")
        locus = target or source or relation or s.relation
        by_locus[locus] = max(by_locus.get(locus, 0.0), s.confidence)
    # independence: noisy-OR across distinct loci -> corroboration boosts fused confidence.
    complement = 1.0
    for conf in by_locus.values():
        complement *= 1.0 - conf
    fused = 1.0 - complement
    best = max(fired, key=lambda s: s.confidence)
    return AuditDecision(VERDICT_INCONSISTENT, best.evidence_span, fused)


def run_graph_agent(
    case: BenchmarkCase, agent_fn: AgentFn, verifiers: list[TypedVerifier],
    *, render: "ArtifactRenderer | None" = None,
) -> list[ClaimPrediction]:
    """B4: aggregate all verifier signals per claim (independence + convergence); agent fills gaps.

    `render` (optional) is used ONLY for the agent fallback on claims no verifier covers, so a geared
    run over a mixed corpus still shows the agent the neutral per-claim evidence there."""
    preds: list[ClaimPrediction] = []
    inventory = render_artifacts(case)
    for claim in case.claims:
        agg = aggregate_signals([v(claim, case) for v in verifiers])
        if agg is None:
            artifacts_text = render(claim, case) if render else inventory
            agg = parse_decision(agent_fn(build_prompt(claim, case, artifacts_text=artifacts_text)))
        preds.append(decision_to_prediction(claim, agg))
    return preds


# ============================================================================================
# B5 — Risk-Controlled Agent: + FAR-constrained selective decision (the method's decision layer).
# Responds to Failure Mode 3. B4 gives a calibrated dirtiness score per claim; B5 re-decides
# flag / abstain / pass under a hard FAR<=alpha ceiling calibrated on a dev split. This is a thin
# wrapper over engine.benchmark.decision — build the Decision with fit_decision(dev, alpha).
# ============================================================================================

def run_risk_controlled_agent(
    case: BenchmarkCase, agent_fn: AgentFn, verifiers: list[TypedVerifier], decision: Decision
) -> list[ClaimPrediction]:
    """[building block] verifier run + FAR-calibrated decision. See apply_far_control (cross-cutting)."""
    return apply_decision(run_graph_agent(case, agent_fn, verifiers), decision)


# ============================================================================================
# B1–B5 GEARS (dual-layer design, 2026-07-13). The ablation is WHICH TOOL LAYER the agent gets,
# not which method-component. Every geared run reuses run_graph_agent (evidence aggregation over
# the given verifiers — product-level fusion); a gear just chooses the verifier set. The functions
# above (run_tool_augmented_agent / run_graph_agent / aggregate_signals / run_risk_controlled_agent)
# are the shared ENGINE. FAR-constrained selective decision is CROSS-CUTTING (apply_far_control),
# layered on top of ANY gear — RQ4, not a gear.
#
#   B1 bare        run_bare_agent                         no tools, PDF/claim text only
#   B2 structured  run_constrained_agent                  + protocol (claim norm + forced grounding)
#   B3 artifact    run_artifact_gear(artifact_verifiers)  + Artifact Integrity (node): data/image/numeric forensics
#   B4 provenance  run_provenance_gear(prov_verifiers)    + Provenance Consistency (edge): L1-L4 code↔table↔figure↔text
#   B5 dual-layer  run_dual_layer_gear(art, prov)         + BOTH; aggregation fuses node+edge signals
# ============================================================================================

def run_artifact_gear(
    case: BenchmarkCase, agent_fn: AgentFn, artifact_verifiers: list[TypedVerifier],
    *, render: "ArtifactRenderer | None" = None,
) -> list[ClaimPrediction]:
    """B3 — agent + Artifact-Integrity verifiers (source-data / image / numeric forensics)."""
    return run_graph_agent(case, agent_fn, artifact_verifiers, render=render)


def run_provenance_gear(
    case: BenchmarkCase, agent_fn: AgentFn, provenance_verifiers: list[TypedVerifier],
    *, render: "ArtifactRenderer | None" = None,
) -> list[ClaimPrediction]:
    """B4 — agent + Provenance-Consistency verifiers (L1-L4 edges: code↔table, table↔figure, →text)."""
    return run_graph_agent(case, agent_fn, provenance_verifiers, render=render)


def run_dual_layer_gear(
    case: BenchmarkCase,
    agent_fn: AgentFn,
    artifact_verifiers: list[TypedVerifier],
    provenance_verifiers: list[TypedVerifier],
    *, render: "ArtifactRenderer | None" = None,
) -> list[ClaimPrediction]:
    """B5 — agent + BOTH layers; evidence aggregation fuses node + edge signals (product-level)."""
    return run_graph_agent(case, agent_fn, [*artifact_verifiers, *provenance_verifiers], render=render)


def apply_far_control(preds: list[ClaimPrediction], decision: Decision) -> list[ClaimPrediction]:
    """Cross-cutting (RQ4): re-decide ANY gear's predictions as flag/abstain/pass under FAR<=alpha."""
    return apply_decision(preds, decision)
