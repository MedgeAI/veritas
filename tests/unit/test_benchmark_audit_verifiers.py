"""Unit tests for engine.benchmark.audit_verifiers — duplicate-column forensics + neutral renderer.

Synthetic expression.csv columns cover the four cases that matter: exact copy, near-duplicate
(~10% perturbed), independent-clean, and merely-correlated hard-negative. The key assertions:
naive MISSES near-dups, robust CATCHES them, and robust does NOT flag a correlated-but-not-copied
pair (byte overlap ≈ 0) — separating copying from correlation.
"""

from __future__ import annotations

import csv
from pathlib import Path

from engine.benchmark.audit_verifiers import (
    audit_integrity_verifier,
    audit_renderer,
    detect_duplicate_columns,
)
from engine.benchmark.audit_adapter import AXIS_ARTIFACT
from engine.benchmark.schema import LABEL_DIRTY, LEVEL_RELATION, BenchmarkCase, ClaimInstance, Evidence


def _write_expr(path: Path, columns: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = list(columns)
    n = len(next(iter(columns.values())))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["feature_id"] + samples)
        for i in range(n):
            w.writerow([f"F{i:04d}"] + [columns[s][i] for s in samples])


def _cols(tmp_path: Path) -> Path:
    base = [round(1.0 + i * 1.37, 4) for i in range(30)]
    near = list(base)
    near[0], near[1], near[2] = 999.1, 888.2, 777.3          # perturb 3/30 = 10%
    corr = [round(v * 1.0001, 4) for v in base]              # r~1, slope~1: NOT a transform
    linear = [round(v * 1.5 + 3.0, 4) for v in base]         # slope 1.5 != 1: linear-transform (#5)
    indep = [round(2.0 + i * 0.91, 4) for i in range(30)]
    p = tmp_path / "expr.csv"
    _write_expr(p, {"S01": base, "S02": list(base), "S03": near, "S04": corr, "S05": linear, "S06": indep})
    return p


def test_naive_misses_near_dup_and_linear_robust_catches():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = _cols(Path(d))
        naive = {frozenset((a, b)) for a, b, _ in detect_duplicate_columns(p, mode="naive")}
        robust = {frozenset((a, b)) for a, b, _ in detect_duplicate_columns(p, mode="robust", threshold=0.5)}
        # exact copy S01==S02 caught by both
        assert frozenset(("S01", "S02")) in naive and frozenset(("S01", "S02")) in robust
        # near-dup S01~S03: robust catches (byte overlap), naive misses
        assert frozenset(("S01", "S03")) in robust and frozenset(("S01", "S03")) not in naive
        # linear-transform S01~S05 (slope 1.5, no identical values): robust catches via regression,
        # naive misses
        assert frozenset(("S01", "S05")) in robust and frozenset(("S01", "S05")) not in naive
        # correlated-not-transformed S01/S04 (slope~1): NEITHER flags -> copying/transform != mere corr
        assert frozenset(("S01", "S04")) not in robust and frozenset(("S01", "S04")) not in naive


def test_integrity_verifier_fires_on_duplicate(tmp_path):
    _write_expr(tmp_path / "dataset_01" / "expression.csv",
                {"S01": [1.0, 2.0, 3.0, 4.0], "S02": [1.0, 2.0, 3.0, 4.0], "S03": [9.0, 8.0, 7.0, 6.0]})
    _write_expr(tmp_path / "dataset_02" / "expression.csv",
                {"S01": [1.0, 2.0, 3.0, 4.0], "S02": [5.0, 6.0, 7.0, 8.0]})
    case = BenchmarkCase("t", "synthetic-test", "t", (), artifacts={"data": str(tmp_path)})

    def _iclaim(ds):
        return ClaimInstance(f"t::{ds}::integrity", "source_data.duplicate_columns", "L3", LABEL_DIRTY,
                             LEVEL_RELATION["L3"], Evidence("source_data", f"{ds}/expression.csv"),
                             metadata={"axis": AXIS_ARTIFACT, "dataset": ds})

    verify = audit_integrity_verifier(mode="robust")
    assert verify(_iclaim("dataset_01"), case).fired          # has a duplicate pair
    assert not verify(_iclaim("dataset_02"), case).fired       # independent columns


def test_renderer_is_neutral(tmp_path):
    _write_expr(tmp_path / "dataset_01" / "expression.csv",
                {"S01": [1.0, 2.0, 3.0, 4.0], "S02": [1.0, 2.0, 3.0, 4.0]})
    case = BenchmarkCase("t", "synthetic-test", "t", (), artifacts={"data": str(tmp_path)})
    claim = ClaimInstance("t::dataset_01::integrity", "source_data.duplicate_columns", "L3", LABEL_DIRTY,
                          LEVEL_RELATION["L3"], Evidence("source_data", "x"),
                          metadata={"axis": AXIS_ARTIFACT, "dataset": "dataset_01"})
    text = audit_renderer()(claim, case).lower()
    assert "correlation matrix" in text and "mean" in text     # raw descriptives present
    for leading in ("duplicat", "suspicious", "fabricat", "copied", "identical"):
        assert leading not in text                              # no leading hint that pre-judges
