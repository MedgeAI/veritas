"""Closed-loop eval adapter for rep_ (reproduction / honest-FP) cases — ORACLE-CONDITIONED, L1.

Extends the eval loop from ncb_ duplication cases to the reproduction family. A rep_ L1 claim is a
natural-language assertion (claim_atom) about two COMPUTED values (source/target obs = code_output
metrics); the agent must judge consistent / inconsistent / insufficient without seeing the gold.

Contrast with the duplication adapter (veritasbench_eval_adapter):
  * the two values are computed metrics (verified reproducible by the recompute verifier), not raw
    cells; the claim asserts a relationship (highest / within-CI / gap / mediator-adjusted), not
    "independent measurements".
  * ★ node vs edge: the recompute B3 verifier confirms the cited values are REPRODUCIBLE (node
    integrity) but CANNOT tell a correct pipeline from a naive one that also reproduces its own
    (wrong-methodology) output — that edge judgment is the agent/context tier's job. So on the
    naive-side FP-traps, recompute stays quiet (clean FAR, but blind to methodology) — the reported
    verifier_conflict, not a bug.

Gold verdict / discrepancy / is_clean are carried for SCORING ONLY, never rendered. The claim_atom
IS the oracle-safe candidate (it states what the paper asserts, not whether it holds); a leak guard
still asserts no verdict word leaks.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.benchmark.recompute_verifier import recompute_verify
from engine.benchmark.schema import (
    LEVEL_RELATION,
    SOURCE_HUMAN,
    BenchmarkCase,
    ClaimInstance,
    Evidence,
    label_from_verdict,
)

AXIS_REP = "reproduction"


def _obs_val(observations: dict, ref: str):
    o = observations.get(ref)
    return (o.get("value") if o else None)


# Neutral claim_text overrides. Two authored claim_atoms carry failure-mode vocabulary that would
# leak the audit task into the agent prompt: methclock says "...or fabricated; reproduces cleanly"
# (a hint word + a verdict-leaning editorial), actmeta says "duplicate <study> removed" (a legit
# meta-analysis cleaning step, but the token trips the guard). We override ONLY the agent-facing
# claim_text here — gold verdict / discrepancy_type / obs values are untouched, so scoring is
# unaffected — instead of editing the data window's case.json. Both rewrites are verified
# hint-word-free by scripts.run_veritasbench_eval._leak_scan (hard gate 1). Director-approved.
_NEUTRAL_CLAIM_TEXT = {
    "rep_methclock_claim_002": (
        "A naive match of the clock's bare cg IDs directly against the EPICv2-suffixed matrix index "
        "yields 0 overlapping probes and a constant prediction (Pearson r=0.00). After stripping the "
        "EPICv2 probe-ID suffixes (cgXXXX vs cgXXXX_TC21/_BC11, replicate probes per CpG) to reconcile "
        "the IDs, the clock's predictions correlate with the reference at Pearson r~0.96."
    ),
    "rep_actmeta_claim_002": (
        "After correcting the three data-extraction errors identified in the re-extraction and "
        "re-running Zhao et al.'s analytic workflow (re-extracted effect sizes, the repeated Ren "
        "Zhihong 2012 entry removed, outlier Zemestani 2020 excluded; 9 studies), the corrected "
        "pooled effect (g = -0.61) is smaller in magnitude than the Figure-4 reproduction (g = -1.05)."
    ),
}


def _rep_claim(row: dict, *, case_id: str, idx: int, observations: dict) -> ClaimInstance | None:
    src_ref, tgt_ref = row.get("source_artifact", ""), row.get("target_artifact", "")
    if src_ref not in observations or tgt_ref not in observations:
        return None  # claim references an obs we don't have -> drop (fail loud at load)
    verdict = row.get("verdict")
    verdict = str(verdict) if verdict else None
    src_key, tgt_key = src_ref.split("#")[-1], tgt_ref.split("#")[-1]
    claim_id = str(row.get("claim_id") or f"{case_id}::c{idx:03d}")
    return ClaimInstance(
        claim_id=claim_id,
        claim_type="reproduction.claim_support",
        level="L1",
        label=label_from_verdict(verdict, is_clean=bool(row.get("is_clean_claim", False))),
        relation=LEVEL_RELATION["L1"],
        # the paper's assertion is the oracle-safe candidate (states the claim, not the answer);
        # a neutral override strips any leaked failure-mode vocabulary (see _NEUTRAL_CLAIM_TEXT)
        claim_text=_NEUTRAL_CLAIM_TEXT.get(claim_id, str(row.get("claim_atom", ""))),
        evidence=Evidence(evidence_type="code_output", target=tgt_key),
        verdict=verdict,                                     # SCORING ONLY
        evidence_span=f"L1:{src_key}->{tgt_key}",
        discrepancy_type=str(row["discrepancy_type"]) if row.get("discrepancy_type") else None,
        source=SOURCE_HUMAN,
        metadata={"axis": AXIS_REP, "src_key": src_key, "tgt_key": tgt_key,
                  "src_val": _obs_val(observations, src_ref), "tgt_val": _obs_val(observations, tgt_ref),
                  "src_obs": observations[src_ref], "tgt_obs": observations[tgt_ref]},
    )


def load_rep_case(case_dir: str | Path, *, split: str = "real-test") -> tuple[BenchmarkCase, dict]:
    """Load one rep_ case.json into an L1-only, oracle-conditioned BenchmarkCase (+ load report)."""
    case_dir = Path(case_dir)
    doc = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    observations = doc.get("observations") or {}
    cid = str(doc.get("case_id") or case_dir.name)

    claims, l1 = [], 0
    for i, row in enumerate(doc.get("claims", []) or []):
        if str(row.get("relation_type") or row.get("level")) != "L1":
            continue
        l1 += 1
        c = _rep_claim(row, case_id=cid, idx=i, observations=observations)
        if c is not None:
            claims.append(c)

    case = BenchmarkCase(
        case_id=cid, split=split, base_paper_id=str(doc.get("paper_title") or cid),
        claims=tuple(claims), artifacts={"data": str(case_dir), "observations": observations},
        title=doc.get("paper_title"),
    )
    return case, {"total_l1": l1, "loaded": len(claims), "dropped": l1 - len(claims)}


def rep_renderer():
    """Neutral oracle renderer: the two computed values the claim references, no leading hints."""

    def render(claim: ClaimInstance, _case: BenchmarkCase) -> str:
        md = claim.metadata or {}
        return (f"The claim references two computed values from the analysis output:\n"
                f"  A ({md.get('src_key')}) = {md.get('src_val')}\n"
                f"  B ({md.get('tgt_key')}) = {md.get('tgt_val')}")

    return render


def rep_recompute_verifier():
    """B3 for rep_: recompute the cited values; fire (inconsistent) iff a value does NOT reproduce.

    This is a NODE-integrity check — it catches a fabricated/non-reproducible value, but a naive
    pipeline whose (wrong-methodology) output reproduces its own code stays unflagged. That blind
    spot to the edge/methodology is the reported node-vs-edge gap."""
    from engine.benchmark.agent_harness import VerifierSignal

    def verify(claim: ClaimInstance, case: BenchmarkCase):
        md = claim.metadata or {}
        if md.get("axis") != AXIS_REP:
            return None
        case_dir = Path(case.artifacts["data"])
        obs_index = case.artifacts.get("observations", {})
        results = [recompute_verify(md["src_obs"], case_dir, obs_index),
                   recompute_verify(md["tgt_obs"], case_dir, obs_index)]
        fired = any(r.startswith("fail") for r in results)   # a cited value does not reproduce
        return VerifierSignal(relation="L1", fired=fired, evidence_span=claim.evidence_span, confidence=1.0)

    return verify
