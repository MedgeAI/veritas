"""Trace-retention schema tests for the eval loop (no API — deterministic paths only).

Locks the evidence-packet shape and the invariant that gold fields live ONLY under the audit-only
`gold` key and never inside `input` (what the agent saw). Mirrors the MedgeBench trace-packet
discipline: input / output / parsed / scored / gold kept as separate layers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts.run_veritasbench_eval as R
from engine.benchmark.agent_harness import build_prompt, run_tool_augmented_agent
from engine.benchmark.veritasbench_eval_adapter import load_veritasbench_case, veritasbench_renderer
from engine.benchmark.veritasbench_verifiers import l1_relationship_verifier

CASES = Path("benchmarks/veritasbench/cases")
PACKET_KEYS = {"tier", "repeat", "case_id", "claim_id", "gold", "input", "output", "parsed", "scored", "verifier"}


def _cases():
    return [load_veritasbench_case(CASES / c)[0] for c in ["ncb_eet", "ncb_wnt"]]


@pytest.mark.skipif(not CASES.exists(), reason="signed corpus not present")
def test_b3_trace_packet_schema():
    cases = _cases()
    verify = l1_relationship_verifier()
    b3 = [run_tool_augmented_agent(c, lambda p: {}, [verify]) for c in cases]
    lines = R._trace_verifier_tier(cases, b3, verify, "B3_verifier")
    assert lines and all(set(x) == PACKET_KEYS for x in lines)
    # deterministic tier: verifier signal present, no agent input/output
    assert all(x["verifier"] is not None and x["output"]["raw_response"] is None for x in lines)
    # gold is recorded (audit) but is its own layer
    assert all({"verdict", "label", "discrepancy_type"} <= set(x["gold"]) for x in lines)


@pytest.mark.skipif(not CASES.exists(), reason="signed corpus not present")
def test_leak_scan_and_gold_absent_from_agent_input():
    cases = _cases()
    render = veritasbench_renderer()
    leak = R._leak_scan(cases, render)
    assert leak["gold_leak_free"] and leak["prompts_scanned"] == sum(len(c.claims) for c in cases)
    # the prompt must not name the failure mode (no "suspicious"/"duplicate"/"fraud"/... hints)
    assert leak["task_hint_free"]
    # the exact prompt the agent sees must contain no gold verdict / discrepancy / gold span
    for case in cases:
        for claim in case.claims:
            prompt = build_prompt(claim, case, artifacts_text=render(claim, case))
            for tok in R._forbidden_tokens(claim):
                assert tok not in prompt
            if claim.verdict:
                # the gold verdict word must not be handed over as the answer
                assert f'"verdict": "{claim.verdict}"' not in prompt
