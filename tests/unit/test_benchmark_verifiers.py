"""Unit tests for engine.benchmark.verifiers — the REAL source-data TypedVerifier (no mock).

A synthetic workbook with a dirty sheet (two identical numeric columns) + a benign sheet (two
independent columns) is written to disk; the verifier runs the actual detectors and must fire on
the dirty sheet, stay silent on the benign one, and decline out-of-scope claims. Wired into B3 it
must catch + ground the dirty claim while leaving the clean one alone.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from engine.benchmark.agent_harness import run_tool_augmented_agent
from engine.benchmark.metrics import main_table_row
from engine.benchmark.schema import (
    LABEL_CLEAN,
    LABEL_DIRTY,
    LEVEL_RELATION,
    BenchmarkCase,
    ClaimInstance,
    Evidence,
)
from engine.benchmark.verifiers import source_data_renderer, source_data_verifier

WORKBOOK = "m.xlsx"


def _write_workbook(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    dirty = wb.active
    dirty.title = "dirtysheet"
    dirty.append(["label", "B", "C"])
    for i in range(1, 16):
        v = i * 1.7 + 0.5
        dirty.append([f"r{i}", v, v])            # C == B -> duplicate_numeric_columns
    benign = wb.create_sheet("benignsheet")
    benign.append(["label", "X", "Y"])
    for i in range(1, 16):
        benign.append([f"r{i}", i * 1.3 + 0.7, i * i * 0.9 - 3])  # independent
    wb.save(data_dir / WORKBOOK)


def _claim(sheet: str, label: str) -> ClaimInstance:
    return ClaimInstance(
        claim_id=f"c::{sheet}",
        claim_type="source_data.duplicate_columns",
        level="L3",
        label=label,
        relation=LEVEL_RELATION["L3"],
        evidence=Evidence(evidence_type="source_data", target=f"{WORKBOOK} / {sheet}",
                          workbook=WORKBOOK, sheet=sheet),
        evidence_span=f"L3:{WORKBOOK}->{WORKBOOK}:{sheet}",
    )


def _case(claims) -> BenchmarkCase:
    return BenchmarkCase(case_id="mock", split="real-test", base_paper_id="mock", claims=tuple(claims))


def test_verifier_fires_on_dirty_sheet(tmp_path: Path):
    _write_workbook(tmp_path)
    verify = source_data_verifier(tmp_path)
    sig = verify(_claim("dirtysheet", LABEL_DIRTY), _case([]))
    assert sig is not None and sig.fired
    assert sig.evidence_span == f"L3:{WORKBOOK}->{WORKBOOK}:dirtysheet"
    assert sig.confidence >= 0.6


def test_verifier_silent_on_benign_sheet(tmp_path: Path):
    _write_workbook(tmp_path)
    verify = source_data_verifier(tmp_path)
    sig = verify(_claim("benignsheet", LABEL_CLEAN), _case([]))
    assert sig is not None and not sig.fired


def test_verifier_out_of_scope_returns_none(tmp_path: Path):
    _write_workbook(tmp_path)
    verify = source_data_verifier(tmp_path)
    non_xlsx = ClaimInstance(
        claim_id="c::x", claim_type="method.unspecified", level="L2", label=LABEL_DIRTY,
        relation=LEVEL_RELATION["L2"], evidence=Evidence(evidence_type="code", target="analysis.py"),
    )
    assert verify(non_xlsx, _case([])) is None


def test_b3_with_real_verifier_catches_and_grounds(tmp_path: Path):
    _write_workbook(tmp_path)
    case = _case([_claim("dirtysheet", LABEL_DIRTY), _claim("benignsheet", LABEL_CLEAN)])
    useless = lambda p: {"verdict": "insufficient"}  # noqa: E731 — verifier carries the load
    row = main_table_row(run_tool_augmented_agent(case, useless, [source_data_verifier(tmp_path)]))
    assert row["claim_recall"] == 1.0        # dirty sheet flagged
    assert row["far"] == 0.0                 # benign sheet not flagged
    assert row["evidence_precision"] == 1.0  # grounded to the right sheet locus


def test_source_data_renderer_loads_real_sheet_content(tmp_path: Path):
    _write_workbook(tmp_path)
    render = source_data_renderer(tmp_path)
    text = render(_claim("dirtysheet", LABEL_DIRTY), _case([]))
    assert "dirtysheet" in text
    assert "r1:" in text and "r2:" in text     # row-numbered so the agent can cite loci
    assert "label, B, C" in text or "B, C" in text
