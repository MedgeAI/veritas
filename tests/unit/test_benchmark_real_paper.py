"""Unit tests for engine.benchmark.real_paper — config-driven real-paper scoring.

springer_prefix encodes a fragile DOI->filename rule (3-digit year -> 4-digit, zero-stripped
article number) validated on real papers; lock it. score_real_paper is exercised on a synthetic
two-sheet workbook (one dirty duplicate sheet + one benign sheet) so recall/FAR are checkable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from engine.benchmark.real_paper import (
    DirtyLocus,
    RealPaperCase,
    score_real_paper,
    springer_moesm_url,
    springer_prefix,
)


def test_springer_prefix_rule():
    assert springer_prefix("10.1038/s41588-025-02253-8") == "41588_2025_2253"  # paper2 (NPC)
    assert springer_prefix("10.1038/s41588-023-01321-1") == "41588_2023_1321"  # CNS-058
    assert springer_prefix("10.1038/s41467-025-66106-x") == "41467_2025_66106"  # CNS-098
    with pytest.raises(ValueError):
        springer_prefix("10.1000/not-a-springer-doi")


def test_springer_moesm_url_encodes_doi():
    url = springer_moesm_url("10.1038/s41588-025-02253-8", 9)
    assert "art%3A10.1038%2Fs41588-025-02253-8" in url
    assert url.endswith("41588_2025_2253_MOESM9_ESM.xlsx")


def _write_paper(tmp_path: Path) -> Path:
    """One workbook: a DIRTY sheet (col C copied from B) + a BENIGN sheet (independent columns)."""
    data = tmp_path / "paper"
    data.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    dirty = wb.active
    dirty.title = "Fig.1a"
    dirty.append(["label", "B", "C"])
    for i in range(1, 41):
        v = i * 1.7 + 0.3
        dirty.append([f"r{i}", v, v])  # C == B -> duplicate_numeric_columns
    benign = wb.create_sheet("Fig.2b")
    benign.append(["label", "X", "Y"])
    for i in range(1, 41):
        benign.append([f"r{i}", i * 1.1 + 0.2, i * i * 0.37 - 5])  # unrelated
    wb.save(data / "mock_MOESM1_ESM.xlsx")
    return data


def test_score_real_paper_recall_and_far(tmp_path: Path):
    data = _write_paper(tmp_path)
    case = RealPaperCase(
        paper_id="MOCK",
        doi="10.1038/s41588-025-02253-8",
        data_dir=str(data),
        dirty=(DirtyLocus("mock_MOESM1_ESM.xlsx", "Fig.1a", "source_data.duplicate_columns", "#1"),),
    )
    result = score_real_paper(case)
    # the dirty duplicate is detected -> recall 1/1
    assert result["recall"]["detected"] == 1
    # the one benign sheet contributes a clean control (X,Y); it must NOT be flagged -> FAR 0
    assert result["far"]["total"] >= 1
    assert result["far"]["far"] == 0.0
    assert result["main_table_row"]["claim_recall"] == 1.0
