"""Wire the L1 provenance verifier on the real PBC case (case #1, CODECHECK-verified).

Proves the L1 plumbing end-to-end on real data: the code-output side is READ from the team's
pre-run `code/results/summary_metrics.csv` (no sandbox needed yet); the paper-reported side comes
from the annotation. Where the reported value is still pending (paywalled PDF), the verifier
correctly ABSTAINS — and this script prints the code-output value it read, so filling in the
reported number later completes the comparison.

Run:  VERITAS_REAL_PAPERS_ROOT=<root> PYTHONPATH=. python3 scripts/run_l1_pbc.py
"""

from __future__ import annotations

import sys

from engine.benchmark.provenance import l1_computation_verifier, results_replay, values_consistent
from engine.benchmark.schema import load_annotations, parse_evidence_span
from engine.env import real_papers_root

CASE_DIR = real_papers_root() / "10.71240_lcyc.66O7260"


def main() -> int:
    case_json = CASE_DIR / "example_case.json"
    if not case_json.exists():
        print(f"missing {case_json}; set VERITAS_REAL_PAPERS_ROOT to a local copy", file=sys.stderr)
        return 1

    case = load_annotations(case_json, split="real-test")
    replay = results_replay(CASE_DIR)
    verify = l1_computation_verifier(replay)

    print(f"case={case.case_id}  ({case.doi})\n")
    for claim in case.claims:
        if claim.level != "L1":
            print(f"  [{claim.level}] {claim.claim_id}: GT={claim.verdict} (not an L1 claim, skipped by L1 verifier)")
            continue
        _r, source, target = parse_evidence_span(claim.evidence_span or "")
        computed = replay(source, target, case)
        reported = (claim.metadata or {}).get("reported_value")
        sig = verify(claim, case)
        code_out = f"{computed.value}" if computed.ok else f"(unreadable: {computed.detail})"
        print(f"  [L1] {claim.claim_id}: GT={claim.verdict}")
        print(f"       code-output ({target}) = {code_out}")
        print(f"       reported (paper table)  = {reported if reported is not None else 'PENDING (paper PDF walled)'}")
        if sig is None:
            reason = "reported value pending" if reported is None else "code output unreadable"
            print(f"       verifier -> ABSTAIN ({reason})")
        else:
            print(f"       verifier -> {'FLAG (inconsistent)' if sig.fired else 'PASS (consistent)'}  conf={sig.confidence}")

    # demo: once the reported value is filled in, the (now CI-aware) verifier judges it correctly.
    # xgb is stochastic; the verifier reads the code output + its OWN bootstrap CI and compares.
    # 0.837 (CODECHECK) stands in for the pending paper Table 2 value; it differs from the 0.845
    # rerun only by seed, so it must NOT be flagged.
    from dataclasses import replace

    c1 = next(c for c in case.claims if c.claim_id == "pbc_c1")
    filled = replace(c1, metadata={**(c1.metadata or {}), "reported_value": "0.837"})
    cv = replay("", "code/results/summary_metrics.csv:xgb_C_mean", case)
    sig = verify(filled, case)
    verdict = "ABSTAIN" if sig is None else ("FLAG (inconsistent)" if sig.fired else "PASS (consistent, CI-aware)")
    fixed = values_consistent("0.837", cv.value) if cv.ok else False
    print("\ndemo: fill reported=0.837 (CODECHECK stand-in) for pbc_c1")
    print(f"      code-output {cv.value:.4f}  95% boot CI [{cv.ci_lo:.3f},{cv.ci_hi:.3f}]  sd {cv.sd:.3f}")
    print(f"      verifier -> {verdict}   (a naive fixed 1e-3 tol would say {'consistent' if fixed else 'INCONSISTENT'})")
    print("      >>> CI-aware tolerance stops a reproducible seed difference from reading as fraud (FP trap).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
