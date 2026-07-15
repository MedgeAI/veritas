"""Smoke/regression tests for the read-only QC verifier (scripts/qc_veritasbench.py).

Locks the extraction dialects against the signed corpus: known-good cases must stay fully
addressable and clean, and the CSV `row k=v, column C` parser must behave. Corpus-dependent, so
skipped when the benchmark tree is absent; the mirror validator is optional and not exercised here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.qc_veritasbench import _parse_csv_span, check_case

BASE = Path("benchmarks/veritasbench/cases")


def test_parse_csv_span_compound_keys():
    # compound row key + quoted value, target column after
    filters, col = _parse_csv_span("f.csv, row a=1, b='x y', column score (note)")
    assert col == "score"
    assert ("a", "1") in filters and ("b", "x y") in filters


def test_parse_csv_span_none_when_not_addressable():
    assert _parse_csv_span("de.csv, 严谨复现: FDR<0.05 的基因数 = 0") is None


@pytest.mark.skipif(not BASE.exists(), reason="signed corpus not present")
@pytest.mark.parametrize("cid", ["ncb_lgr4", "ncb_clonalfish", "rep_methclock", "rep_mediator"])
def test_known_good_cases_clean(cid):
    r = check_case(cid, BASE, mirror=None)  # mirror skipped (None); structural + extractability only
    assert not r["fail"], f"{cid} unexpectedly failed: {r['fails'] or r['hash_fail'] or r['a1_missing']}"
    assert not r["hash_fail"] and not r["a1_missing"]


@pytest.mark.skipif(not BASE.exists(), reason="signed corpus not present")
def test_clonalfish_line_contract_all_extractable():
    # the L<file_line>:<column> CSV obs must all re-read correctly after the Round-2 fix
    r = check_case("ncb_clonalfish", BASE, mirror=None)
    assert r["ok"] == r["total"] and not r["nonaddr"]
