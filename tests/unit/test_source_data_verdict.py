"""Tests for source_data_verdict — LLM verdict adjudication module.

These tests validate the deterministic logic (XLSX reading, grouping,
schema validation) WITHOUT calling the LLM.  LLM integration is
covered by integration tests that require opencode to be available.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.static_audit.paths import resolve_artifact_path
from engine.static_audit.tools.source_data_verdict import (
    _build_sheet_context,
    _group_findings_by_sheet,
    _safe_value,
    _validate_verdict_output,
    read_xlsx_column_context,
    run_source_data_verdict,
)


# ── _safe_value ──────────────────────────────────────────────────────


class TestSafeValue:
    def test_none(self):
        assert _safe_value(None) is None

    def test_int(self):
        assert _safe_value(42) == 42

    def test_float(self):
        assert _safe_value(3.14) == 3.14

    def test_bool(self):
        assert _safe_value(True) is True

    def test_short_string(self):
        assert _safe_value("hello") == "hello"

    def test_long_string_truncated(self):
        long = "a" * 100
        result = _safe_value(long, max_len=10)
        assert len(result) == 10


# ── _group_findings_by_sheet ─────────────────────────────────────────


class TestGroupFindings:
    def test_empty(self):
        assert _group_findings_by_sheet(None, None) == {}

    def test_findings_only(self):
        data = {
            "findings": [
                {"finding_id": "DC-0001", "workbook": "a.xlsx", "sheet": "S1"},
                {"finding_id": "FR-0001", "workbook": "a.xlsx", "sheet": "S1"},
                {"finding_id": "FR-0002", "workbook": "b.xlsx", "sheet": "S2"},
            ]
        }
        g = _group_findings_by_sheet(data, None)
        assert len(g) == 2
        assert len(g[("a.xlsx", "S1")]) == 2
        assert len(g[("b.xlsx", "S2")]) == 1

    def test_pair_forensics_only(self):
        data = {
            "findings": [
                {"finding_id": "PRR-0001", "workbook": "a.xlsx", "sheet": "S1"},
            ]
        }
        g = _group_findings_by_sheet(None, data)
        assert len(g) == 1
        assert len(g[("a.xlsx", "S1")]) == 1

    def test_merged(self):
        findings = {
            "findings": [
                {"finding_id": "DC-0001", "workbook": "a.xlsx", "sheet": "S1"},
            ]
        }
        pair = {
            "findings": [
                {"finding_id": "PRR-0001", "workbook": "a.xlsx", "sheet": "S1"},
            ]
        }
        g = _group_findings_by_sheet(findings, pair)
        assert len(g[("a.xlsx", "S1")]) == 2

    def test_missing_workbook_or_sheet_skipped(self):
        data = {
            "findings": [
                {"finding_id": "X", "workbook": "", "sheet": "S1"},
                {"finding_id": "Y", "workbook": "a.xlsx", "sheet": ""},
                {"finding_id": "Z", "workbook": "a.xlsx", "sheet": "S1"},
            ]
        }
        g = _group_findings_by_sheet(data, None)
        assert len(g) == 1
        assert len(g[("a.xlsx", "S1")]) == 1


# ── _validate_verdict_output ─────────────────────────────────────────


class TestValidateVerdictOutput:
    def test_valid(self):
        data = {
            "sheet_verdict": "mostly_false_positive",
            "sheet_pattern": "descriptive_statistics_table",
            "findings": [
                {"id": "FR-0001", "verdict": "false_positive", "confidence": 0.95},
            ],
        }
        result = _validate_verdict_output(data)
        assert result["sheet_verdict"] == "mostly_false_positive"

    def test_not_dict(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            _validate_verdict_output([])

    def test_missing_sheet_verdict(self):
        with pytest.raises(ValueError, match="missing 'sheet_verdict'"):
            _validate_verdict_output({"findings": []})

    def test_invalid_sheet_verdict(self):
        with pytest.raises(ValueError, match="invalid sheet_verdict"):
            _validate_verdict_output({"sheet_verdict": "bogus", "findings": []})

    def test_missing_findings(self):
        with pytest.raises(ValueError, match="missing 'findings'"):
            _validate_verdict_output({"sheet_verdict": "mixed"})

    def test_findings_not_list(self):
        with pytest.raises(ValueError, match="not a list"):
            _validate_verdict_output({"sheet_verdict": "mixed", "findings": "oops"})

    def test_finding_not_dict(self):
        with pytest.raises(ValueError, match="not an object"):
            _validate_verdict_output(
                {
                    "sheet_verdict": "mixed",
                    "findings": ["oops"],
                }
            )

    def test_finding_missing_id(self):
        with pytest.raises(ValueError, match="missing 'id'"):
            _validate_verdict_output(
                {
                    "sheet_verdict": "mixed",
                    "findings": [{"verdict": "uncertain"}],
                }
            )

    def test_invalid_finding_verdict(self):
        with pytest.raises(ValueError, match="invalid verdict"):
            _validate_verdict_output(
                {
                    "sheet_verdict": "mixed",
                    "findings": [{"id": "X", "verdict": "bogus"}],
                }
            )

    def test_all_three_verdicts_accepted(self):
        for v in ("true_positive", "false_positive", "uncertain"):
            _validate_verdict_output(
                {
                    "sheet_verdict": "mixed",
                    "findings": [{"id": "X", "verdict": v}],
                }
            )


# ── run_source_data_verdict ───────────────────────────────────────────


def _write_json_artifact(workdir: Path, artifact_name: str, data: dict) -> Path:
    path = resolve_artifact_path(workdir, artifact_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _write_verdict_xlsx(path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S1"
    ws.append(["Descriptive Statistics", None, None])
    ws.append(["N total", "Mean", "Sum"])
    ws.append([10, 2.0, 20.0])
    ws.append([10, 3.0, 30.0])
    ws.append([10, 4.0, 40.0])

    ws2 = wb.create_sheet("S2")
    ws2.append(["Group", "Value"])
    ws2.append(["A", 1.0])
    ws2.append(["B", 1.1])
    wb.save(path)


def test_run_source_data_verdict_writes_summary_and_artifact(
    tmp_path, monkeypatch
) -> None:
    workdir = tmp_path / "work"
    source_dir = tmp_path / "Source Data"
    source_dir.mkdir()
    _write_verdict_xlsx(source_dir / "source.xlsx")

    _write_json_artifact(
        workdir,
        "source_data_findings.json",
        {
            "findings": [
                {
                    "finding_id": "FR-0001",
                    "category": "fixed_ratio",
                    "risk_level": "medium",
                    "workbook": "source.xlsx",
                    "sheet": "S1",
                    "column_pair": ["B", "C"],
                    "relationship_value": "0.1",
                    "support_rate": 1.0,
                },
                {
                    "finding_id": "DC-0001",
                    "category": "duplicate_numeric_columns",
                    "risk_level": "high",
                    "workbook": "source.xlsx",
                    "sheet": "S1",
                    "column_pair": ["D", "E"],
                    "support_rate": 1.0,
                },
            ]
        },
    )
    _write_json_artifact(
        workdir,
        "source_data_pair_forensics.json",
        {
            "findings": [
                {
                    "finding_id": "PRR-0001",
                    "category": "paired_ratio_reuse",
                    "risk_level": "medium",
                    "workbook": "source.xlsx",
                    "sheet": "S2",
                    "column_pair": ["A", "B"],
                    "support_rate": 1.0,
                }
            ]
        },
    )
    _write_json_artifact(
        workdir,
        "source_data_profile.json",
        {
            "workbooks": [
                {
                    "file_name": "source.xlsx",
                    "sheets": [
                        {"name": "S1", "cell_count": 15, "numeric_cell_count": 9},
                        {"name": "S2", "cell_count": 4, "numeric_cell_count": 2},
                    ],
                }
            ]
        },
    )

    seen_contexts: list[dict] = []

    def fake_get_sheet_verdict(sheet_context, **_kwargs):
        seen_contexts.append(sheet_context)
        if sheet_context["sheet"] == "S1":
            return {
                "sheet_verdict": "mixed",
                "sheet_pattern": "descriptive_statistics_table",
                "findings": [
                    {"id": "FR-0001", "verdict": "false_positive", "confidence": 0.94},
                    {"id": "DC-0001", "verdict": "true_positive", "confidence": 0.88},
                ],
            }
        return {
            "sheet_verdict": "mostly_uncertain",
            "sheet_pattern": "measurement_data",
            "findings": [
                {"id": "PRR-0001", "verdict": "uncertain", "confidence": 0.5},
            ],
        }

    monkeypatch.setattr(
        "engine.static_audit.tools.source_data_verdict.get_sheet_verdict",
        fake_get_sheet_verdict,
    )

    result = run_source_data_verdict(
        workdir,
        source_data_dir=source_dir,
        project_root=tmp_path,
        env={},
        model="test-model",
        max_workers=1,
    )

    assert result["summary"] == {
        "total_sheets": 2,
        "total_findings": 3,
        "true_positive": 1,
        "false_positive": 1,
        "uncertain": 1,
        "failed_sheets": 0,
    }
    output_path = resolve_artifact_path(workdir, "source_data_findings_verdict.json")
    assert output_path.exists()
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["model"] == "test-model"
    assert [sheet["sheet"] for sheet in persisted["sheets"]] == ["S1", "S2"]
    s1_context = next(ctx for ctx in seen_contexts if ctx["sheet"] == "S1")
    assert s1_context["columns"] is not None
    assert [finding["id"] for finding in s1_context["findings"]] == [
        "FR-0001",
        "DC-0001",
    ]


def test_run_source_data_verdict_keeps_findings_uncertain_when_sheet_call_fails(
    tmp_path, monkeypatch
) -> None:
    workdir = tmp_path / "work"
    source_dir = tmp_path / "Source Data"
    source_dir.mkdir()
    _write_verdict_xlsx(source_dir / "source.xlsx")

    _write_json_artifact(
        workdir,
        "source_data_findings.json",
        {
            "findings": [
                {
                    "finding_id": "F-OK",
                    "category": "fixed_ratio",
                    "risk_level": "medium",
                    "workbook": "source.xlsx",
                    "sheet": "S1",
                },
                {
                    "finding_id": "F-FAIL",
                    "category": "fixed_ratio",
                    "risk_level": "medium",
                    "workbook": "source.xlsx",
                    "sheet": "S2",
                },
            ]
        },
    )

    def fake_get_sheet_verdict(sheet_context, **_kwargs):
        if sheet_context["sheet"] == "S2":
            raise RuntimeError("opencode unavailable")
        return {
            "sheet_verdict": "mostly_uncertain",
            "sheet_pattern": "measurement_data",
            "findings": [{"id": "F-OK", "verdict": "true_positive", "confidence": 0.8}],
        }

    monkeypatch.setattr(
        "engine.static_audit.tools.source_data_verdict.get_sheet_verdict",
        fake_get_sheet_verdict,
    )

    result = run_source_data_verdict(
        workdir,
        source_data_dir=source_dir,
        project_root=tmp_path,
        env={},
        max_workers=2,
    )

    assert result["summary"]["failed_sheets"] == 1
    assert result["summary"]["true_positive"] == 1
    assert result["summary"]["uncertain"] == 1
    failed_sheet = next(sheet for sheet in result["sheets"] if sheet["sheet"] == "S2")
    assert failed_sheet["verdict_status"] == "failed"
    assert failed_sheet["findings"] == [
        {
            "id": "F-FAIL",
            "verdict": "uncertain",
            "confidence": 0.0,
            "explanation": "LLM verdict unavailable",
        }
    ]


# ── read_xlsx_column_context ─────────────────────────────────────────


class TestReadXlsxContext:
    """Test XLSX reading with real paper3 data."""

    PAPER3_SD = Path("/mnt/disk1/LZJ/project/veritas/input/paper3/Source Data")
    MOESM13 = "41586_2025_8943_MOESM13_ESM.xlsx"

    @pytest.fixture(autouse=True)
    def _skip_if_no_data(self):
        if not self.PAPER3_SD.exists():
            pytest.skip("paper3 Source Data not available")

    def test_reads_descriptive_stats_sheet(self):
        ctx = read_xlsx_column_context(
            self.PAPER3_SD / self.MOESM13,
            "Extended Data Fig. 3d",
        )
        assert ctx is not None
        assert ctx["num_columns"] == 10
        assert ctx["header_row_count"] > 0
        assert ctx["data_start_row"] > 0

    def test_column_hierarchy_matches_findings_labels(self):
        """Column hierarchy for col 4 (Mean) should include 'Mean' and
        'Descriptive Statistics' — matching the column_labels in findings."""
        ctx = read_xlsx_column_context(
            self.PAPER3_SD / self.MOESM13,
            "Extended Data Fig. 3d",
        )
        assert ctx is not None
        col4 = ctx["columns"][4]
        assert "Mean" in col4["header_hierarchy"]
        assert "Descriptive Statistics" in col4["header_hierarchy"]

    def test_sample_values_are_numeric(self):
        ctx = read_xlsx_column_context(
            self.PAPER3_SD / self.MOESM13,
            "Extended Data Fig. 3d",
        )
        assert ctx is not None
        # Col 4 (Mean) should have numeric samples
        samples = ctx["columns"][4]["sample_values"]
        assert len(samples) > 0
        assert all(isinstance(v, (int, float)) for v in samples if v is not None)

    def test_nonexistent_sheet_returns_none(self):
        ctx = read_xlsx_column_context(
            self.PAPER3_SD / self.MOESM13,
            "Nonexistent Sheet",
        )
        assert ctx is None

    def test_nonexistent_file_returns_none(self):
        ctx = read_xlsx_column_context(
            self.PAPER3_SD / "nonexistent.xlsx",
            "Sheet1",
        )
        assert ctx is None


# ── _build_sheet_context ─────────────────────────────────────────────


class TestBuildSheetContext:
    PAPER3_SD = Path("/mnt/disk1/LZJ/project/veritas/input/paper3/Source Data")
    PAPER3_OUT = Path(
        "/mnt/disk1/LZJ/project/veritas/outputs/paper3/research-integrity-audit"
    )

    @pytest.fixture(autouse=True)
    def _skip_if_no_data(self):
        if not self.PAPER3_SD.exists() or not self.PAPER3_OUT.exists():
            pytest.skip("paper3 data not available")

    def test_builds_context_with_xlsx_and_profile(self):
        findings_path = self.PAPER3_OUT / "source_data" / "findings.json"
        pair_path = self.PAPER3_OUT / "source_data" / "pair_forensics.json"
        profile_path = self.PAPER3_OUT / "source_data" / "profile.json"

        findings_data = json.loads(findings_path.read_text())
        pair_data = json.loads(pair_path.read_text())
        profile = json.loads(profile_path.read_text())

        grouped = _group_findings_by_sheet(findings_data, pair_data)
        key = ("41586_2025_8943_MOESM13_ESM.xlsx", "Extended Data Fig. 3d")
        assert key in grouped

        ctx = _build_sheet_context(
            key[0], key[1], grouped[key], self.PAPER3_SD, profile
        )

        assert ctx["workbook"] == key[0]
        assert ctx["sheet"] == key[1]
        assert ctx["columns"] is not None
        assert len(ctx["findings"]) == len(grouped[key])
        assert ctx["profile"] is not None

    def test_context_without_xlsx(self):
        """When XLSX path doesn't exist, columns should be None."""
        ctx = _build_sheet_context(
            "nonexistent.xlsx",
            "Sheet1",
            [
                {
                    "finding_id": "X",
                    "category": "fixed_ratio",
                    "workbook": "nonexistent.xlsx",
                    "sheet": "Sheet1",
                }
            ],
            Path("/tmp"),
            None,
        )
        assert ctx["columns"] is None
        assert len(ctx["findings"]) == 1
