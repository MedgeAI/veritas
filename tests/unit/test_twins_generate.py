"""Unit tests for engine.twins.generate — config-driven multi-mother twin generation.

Uses a synthetic in-memory workbook (no dependency on downloaded mother data), so it proves the
generator is mother-agnostic and that an injected relationship round-trips into both the
annotation (claim_type) and the numeric detector (it actually fires).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from engine.benchmark.schema import load_annotations
from engine.static_audit.tools.source_data_findings import (
    duplicate_column_findings,
    fixed_relationship_findings,
    parse_workbook_vectors,
)
from engine.twins.generate import InjectionSpec, MotherConfig, generate_twins


def _make_mother(base_dir: Path) -> str:
    """A tiny mother with two real-numeric columns (B varied, C to be overwritten)."""
    base_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "s1"
    ws.append(["label", "B", "C"])
    for i in range(1, 41):
        ws.append([f"row-{i}", i * 1.7 + 0.5, i * 9.0 - 3.0])
    name = "mother.xlsx"
    wb.save(base_dir / name)
    return name


def test_generate_twins_writes_layout_and_annotation(tmp_path: Path):
    base = tmp_path / "mother_dir"
    workbook = _make_mother(base)
    config = MotherConfig(
        paper_id="TEST-mother",
        base_dir=str(base),
        specs=(
            InjectionSpec("duplicate_columns", workbook, "s1", 2, 41, source_column="B", target_column="C", seq=1),
        ),
    )
    twins_root = tmp_path / "twins"
    summary = generate_twins(config, twins_root)

    assert len(summary) == 1
    twin_dir = twins_root / "TEST-mother__duplicate_columns__01"
    assert (twin_dir / "supplementary" / workbook).exists()
    log = json.loads((twin_dir / "injection_log.json").read_text(encoding="utf-8"))
    assert log["class"] == "duplicate_columns"
    assert log["claim_type"] == "source_data.duplicate_columns"

    case = load_annotations(twin_dir / "annotations.yaml", split="synthetic-dev")
    assert case.case_id == "TEST-mother"
    claim = case.claims[0]
    assert claim.claim_type == "source_data.duplicate_columns"
    assert claim.level == "L3"
    assert claim.source == "injected"
    assert claim.deterministically_verifiable is True


def test_injected_relationship_is_detectable(tmp_path: Path):
    # after copying B -> C, the numeric detector must flag the duplicate on the twin.
    base = tmp_path / "mother_dir"
    workbook = _make_mother(base)
    config = MotherConfig(
        paper_id="TEST-mother",
        base_dir=str(base),
        specs=(InjectionSpec("fixed_ratio", workbook, "s1", 2, 41, source_column="B", target_column="C", factor=2.0, seq=1),),
    )
    twins_root = tmp_path / "twins"
    generate_twins(config, twins_root)
    path = twins_root / "TEST-mother__fixed_ratio__01" / "supplementary" / workbook
    cats = set()
    for sheet in parse_workbook_vectors(path):
        if sheet.sheet != "s1":
            continue
        cats |= {f.get("category") for f in duplicate_column_findings(sheet, 8, 0.95, 200)}
        cats |= {f.get("category") for f in fixed_relationship_findings(sheet, 8, 0.95, 200)}
    assert "fixed_ratio" in cats


def test_missing_required_param_fails_loud(tmp_path: Path):
    base = tmp_path / "mother_dir"
    workbook = _make_mother(base)
    # fixed_ratio without a factor must raise, not silently produce a bad twin.
    config = MotherConfig(
        paper_id="TEST-mother",
        base_dir=str(base),
        specs=(InjectionSpec("fixed_ratio", workbook, "s1", 2, 41, source_column="B", target_column="C", seq=1),),
    )
    with pytest.raises(ValueError):
        generate_twins(config, tmp_path / "twins")
