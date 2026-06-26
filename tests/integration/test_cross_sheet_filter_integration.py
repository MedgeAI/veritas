"""Integration tests for cross-sheet LLM metadata column filter.

Exercises the REAL ``run_cross_sheet_filter`` and ``classify_columns_with_llm``
functions from engine.static_audit._shared.

Only the LLM client is mocked (external API boundary).  The rest of the
pipeline — column extraction, finding filtering, type annotation — runs
through real code.

Tests cover:
- Metadata / measurement / index classification
- Mixed column types in one finding
- LLM failure fallback (conservative: keep all findings)
- Empty findings list
- Classification annotation added to findings
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.static_audit._shared import (
    classify_columns_with_llm,
    run_cross_sheet_filter,
)


# ---------------------------------------------------------------------------
# Mock LLM client — external API boundary
# ---------------------------------------------------------------------------


class _MockLLMClient:
    """Mock LLM client for testing.  Returns a canned response or raises."""

    def __init__(self, response: dict | None = None, raise_error: bool = False):
        self.response = response or {}
        self.raise_error = raise_error

    def chat_json(self, prompt: str, **kwargs) -> dict:
        if self.raise_error:
            raise RuntimeError("LLM API failure")
        return self.response


# ---------------------------------------------------------------------------
# classify_columns_with_llm
# ---------------------------------------------------------------------------


class TestClassifyColumnsWithLLM:
    """Tests for classify_columns_with_llm function."""

    def test_metadata_classification(self):
        """Test that metadata columns are correctly classified."""
        column_names = ["patient_id", "sample_name", "group"]
        sample_values = {
            "patient_id": ["P001", "P002", "P003"],
            "sample_name": ["Sample_A", "Sample_B", "Sample_C"],
            "group": ["control", "treatment", "treatment"],
        }
        mock_client = _MockLLMClient(response={
            "patient_id": "metadata",
            "sample_name": "metadata",
            "group": "metadata",
        })

        result = classify_columns_with_llm(column_names, sample_values, mock_client)

        assert result == {
            "patient_id": "metadata",
            "sample_name": "metadata",
            "group": "metadata",
        }

    def test_measurement_classification(self):
        """Test that measurement columns are correctly classified."""
        column_names = ["expression", "count", "ratio"]
        sample_values = {
            "expression": [1.5, 2.3, 0.8],
            "count": [100, 200, 150],
            "ratio": [0.5, 0.7, 0.6],
        }
        mock_client = _MockLLMClient(response={
            "expression": "measurement",
            "count": "measurement",
            "ratio": "measurement",
        })

        result = classify_columns_with_llm(column_names, sample_values, mock_client)

        assert result == {
            "expression": "measurement",
            "count": "measurement",
            "ratio": "measurement",
        }

    def test_mixed_classification(self):
        """Test mixed column types in one call."""
        column_names = ["patient_id", "expression", "row_number"]
        sample_values = {
            "patient_id": ["P001", "P002"],
            "expression": [1.5, 2.3],
            "row_number": [1, 2],
        }
        mock_client = _MockLLMClient(response={
            "patient_id": "metadata",
            "expression": "measurement",
            "row_number": "index",
        })

        result = classify_columns_with_llm(column_names, sample_values, mock_client)

        assert result == {
            "patient_id": "metadata",
            "expression": "measurement",
            "row_number": "index",
        }

    def test_llm_failure_returns_empty(self):
        """Test that LLM failure returns empty dict."""
        column_names = ["patient_id", "expression"]
        sample_values = {
            "patient_id": ["P001"],
            "expression": [1.5],
        }
        mock_client = _MockLLMClient(raise_error=True)

        result = classify_columns_with_llm(column_names, sample_values, mock_client)

        assert result == {}

    def test_empty_column_list(self):
        """Test with empty column list."""
        mock_client = _MockLLMClient(response={})

        result = classify_columns_with_llm([], {}, mock_client)

        assert result == {}

    def test_case_normalization(self):
        """Test that classification values are normalized to lowercase."""
        column_names = ["patient_id"]
        sample_values = {"patient_id": ["P001"]}
        mock_client = _MockLLMClient(response={"patient_id": "METADATA"})

        result = classify_columns_with_llm(column_names, sample_values, mock_client)

        assert result == {"patient_id": "metadata"}


# ---------------------------------------------------------------------------
# run_cross_sheet_filter — end-to-end
# ---------------------------------------------------------------------------


class TestRunCrossSheetFilterIntegration:
    """End-to-end tests for run_cross_sheet_filter.

    The function takes a workdir, a list of findings, and an LLM client.
    It classifies columns and filters out findings where BOTH columns
    are metadata or index types.
    """

    def test_filter_metadata_findings(self, tmp_path: Path):
        """Test that metadata column findings are filtered out."""
        findings = [
            {
                "finding_id": "CSD-0001",
                "column_1": "patient_id",
                "column_2": "patient_id",
                "column_1_label": "P001",
                "column_2_label": "P001",
            },
            {
                "finding_id": "CSD-0002",
                "column_1": "expression",
                "column_2": "expression",
                "column_1_label": "1.5",
                "column_2_label": "1.5",
            },
        ]

        mock_client = _MockLLMClient(response={
            "patient_id": "metadata",
            "expression": "measurement",
        })

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        # CSD-0001 (both metadata) is filtered; CSD-0002 (both measurement) is kept
        assert len(filtered) == 1
        assert filtered[0]["finding_id"] == "CSD-0002"
        assert filtered[0]["column_1_type"] == "measurement"
        assert filtered[0]["column_2_type"] == "measurement"

    def test_filter_index_findings(self, tmp_path: Path):
        """Test that index column findings are filtered out."""
        findings = [
            {
                "finding_id": "CSD-0001",
                "column_1": "row_number",
                "column_2": "row_number",
            },
        ]

        mock_client = _MockLLMClient(response={"row_number": "index"})

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        assert len(filtered) == 0

    def test_keep_measurement_findings(self, tmp_path: Path):
        """Test that measurement column findings are kept."""
        findings = [
            {
                "finding_id": "CSD-0001",
                "column_1": "expression",
                "column_2": "count",
            },
        ]

        mock_client = _MockLLMClient(response={
            "expression": "measurement",
            "count": "measurement",
        })

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        assert len(filtered) == 1
        assert filtered[0]["finding_id"] == "CSD-0001"

    def test_llm_failure_conservative_fallback(self, tmp_path: Path):
        """Test that LLM failure keeps all findings (conservative)."""
        findings = [
            {
                "finding_id": "CSD-0001",
                "column_1": "patient_id",
                "column_2": "patient_id",
            },
            {
                "finding_id": "CSD-0002",
                "column_1": "expression",
                "column_2": "expression",
            },
        ]

        mock_client = _MockLLMClient(raise_error=True)

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        # All findings should be kept (conservative fallback)
        assert len(filtered) == 2

    def test_empty_findings_list(self, tmp_path: Path):
        """Test with empty findings list."""
        mock_client = _MockLLMClient(response={})

        filtered = run_cross_sheet_filter(tmp_path, [], mock_client)

        assert filtered == []

    def test_mixed_column_types_in_one_finding(self, tmp_path: Path):
        """Test finding with one metadata and one measurement column.

        If at least one column is a measurement, the finding is kept.
        """
        findings = [
            {
                "finding_id": "CSD-0001",
                "column_1": "patient_id",  # metadata
                "column_2": "expression",  # measurement
            },
        ]

        mock_client = _MockLLMClient(response={
            "patient_id": "metadata",
            "expression": "measurement",
        })

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        # Should keep because at least one column is measurement
        assert len(filtered) == 1
        assert filtered[0]["column_1_type"] == "metadata"
        assert filtered[0]["column_2_type"] == "measurement"

    def test_classification_annotation_added(self, tmp_path: Path):
        """Test that column type annotations are added to findings."""
        findings = [
            {
                "finding_id": "CSD-0001",
                "column_1": "expression",
                "column_2": "expression",
            },
        ]

        mock_client = _MockLLMClient(response={"expression": "measurement"})

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        assert len(filtered) == 1
        assert "column_1_type" in filtered[0]
        assert "column_2_type" in filtered[0]
        assert filtered[0]["column_1_type"] == "measurement"
        assert filtered[0]["column_2_type"] == "measurement"

    def test_mixed_findings_with_multiple_columns(self, tmp_path: Path):
        """Complex scenario: multiple findings with different column type combos."""
        findings = [
            # Both metadata -> filtered out
            {"finding_id": "F1", "column_1": "patient_id", "column_2": "sample_name"},
            # Both measurement -> kept
            {"finding_id": "F2", "column_1": "expression", "column_2": "count"},
            # Both index -> filtered out
            {"finding_id": "F3", "column_1": "row_number", "column_2": "index"},
            # Mixed: metadata + measurement -> kept
            {"finding_id": "F4", "column_1": "patient_id", "column_2": "ratio"},
            # Mixed: index + measurement -> kept
            {"finding_id": "F5", "column_1": "row_number", "column_2": "expression"},
        ]

        mock_client = _MockLLMClient(response={
            "patient_id": "metadata",
            "sample_name": "metadata",
            "expression": "measurement",
            "count": "measurement",
            "ratio": "measurement",
            "row_number": "index",
            "index": "index",
        })

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        # F1 and F3 filtered; F2, F4, F5 kept
        assert len(filtered) == 3
        kept_ids = {f["finding_id"] for f in filtered}
        assert kept_ids == {"F2", "F4", "F5"}

        # Verify annotations
        f2 = next(f for f in filtered if f["finding_id"] == "F2")
        assert f2["column_1_type"] == "measurement"
        assert f2["column_2_type"] == "measurement"

        f4 = next(f for f in filtered if f["finding_id"] == "F4")
        assert f4["column_1_type"] == "metadata"
        assert f4["column_2_type"] == "measurement"
