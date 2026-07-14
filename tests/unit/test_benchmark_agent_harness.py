"""Unit tests for engine.benchmark.agent_harness (B1 bare-agent harness).

The LLM is mocked at its boundary (AgentFn). Three stubs exercise the harness end-to-end and,
via metrics, show B1's failure surface: a perfect oracle (F1 1, FAR 0), an always-flag agent
(recall 1 but FAR 1 — Failure Mode 3), and a malformed agent (all abstain).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.benchmark.agent_harness import (
    VerifierSignal,
    aggregate_signals,
    apply_far_control,
    build_prompt,
    decision_to_prediction,
    parse_decision,
    run_artifact_gear,
    run_bare_agent,
    run_constrained_agent,
    run_dual_layer_gear,
    run_graph_agent,
    run_provenance_gear,
    run_risk_controlled_agent,
    run_tool_augmented_agent,
)
from engine.benchmark.decision import Decision
from engine.benchmark.metrics import claim_prf, coverage_abstention, main_table_row
from engine.benchmark.schema import (
    LABEL_CLEAN,
    LABEL_DIRTY,
    LEVEL_RELATION,
    BenchmarkCase,
    ClaimInstance,
    Evidence,
    load_annotations,
)

CASE_JSON = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "veritasbench_cases" / "example_case.json"


def _case():
    return load_annotations(CASE_JSON, split="real-test")


def _oracle_agent(case):
    """A perfect agent: returns each claim's GT verdict + GT evidence_span (keyed by claim text)."""
    by_text = {(c.claim_text or c.description): c for c in case.claims}

    def fn(prompt: str) -> dict:
        for text, claim in by_text.items():
            if text and text in prompt:
                verdict = claim.verdict or ("inconsistent" if claim.label == "dirty" else "consistent")
                return {"verdict": verdict, "evidence_span": claim.evidence_span, "confidence": 0.9}
        return {}

    return fn


def test_oracle_agent_scores_perfectly():
    case = _case()
    preds = run_bare_agent(case, _oracle_agent(case))
    row = main_table_row(preds)
    assert row["claim_f1"] == 1.0
    assert row["claim_recall"] == 1.0
    assert row["far"] == 0.0
    assert row["evidence_precision"] == 1.0  # cited GT edges -> grounded
    assert row["coverage"] == 1.0


def test_always_flag_agent_exposes_false_accusation():
    # flags every claim -> catches both dirty ones (recall 1) but also the clean one (FAR 1).
    case = _case()
    preds = run_bare_agent(case, lambda p: {"verdict": "inconsistent", "evidence_span": "L1:a->b", "confidence": 0.5})
    row = main_table_row(preds)
    assert row["claim_recall"] == 1.0
    assert row["far"] == 1.0                      # Failure Mode 3: uncontrolled false accusation
    assert row["evidence_precision"] == 0.0       # wrong locus -> not grounded
    assert row["claim_precision"] < 1.0


def test_malformed_agent_abstains():
    case = _case()
    preds = run_bare_agent(case, lambda p: {})    # empty reply -> insufficient
    row = main_table_row(preds)
    assert row["coverage"] == 0.0
    assert row["abstention"] == 1.0
    assert all(p.abstained for p in preds)


def test_parse_decision_is_defensive():
    assert parse_decision(None).verdict == "insufficient"
    assert parse_decision({"verdict": "nonsense"}).verdict == "insufficient"
    d = parse_decision({"verdict": "INCONSISTENT", "confidence": 5, "evidence_span": "L1:a->b"})
    assert d.verdict == "inconsistent"            # normalised
    assert d.confidence == 1.0                    # clamped
    assert d.evidence_span == "L1:a->b"


def test_render_content_reaches_the_prompt():
    case = _case()
    seen = []

    def flag_if_sentinel(prompt: str) -> dict:
        seen.append(prompt)
        return {"verdict": "inconsistent", "evidence_span": "L1:a->b"} if "SENTINEL_DATA" in prompt else {}

    preds = run_bare_agent(case, flag_if_sentinel, render=lambda claim, case: "SENTINEL_DATA r1: 1, 1")
    assert all(p.predicted_flag for p in preds)   # the rendered content reached every prompt
    assert "SENTINEL_DATA" in seen[0]


def test_prompt_does_not_leak_ground_truth():
    case = _case()
    c1 = case.claims[0]  # dirty, has a GT evidence_span
    prompt = build_prompt(c1, case)
    assert c1.claim_text in prompt
    assert "table1.json" in prompt                 # artifact inventory is shown
    assert c1.evidence_span not in prompt          # but the GT edge is NOT given away
    assert c1.label not in prompt                  # nor the GT label


