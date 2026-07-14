"""Unit tests for engine.twins.matched_clean — FAR clean-control minting.

Uses a synthetic pristine workbook (three real-numeric columns), so it verifies the column
universe, injected-pair exclusion, FAR arithmetic, and that the emitted rows round-trip through
the benchmark schema as label=clean.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from openpyxl import Workbook

from engine.benchmark.schema import load_annotations
from engine.twins.matched_clean import (
    CleanControl,
    clean_control_rows,
    enumerate_clean_controls,
    far,
    flagged_pairs,
)


def _pristine(path_dir: Path) -> Path:
    path_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "s1"
    ws.append(["label", "B", "C", "D"])           # B,C,D numeric
    for i in range(1, 21):
        ws.append([f"r{i}", i * 1.1, i * 2.7 + 1, 100 - i])
    p = path_dir / "pristine.xlsx"
    wb.save(p)
    return p


def test_enumerate_excludes_injected_pairs(tmp_path: Path):
    p = _pristine(tmp_path)
    all_ctrls = enumerate_clean_controls(p, "s1", min_overlap=8)
    # 3 numeric columns (B,C,D) -> C(3,2)=3 pairs
    assert len(all_ctrls) == 3
    pairs = {c.pair_key for c in all_ctrls}
    assert pairs == {frozenset(("B", "C")), frozenset(("B", "D")), frozenset(("C", "D"))}

    minus = enumerate_clean_controls(p, "s1", min_overlap=8, exclude_pairs={frozenset(("B", "C"))})
    assert len(minus) == 2
    assert frozenset(("B", "C")) not in {c.pair_key for c in minus}


def test_far_arithmetic():
    controls = [
        CleanControl("w", "s", "B", "C"),
        CleanControl("w", "s", "B", "D"),
        CleanControl("w", "s", "C", "D"),
    ]
    flagged = {frozenset(("B", "C"))}
    result = far(controls, flagged)
    assert result == {"far": 1 / 3, "flagged": 1, "total": 3}
    assert far(controls, set())["far"] == 0.0
    assert far([], flagged) == {"far": 0.0, "flagged": 0, "total": 0}


def test_flagged_pairs_reads_column_pair():
    findings = [
        {"category": "duplicate_numeric_columns", "column_pair": ["AG", "AM"]},
        {"category": "fixed_ratio", "column_pair": ["I", "AG"]},
        {"category": "other"},  # no column_pair -> ignored
    ]
    assert flagged_pairs(findings) == {frozenset(("AG", "AM")), frozenset(("I", "AG"))}


def test_clean_rows_load_as_clean_claims(tmp_path: Path):
    p = _pristine(tmp_path)
    controls = enumerate_clean_controls(p, "s1", min_overlap=8)
    doc = {"paper": {"base_paper_id": "T", "source": "injected"}, "claims": clean_control_rows(controls)}
    yaml_path = tmp_path / "clean.annotations.yaml"
    yaml_path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    case = load_annotations(yaml_path, split="synthetic-dev")
    assert len(case.claims) == 3
    assert not case.dirty_claims()
    assert len(case.clean_claims()) == 3
    assert all(c.level == "L3" for c in case.claims)
