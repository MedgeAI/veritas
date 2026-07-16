"""Tests for the generic recompute verifier (engine.benchmark.recompute_verifier).

Reference functions are checked against real rep_ corpus data where present; the recompute_verify
dispatcher is checked with synthetic contract blocks for every tolerance kind, pass AND fail.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from engine.benchmark.recompute_verifier import (
    REFERENCE_REGISTRY,
    cell_lookup,
    count_where,
    recompute_verify,
)

COEXPR = Path("benchmarks/veritasbench/cases/rep_coexpr/artifacts/de_analysis_correct.csv")


def _write_csv(p: Path, header, rows):
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_registry_has_core_families():
    assert {"count_where", "cell_lookup", "fraction_where", "pearson"} <= set(REFERENCE_REGISTRY)


CASES = Path("benchmarks/veritasbench/cases")


@pytest.mark.skipif(not COEXPR.exists(), reason="corpus not present")
def test_count_where_matches_real_coexpr():
    # obs n_sig_donor_padj05 == 0 in the signed data
    assert count_where([COEXPR], {"column": "padj", "op": "<", "thresh": 0.05}) == 0


@pytest.mark.skipif(not CASES.exists(), reason="corpus not present")
def test_count_in_top_n_strip_truncates_at_delimiter():
    from engine.benchmark.recompute_verifier import count_in_top_n
    hsp = ["HSPA1B", "DNAJB2", "HSPA1A", "HSPE1", "HSPH1", "HSP90AA1", "HSPD1", "CIRBP", "CACYBP", "PTGES3"]
    args = {"rank_col": "rank", "top_n": 20, "gene_col": "gene", "gene_strip": "##", "gene_in": hsp}
    art = CASES / "rep_coexpr/artifacts"
    # 'HSPA1B##1' must truncate to 'HSPA1B' (match), not 'HSPA1B1' (miss) -> naive=10, correct=0
    assert count_in_top_n([art / "dysregulated_program_naive.csv"], args) == 10
    assert count_in_top_n([art / "dysregulated_program_correct.csv"], args) == 0


@pytest.mark.skipif(not CASES.exists(), reason="corpus not present")
def test_rule_classify_mediator_correct_and_naive():
    from engine.benchmark.recompute_verifier import rule_classify
    art = CASES / "rep_mediator/artifacts"
    assert rule_classify([art / "perturbation_summary_correct.csv"],
                         {"rule": "mediator_call_correct", "key_col": "perturbation", "key": "KO_13",
                          "n_deg_col": "n_deg", "mtdna_col": "mean_mtDNA_copy_number",
                          "depl_thr": 279125, "n_deg_thr": 200}) == "shared"
    assert rule_classify([art / "perturbation_summary_naive.csv"],
                         {"rule": "mediator_call_naive", "key_col": "perturbation", "key": "KO_13",
                          "n_deg_col": "n_deg", "n_deg_thr": 200}) == "gene_specific"


@pytest.mark.skipif(not CASES.exists(), reason="corpus not present")
def test_top_n_per_group_rtkfeedback():
    from engine.benchmark.recompute_verifier import top_n_per_group
    assert top_n_per_group([CASES / "rep_rtkfeedback/artifacts/naive_drug_response.csv"],
                           {"group_col": "model", "score_col": "response_magnitude", "n": 3,
                            "target": {"drug_id": "Drug_D", "model": "Model_A"}, "pos": "yes", "neg": "no"}) == "yes"


def test_cell_lookup_by_row_and_line(tmp_path):
    p = tmp_path / "out.csv"
    _write_csv(p, ["metric", "value"], [["pearson_r", "0.963"], ["MAE", "4.02"]])
    assert cell_lookup([p], {"row": {"metric": "pearson_r"}, "column": "value"}) == "0.963"
    assert cell_lookup([p], {"line": 2, "column": "value"}) == "0.963"  # physical line 2 = first data row


def test_verify_exact_and_reltol(tmp_path):
    p = tmp_path / "de.csv"
    _write_csv(p, ["padj"], [["0.01"], ["0.2"], ["0.6"]])
    obs_ok = {"value": 1, "recompute": {"inputs": [p.name], "metric_type": "count",
              "method": {"reference_fn": "count_where", "args": {"column": "padj", "op": "<", "thresh": 0.05}},
              "tolerance": {"kind": "exact"}}}
    assert recompute_verify(obs_ok, tmp_path, {}) == "ok"
    obs_bad = {**obs_ok, "value": 2}
    assert recompute_verify(obs_bad, tmp_path, {}).startswith("fail")


def test_verify_ci_interval_pass_and_fail():
    # ci_interval needs no live recompute — it checks the point against sibling CI-bound obs.
    obs_index = {"c#lo": {"value": 0.82}, "c#hi": {"value": 0.87}}
    contract = {"recompute": {"metric_type": "ci_bounded_stat", "inputs": [], "method": {},
                "tolerance": {"kind": "ci_interval", "lo_obs": "c#lo", "hi_obs": "c#hi"}}}
    inside = {**contract, "value": 0.845}   # bootstrap noise inside CI -> not flagged
    outside = {**contract, "value": 0.90}   # genuinely outside -> flagged
    assert recompute_verify(inside, Path("."), obs_index) == "ok"
    assert recompute_verify(outside, Path("."), obs_index).startswith("fail")


def test_verify_skips_code_entry(tmp_path):
    obs = {"value": 1.0, "recompute": {"inputs": [], "metric_type": "count",
           "method": {"code_entry": "solve.py::main"}, "tolerance": {"kind": "exact"}}}
    assert recompute_verify(obs, tmp_path, {}).startswith("skip:code_entry")


def test_no_contract_is_nonaddr():
    assert recompute_verify({"value": 1}, Path("."), {}) == "nonaddr"