def test_evidence_correct_only_on_grounded_dirty_flag():
    case = _case()
    dirty = case.claims[0]
    # flag with the correct GT span -> evidence_correct True
    from engine.benchmark.agent_harness import AuditDecision
    good = decision_to_prediction(dirty, AuditDecision("inconsistent", dirty.evidence_span, 0.8))
    assert good.predicted_flag and good.evidence_correct
    # flag with a wrong span -> not grounded
    bad = decision_to_prediction(dirty, AuditDecision("inconsistent", "L1:zzz->qqq", 0.8))
    assert bad.predicted_flag and not bad.evidence_correct


# --- B2 constrained agent: ungrounded flags are refused ------------------------------------

def test_b2_downgrades_ungrounded_flags_vs_b1():
    case = _case()
    # a hallucinator that flags everything but never grounds (no evidence_span)
    hallucinate = lambda p: {"verdict": "inconsistent", "confidence": 0.5}  # noqa: E731
    b1 = main_table_row(run_bare_agent(case, hallucinate))
    b2 = main_table_row(run_constrained_agent(case, hallucinate))
    assert b1["far"] == 1.0            # B1 accepts every ungrounded accusation
    assert b2["far"] == 0.0            # B2 refuses them (no well-formed span)
    assert b2["far"] < b1["far"]


def test_b2_keeps_grounded_flags():
    case = _case()
    b2 = main_table_row(run_constrained_agent(case, _oracle_agent(case)))
    assert b2["claim_f1"] == 1.0       # well-grounded oracle survives the B2 constraint
    assert b2["evidence_precision"] == 1.0


# --- B3 typed verifiers carry grounding even with a useless agent --------------------------

def _perfect_verifier(case):
    """A stub typed verifier: in-scope for all claims, fires on dirty ones with the GT span."""
    gt = {c.claim_id: c for c in case.claims}

    def v(claim, _case):
        c = gt[claim.claim_id]
        return VerifierSignal(claim.relation, fired=(c.label == "dirty"), evidence_span=c.evidence_span, confidence=0.95)

    return v


def test_b3_verifiers_ground_even_with_useless_agent():
    case = _case()
    useless = lambda p: {"verdict": "insufficient"}  # noqa: E731 — agent contributes nothing
    row = main_table_row(run_tool_augmented_agent(case, useless, [_perfect_verifier(case)]))
    assert row["claim_f1"] == 1.0
    assert row["claim_recall"] == 1.0
    assert row["far"] == 0.0
    assert row["evidence_precision"] == 1.0   # grounded by the deterministic verifier


def test_b3_falls_back_to_agent_when_no_verifier_in_scope():
    case = _case()
    out_of_scope = lambda claim, case: None  # noqa: E731 — no tool covers anything
    row = main_table_row(run_tool_augmented_agent(case, _oracle_agent(case), [out_of_scope]))
    assert row["claim_f1"] == 1.0             # falls back to the (here perfect) bare agent


# --- B4 evidence-graph aggregation: independence corroborates, convergence de-duplicates ----

def test_aggregate_independent_signals_corroborate():
    # two signals on DISTINCT loci -> noisy-OR boosts confidence above either alone
    s1 = VerifierSignal("L1", fired=True, evidence_span="L1:a->t1", confidence=0.6)
    s2 = VerifierSignal("L1", fired=True, evidence_span="L1:b->t2", confidence=0.6)
    agg = aggregate_signals([s1, s2])
    assert agg.verdict == "inconsistent"
    assert agg.confidence == pytest.approx(1 - 0.4 * 0.4)   # 0.84 > 0.6


def test_aggregate_convergent_signals_do_not_double_count():
    # two signals on the SAME target -> same mismatch -> not double-counted
    s1 = VerifierSignal("L1", fired=True, evidence_span="L1:a->t1", confidence=0.6)
    s3 = VerifierSignal("L1", fired=True, evidence_span="L1:c->t1", confidence=0.6)
    agg = aggregate_signals([s1, s3])
    assert agg.confidence == pytest.approx(0.6)             # collapsed, no boost


def test_aggregate_none_when_no_verifier_in_scope():
    assert aggregate_signals([None, None]) is None


