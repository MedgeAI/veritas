"""Tests for paperconan adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.static_audit.adapters import paperconan_adapter
from engine.static_audit.adapters.paperconan_adapter import (
    PaperconanAdapterError,
    run_paperconan_scan,
)
from engine.tools.registry import (
    PAPERCONAN_NUMERIC_FORENSICS_TOOL_ID,
    TOOLS,
    coerce_tool_params,
)


def test_paperconan_tool_registered() -> None:
    """Verify paperconan tool is registered in the Tool Registry."""
    assert PAPERCONAN_NUMERIC_FORENSICS_TOOL_ID in TOOLS
    tool = TOOLS[PAPERCONAN_NUMERIC_FORENSICS_TOOL_ID]
    assert tool.tool_id == "paperconan.numeric_forensics"
    assert tool.source == "third_party/paperconan"
    assert tool.agent_selectable is True
    assert tool.deterministic is True
    assert "numeric/paperconan_scan.json" in tool.output_artifacts


def test_paperconan_coerce_params_valid() -> None:
    """Verify paperconan params are coerced correctly."""
    # Default profile
    params = coerce_tool_params(PAPERCONAN_NUMERIC_FORENSICS_TOOL_ID, {})
    assert params == {"profile": "review"}

    # Explicit valid profiles
    for profile in ("review", "forensic", "triage"):
        params = coerce_tool_params(
            PAPERCONAN_NUMERIC_FORENSICS_TOOL_ID, {"profile": profile}
        )
        assert params == {"profile": profile}


def test_paperconan_coerce_params_invalid() -> None:
    """Verify paperconan params reject invalid profile."""
    with pytest.raises(ValueError, match="profile must be one of"):
        coerce_tool_params(PAPERCONAN_NUMERIC_FORENSICS_TOOL_ID, {"profile": "invalid"})


def test_paperconan_adapter_missing_source_data_dir(tmp_path: Path) -> None:
    """Verify adapter raises error when source_data_dir does not exist."""
    nonexistent = tmp_path / "nonexistent"
    output_dir = tmp_path / "output"

    with pytest.raises(PaperconanAdapterError, match="does not exist"):
        run_paperconan_scan(nonexistent, output_dir)


def test_paperconan_adapter_empty_source_data_dir(tmp_path: Path) -> None:
    """Verify adapter handles empty source data directory gracefully."""
    source_data_dir = tmp_path / "source_data"
    source_data_dir.mkdir()
    output_dir = tmp_path / "output"

    result = run_paperconan_scan(source_data_dir, output_dir)

    # Should return "no_data" status, not raise an error
    assert result["status"] == "no_data"
    assert (
        "no .xlsx" in result["error"].lower()
        or "no supported files" in result["error"].lower()
    )
    assert result["findings_summary"]["total"] == 0
    assert result["artifact_path"] is not None

    # Verify error artifact was written
    artifact_path = Path(result["artifact_path"])
    assert artifact_path.exists()
    artifact = json.loads(artifact_path.read_text())
    assert artifact["status"] == "no_data"


@pytest.mark.xfail(raises=Exception, reason="Known failure, tracked in review-fix-decisions.md")
def test_paperconan_adapter_with_synthetic_data(tmp_path: Path) -> None:
    """Verify adapter runs successfully on synthetic data with known patterns.

    This test creates a minimal xlsx file with a known fabrication pattern
    (identical columns) and verifies the adapter detects it.
    """
    try:
        import openpyxl
    except ImportError:
        pytest.skip("openpyxl not installed")

    # Create synthetic source data with identical columns (a known fabrication pattern)
    source_data_dir = tmp_path / "source_data"
    source_data_dir.mkdir()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # Write header
    ws["A1"] = "Sample"
    ws["B1"] = "Control"
    ws["C1"] = "Treatment"
    ws["D1"] = "Duplicate_of_Control"

    # Write data: Control and Duplicate_of_Control are identical (fabrication pattern)
    for i in range(2, 12):
        ws[f"A{i}"] = f"Sample_{i - 1}"
        ws[f"B{i}"] = 10.0 + i  # Control: 11, 12, 13, ...
        ws[f"C{i}"] = 15.0 + i  # Treatment: 16, 17, 18, ...
        ws[f"D{i}"] = 10.0 + i  # Duplicate of Control (identical)

    xlsx_path = source_data_dir / "synthetic_data.xlsx"
    wb.save(xlsx_path)

    output_dir = tmp_path / "output"
    result = run_paperconan_scan(source_data_dir, output_dir)

    # Verify scan succeeded
    assert result["status"] == "success"
    assert result["tool"] == "paperconan"
    assert result["tool_version"] != "unknown"

    # Verify findings summary
    summary = result["findings_summary"]
    assert summary["total"] > 0, "Expected at least one finding (identical columns)"
    assert (
        "identical_column" in summary["by_kind"]
        or "constant_offset" in summary["by_kind"]
    ), f"Expected identical_column or constant_offset finding, got {summary['by_kind']}"

    # Verify artifact was written
    artifact_path = Path(result["artifact_path"])
    assert artifact_path.exists()
    artifact = json.loads(artifact_path.read_text())
    assert artifact["status"] == "success"
    assert "scan_result" in artifact

    # Verify scan_result contains the expected structure
    scan_result = artifact["scan_result"]
    assert "tool" in scan_result
    assert scan_result["tool"] == "paperconan"
    assert "relations_blocks" in scan_result
    assert len(scan_result["relations_blocks"]) > 0
    assert not (output_dir / "scan.json").exists()
    assert artifact["artifact_policy"]["upstream_scan_json"] == "disabled"
    assert not _has_key(artifact, "evidence")


def test_paperconan_adapter_strips_bulky_upstream_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_data_dir = tmp_path / "source_data"
    source_data_dir.mkdir()
    (source_data_dir / "data.csv").write_text("a,b\n1,1\n2,2\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "scan.json").write_text('{"legacy": true}', encoding="utf-8")

    def fake_scan_dir(**_: object) -> dict:
        return {
            "tool": "paperconan",
            "tool_version": "test",
            "relations_blocks": [
                {
                    "file": "data.csv",
                    "sheet": "data",
                    "block": {"rows": "1-2", "cols": "1-2"},
                    "relations": [
                        {
                            "kind": "identical_column",
                            "severity": "high",
                            "evidence": {"rows": [{"values": [1, 2, 3]}]},
                            "raw_values": [1, 2, 3],
                            "base64": "x" * 1000,
                        }
                    ],
                    "progressions": [],
                    "equal_pairs": [],
                    "within_col": [],
                    "identical_after_rounding": [],
                    "grim": [],
                }
            ],
            "cross_sheet_findings": [],
            "digit_distribution": [],
            "decimal_endings": [],
        }

    def fake_load_paperconan() -> tuple[object, type[Exception]]:
        return fake_scan_dir, ValueError

    monkeypatch.setattr(paperconan_adapter, "_load_paperconan", fake_load_paperconan)

    result = run_paperconan_scan(source_data_dir, output_dir)
    artifact = json.loads(Path(result["artifact_path"]).read_text())

    assert result["findings_summary"]["total"] == 1
    assert not (output_dir / "scan.json").exists()
    assert not _has_key(artifact, "evidence")
    assert not _has_key(artifact, "raw_values")
    assert not _has_key(artifact, "base64")


def test_paperconan_adapter_preserves_new_detector_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """New paperconan detector fields must survive _compact_scan_result().

    paperconan added 5 new detectors (decimal_tail_reuse, column_duplicate,
    recurring_row_vector, fraction_reuse, partial_constant_offset, etc.) whose
    finding dicts carry detector-specific fields like decimal_tail, vector,
    fraction_of_smaller, run_length, etc. These are NOT in the blocklist and
    must not be stripped by _drop_bulky_fields().
    """
    source_data_dir = tmp_path / "source_data"
    source_data_dir.mkdir()
    (source_data_dir / "data.csv").write_text("a,b\n1,1\n2,2\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    def fake_scan_dir(**_: object) -> dict:
        return {
            "tool": "paperconan",
            "tool_version": "test",
            "relations_blocks": [
                {
                    "file": "data.csv",
                    "sheet": "data",
                    "block": {"rows": "1-10", "cols": "A-B"},
                    "relations": [
                        {
                            "kind": "row_pair_digit_coupling",
                            "severity": "high",
                            "examples": "5 pairs",
                            "example_cells": "A2:A6, B2:B6",
                            "same_decimal1": 4,
                            "same_ones_decimal1": 3,
                            "coarse_10_diff": 1,
                            "top_diffs": [[1, 2], [3, 4]],
                            "n_shared_fraction": "4/5",
                            "n_high_precision": 3,
                        },
                        {
                            "kind": "partial_constant_offset",
                            "severity": "medium",
                            "run_length": 8,
                            "offset": 0.5,
                        },
                    ],
                    "progressions": [],
                    "equal_pairs": [],
                    "within_col": [],
                    "identical_after_rounding": [],
                    "grim": [],
                }
            ],
            "cross_sheet_findings": [
                {
                    "kind": "cross_sheet_decimal_tail_reuse",
                    "severity": "low",
                    "decimal_tail": "00",
                    "tail_match_count": 12,
                    "offset_rows": 0,
                    "offset_cols": 1,
                    "min_tail_digits": 2,
                    "skip_decimal_digits": 0,
                    "label_context_a": "Sheet1!B",
                    "label_context_b": "Sheet2!C",
                },
                {
                    "kind": "cross_sheet_column_duplicate",
                    "severity": "low",
                    "same_position_count": 45,
                    "fraction_of_smaller": 0.95,
                    "block_a": "Sheet1!A1:A50",
                    "block_b": "Sheet2!B1:B50",
                },
                {
                    "kind": "recurring_row_vector",
                    "severity": "high",
                    "vector": [1, 2, 3],
                    "pattern": "arithmetic",
                    "n_occurrences": 7,
                    "n_figures": 3,
                },
                {
                    "kind": "within_table_fraction_reuse",
                    "severity": "high",
                    "fraction_of_smaller": 0.80,
                    "block_a": "A1:A20",
                    "block_b": "C1:C20",
                },
                {
                    "kind": "integer_diff_shared_fraction",
                    "severity": "medium",
                    "n_shared_fraction": "15/20",
                    "n_high_precision": 10,
                },
            ],
            "digit_distribution": [],
            "decimal_endings": [],
        }

    def fake_load_paperconan() -> tuple[object, type[Exception]]:
        return fake_scan_dir, ValueError

    monkeypatch.setattr(paperconan_adapter, "_load_paperconan", fake_load_paperconan)

    result = run_paperconan_scan(source_data_dir, output_dir)
    artifact = json.loads(Path(result["artifact_path"]).read_text())
    scan_result = artifact["scan_result"]

    # --- relations_blocks: row_pair_digit_coupling fields survive ---
    rel = scan_result["relations_blocks"][0]["relations"][0]
    assert rel["examples"] == "5 pairs"
    assert rel["example_cells"] == "A2:A6, B2:B6"
    assert rel["same_decimal1"] == 4
    assert rel["same_ones_decimal1"] == 3
    assert rel["coarse_10_diff"] == 1
    assert rel["top_diffs"] == [[1, 2], [3, 4]]
    assert rel["n_shared_fraction"] == "4/5"
    assert rel["n_high_precision"] == 3

    # --- relations_blocks: partial_constant_offset fields survive ---
    pco = scan_result["relations_blocks"][0]["relations"][1]
    assert pco["run_length"] == 8
    assert pco["offset"] == 0.5

    # --- cross_sheet_findings: decimal_tail_reuse fields survive ---
    dtr = scan_result["cross_sheet_findings"][0]
    assert dtr["kind"] == "cross_sheet_decimal_tail_reuse"
    assert dtr["decimal_tail"] == "00"
    assert dtr["tail_match_count"] == 12
    assert dtr["offset_rows"] == 0
    assert dtr["offset_cols"] == 1
    assert dtr["min_tail_digits"] == 2
    assert dtr["skip_decimal_digits"] == 0
    assert dtr["label_context_a"] == "Sheet1!B"
    assert dtr["label_context_b"] == "Sheet2!C"

    # --- cross_sheet_findings: column_duplicate fields survive ---
    cd = scan_result["cross_sheet_findings"][1]
    assert cd["same_position_count"] == 45
    assert cd["fraction_of_smaller"] == 0.95
    assert cd["block_a"] == "Sheet1!A1:A50"
    assert cd["block_b"] == "Sheet2!B1:B50"

    # --- cross_sheet_findings: recurring_row_vector fields survive ---
    rrv = scan_result["cross_sheet_findings"][2]
    assert rrv["vector"] == [1, 2, 3]
    assert rrv["pattern"] == "arithmetic"
    assert rrv["n_occurrences"] == 7
    assert rrv["n_figures"] == 3

    # --- cross_sheet_findings: fraction_reuse fields survive ---
    wtf = scan_result["cross_sheet_findings"][3]
    assert wtf["fraction_of_smaller"] == 0.80

    # --- cross_sheet_findings: integer_diff_shared_fraction fields survive ---
    idsf = scan_result["cross_sheet_findings"][4]
    assert idsf["n_shared_fraction"] == "15/20"
    assert idsf["n_high_precision"] == 10

    # Verify total finding count
    assert result["findings_summary"]["total"] == 7


def _has_key(value: object, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_has_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_has_key(item, key) for item in value)
    return False
