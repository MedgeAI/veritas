"""Unit tests for cross-sheet LLM metadata column filter.

Tests classify_columns_with_llm and run_cross_sheet_filter from engine.static_audit._shared.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import Mock

from engine.static_audit._shared import (
    classify_columns_with_llm,
    run_cross_sheet_filter,
)


class MockLLMClient:
    """Mock LLM client for testing."""

    def __init__(self, response: dict | None = None, raise_error: bool = False):
        self.response = response or {}
        self.raise_error = raise_error

    def chat_json(self, prompt: str, **kwargs) -> dict:
        if self.raise_error:
            raise RuntimeError("LLM API failure")
        return self.response


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
        mock_client = MockLLMClient(response={
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
        mock_client = MockLLMClient(response={
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

    def test_index_classification(self):
        """Test that index columns are correctly classified."""
        column_names = ["row_number", "index", "#"]
        sample_values = {
            "row_number": [1, 2, 3],
            "index": [0, 1, 2],
            "#": [1, 2, 3],
        }
        mock_client = MockLLMClient(response={
            "row_number": "index",
            "index": "index",
            "#": "index",
        })

        result = classify_columns_with_llm(column_names, sample_values, mock_client)

        assert result == {
            "row_number": "index",
            "index": "index",
            "#": "index",
        }

    def test_mixed_classification(self):
        """Test mixed column types in one call."""
        column_names = ["patient_id", "expression", "row_number"]
        sample_values = {
            "patient_id": ["P001", "P002"],
            "expression": [1.5, 2.3],
            "row_number": [1, 2],
        }
        mock_client = MockLLMClient(response={
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
        mock_client = MockLLMClient(raise_error=True)

        result = classify_columns_with_llm(column_names, sample_values, mock_client)

        assert result == {}

    def test_empty_column_list(self):
        """Test with empty column list."""
        mock_client = MockLLMClient(response={})

        result = classify_columns_with_llm([], {}, mock_client)

        assert result == {}

    def test_case_normalization(self):
        """Test that classification values are normalized to lowercase."""
        column_names = ["patient_id"]
        sample_values = {"patient_id": ["P001"]}
        mock_client = MockLLMClient(response={"patient_id": "METADATA"})

        result = classify_columns_with_llm(column_names, sample_values, mock_client)

        assert result == {"patient_id": "metadata"}


class TestRunCrossSheetFilter:
    """Tests for run_cross_sheet_filter function."""

    def test_filter_metadata_findings(self, tmp_path):
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

        mock_client = MockLLMClient(response={
            "patient_id": "metadata",
            "expression": "measurement",
        })

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        assert len(filtered) == 1
        assert filtered[0]["finding_id"] == "CSD-0002"
        assert filtered[0]["column_1_type"] == "measurement"
        assert filtered[0]["column_2_type"] == "measurement"

    def test_filter_index_findings(self, tmp_path):
        """Test that index column findings are filtered out."""
        findings = [
            {
                "finding_id": "CSD-0001",
                "column_1": "row_number",
                "column_2": "row_number",
            },
        ]

        mock_client = MockLLMClient(response={"row_number": "index"})

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        assert len(filtered) == 0

    def test_keep_measurement_findings(self, tmp_path):
        """Test that measurement column findings are kept."""
        findings = [
            {
                "finding_id": "CSD-0001",
                "column_1": "expression",
                "column_2": "count",
            },
        ]

        mock_client = MockLLMClient(response={
            "expression": "measurement",
            "count": "measurement",
        })

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        assert len(filtered) == 1
        assert filtered[0]["finding_id"] == "CSD-0001"

    def test_llm_failure_conservative_fallback(self, tmp_path):
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

        mock_client = MockLLMClient(raise_error=True)

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        # All findings should be kept (conservative fallback)
        assert len(filtered) == 2

    def test_empty_findings_list(self, tmp_path):
        """Test with empty findings list."""
        mock_client = MockLLMClient(response={})

        filtered = run_cross_sheet_filter(tmp_path, [], mock_client)

        assert filtered == []

    def test_mixed_column_types_in_one_finding(self, tmp_path):
        """Test finding with one metadata and one measurement column."""
        findings = [
            {
                "finding_id": "CSD-0001",
                "column_1": "patient_id",  # metadata
                "column_2": "expression",  # measurement
            },
        ]

        mock_client = MockLLMClient(response={
            "patient_id": "metadata",
            "expression": "measurement",
        })

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        # Should keep because at least one column is measurement
        assert len(filtered) == 1
        assert filtered[0]["column_1_type"] == "metadata"
        assert filtered[0]["column_2_type"] == "measurement"

    def test_classification_annotation_added(self, tmp_path):
        """Test that column type annotations are added to findings."""
        findings = [
            {
                "finding_id": "CSD-0001",
                "column_1": "expression",
                "column_2": "expression",
            },
        ]

        mock_client = MockLLMClient(response={"expression": "measurement"})

        filtered = run_cross_sheet_filter(tmp_path, findings, mock_client)

        assert len(filtered) == 1
        assert "column_1_type" in filtered[0]
        assert "column_2_type" in filtered[0]
        assert filtered[0]["column_1_type"] == "measurement"
        assert filtered[0]["column_2_type"] == "measurement"