def test_b4_grounds_like_b3_with_a_covering_verifier():
    case = _case()
    useless = lambda p: {"verdict": "insufficient"}  # noqa: E731
    row = main_table_row(run_graph_agent(case, useless, [_perfect_verifier(case)]))
    assert row["claim_f1"] == 1.0 and row["far"] == 0.0 and row["evidence_precision"] == 1.0


# --- B5 FAR-constrained selective decision: borderline flags are abstained -----------------

# --- B1-B5 gears (dual-layer design): the layers are complementary (RQ3) ------------------

def _dl_claim(cid, label, span):
    return ClaimInstance(claim_id=cid, claim_type="report.x", level="L3", label=label,
                         relation=LEVEL_RELATION["L3"],
                         evidence=Evidence(evidence_type="source_data", target=cid), evidence_span=span)


def _dual_layer_case():
    # one ARTIFACT-layer fabrication, one PROVENANCE-layer fabrication, plus a clean control
    return BenchmarkCase("dl", "real-test", "dl", (
        _dl_claim("art::1", LABEL_DIRTY, "L3:d->art"),
        _dl_claim("prov::1", LABEL_DIRTY, "L3:t->prov"),
        _dl_claim("clean::1", LABEL_CLEAN, "L3:x->clean"),
    ))


def _layer_verifier(tag):
    """Stub verifier that fires only on its layer's dirty claim (keyed by claim_id tag)."""
    def v(claim, _case):
        fires = tag in claim.claim_id and claim.label == LABEL_DIRTY
        return VerifierSignal(claim.relation, fired=fires, evidence_span=claim.evidence_span, confidence=0.9)
    return v


def test_dual_layer_gears_are_complementary():
    case = _dual_layer_case()
    useless = lambda p: {"verdict": "insufficient"}  # noqa: E731
    artifact = [_layer_verifier("art")]        # B3 tools: node integrity
    provenance = [_layer_verifier("prov")]     # B4 tools: edge consistency

    b3 = claim_prf(run_artifact_gear(case, useless, artifact))
    b4 = claim_prf(run_provenance_gear(case, useless, provenance))
    b5 = claim_prf(run_dual_layer_gear(case, useless, artifact, provenance))

    assert b3["tp"] == 1 and b3["fn"] == 1     # B3 catches the artifact fraud, misses the provenance one
    assert b4["tp"] == 1 and b4["fn"] == 1     # B4 catches the provenance fraud, misses the artifact one
    assert b5["tp"] == 2 and b5["fn"] == 0     # B5 dual-layer catches BOTH (complementary coverage)
    assert b3["fp"] == b4["fp"] == b5["fp"] == 0   # none flag the clean control


def test_apply_far_control_is_cross_cutting():
    # FAR control applies to ANY gear's predictions; a high threshold abstains borderline flags.
    case = _dual_layer_case()
    useless = lambda p: {"verdict": "insufficient"}  # noqa: E731
    preds = run_artifact_gear(case, useless, [_layer_verifier("art")])
    controlled = apply_far_control(preds, Decision(flag_threshold=0.95, abstain_threshold=0.5, alpha=0.05))
    # the artifact flag scored 0.9 -> below 0.95 flag threshold, in the abstain band
    assert any(p.abstained for p in controlled)


def test_b5_abstains_borderline_and_flags_strong():
    case = _case()
    useless = lambda p: {"verdict": "insufficient"}  # noqa: E731

    def weak_verifier(case):
        gt = {c.claim_id: c for c in case.claims}

        def v(claim, _case):
            c = gt[claim.claim_id]
            # dirty claims get only a BORDERLINE 0.5 signal; clean stay clean
            return VerifierSignal(claim.relation, fired=(c.label == "dirty"),
                                  evidence_span=c.evidence_span, confidence=0.5)
        return v

    # a decision that only flags >=0.8 and abstains the [0.4,0.8) band
    decision = Decision(flag_threshold=0.8, abstain_threshold=0.4, alpha=0.05)
    preds = run_risk_controlled_agent(case, useless, [weak_verifier(case)], decision)
    cov = coverage_abstention(preds)
    # the two dirty claims score 0.5 -> abstained (borderline), not flagged
    assert cov["abstention"] > 0.0
    assert not any(p.predicted_flag and p.gt_label == "dirty" for p in preds)

    # a strong decision threshold below the score -> the same claims now flag
    strong = Decision(flag_threshold=0.4, abstain_threshold=0.4, alpha=0.05)
    preds2 = run_risk_controlled_agent(case, useless, [weak_verifier(case)], strong)
    assert any(p.predicted_flag and p.gt_label == "dirty" for p in preds2)
