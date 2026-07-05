"""Tests for Evidence Locator + Bounded Window Builder (WP6).

Uses synthetic CSV/XLSX fixtures to verify:
- Locator roundtrip (to_dict / from_dict)
- Window builder deterministic rebuild
- Fail-loud on missing file / hash mismatch
- Highlight rows/cols preserved
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from engine.static_audit.evidence_windows.locator import EvidenceLocator
from engine.static_audit.evidence_windows.manifest import EvidenceWindowManifest
from engine.static_audit.evidence_windows.window_builder import (
    EvidenceWindowError,
    build_window,
    build_window_from_locator,
    _letter_to_index,
)


# ---- Synthetic fixtures ----


def _make_csv(path: Path, rows: list[list[str]]) -> str:
    """Write a CSV file and return its SHA-256 hex digest."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture()
def synthetic_csv(tmp_path: Path) -> tuple[Path, str]:
    """Create a synthetic CSV file and return (path, sha256)."""
    rows = [
        ["sample_id", "treatment", "value_a", "value_b"],
        ["S001", "control", "10.5", "20.3"],
        ["S002", "control", "11.2", "21.1"],
        ["S003", "treated", "15.8", "25.4"],
        ["S004", "treated", "16.1", "26.0"],
        ["S005", "treated", "14.9", "24.8"],
    ]
    path = tmp_path / "source_data.csv"
    sha = _make_csv(path, rows)
    return path, sha


@pytest.fixture()
def synthetic_xlsx(tmp_path: Path) -> tuple[Path, str]:
    """Create a synthetic XLSX file and return (path, sha256)."""
    try:
        import openpyxl
    except ImportError:
        pytest.skip("openpyxl not installed")

    path = tmp_path / "source_data.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Source Data Fig.4"
    ws.append(["sample_id", "treatment", "value_a", "value_b"])
    ws.append(["S001", "control", 10.5, 20.3])
    ws.append(["S002", "control", 11.2, 21.1])
    ws.append(["S003", "treated", 15.8, 25.4])
    ws.append(["S004", "treated", 16.1, 26.0])
    ws.append(["S005", "treated", 14.9, 24.8])
    wb.save(path)

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return path, h.hexdigest()


# ---- Locator tests ----


class TestEvidenceLocator:
    def test_roundtrip(self) -> None:
        loc = EvidenceLocator(
            source_path="SourceData.xlsx",
            source_sha256="abc123",
            sheet="Sheet1",
            rows="2-6",
            cols="1-4",
            highlight_rows=[3, 4],
            highlight_cols=["B", "C"],
            detector_id="paperconan.constant_offset",
            signal_id="NUM-SIG-0001",
            extraction_method="openpyxl",
        )
        d = loc.to_dict()
        restored = EvidenceLocator.from_dict(d)
        assert restored == loc

    def test_from_dict_missing_required_raises(self) -> None:
        with pytest.raises(ValueError, match="missing required fields"):
            EvidenceLocator.from_dict({"source_path": "x.csv"})

    def test_parse_row_range(self) -> None:
        loc = EvidenceLocator(
            source_path="x.csv", source_sha256="h", sheet="",
            rows="5-39", cols="2-4",
        )
        assert loc.parse_row_range() == (5, 39)

    def test_parse_row_range_invalid(self) -> None:
        loc = EvidenceLocator(
            source_path="x.csv", source_sha256="h", sheet="",
            rows="abc", cols="2-4",
        )
        with pytest.raises(ValueError):
            loc.parse_row_range()

    def test_parse_col_range_numeric(self) -> None:
        loc = EvidenceLocator(
            source_path="x.csv", source_sha256="h", sheet="",
            rows="1-5", cols="2-4",
        )
        assert loc.parse_col_range() == (2, 4)

    def test_parse_col_range_letter(self) -> None:
        loc = EvidenceLocator(
            source_path="x.csv", source_sha256="h", sheet="",
            rows="1-5", cols="B-D",
        )
        assert loc.parse_col_range() == ("B", "D")

    def test_frozen(self) -> None:
        loc = EvidenceLocator(
            source_path="x.csv", source_sha256="h", sheet="",
            rows="1-5", cols="1-4",
        )
        with pytest.raises(AttributeError):
            loc.source_path = "other.csv"  # type: ignore[misc]


# ---- Window builder tests ----


class TestWindowBuilderCSV:
    def test_build_window_csv(self, tmp_path: Path, synthetic_csv: tuple[Path, str]) -> None:
        csv_path, sha = synthetic_csv
        locator = EvidenceLocator(
            source_path=csv_path.name,
            source_sha256=sha,
            sheet="",
            rows="2-4",
            cols="1-4",
            highlight_rows=[2, 3],
            highlight_cols=["C"],
            detector_id="test.constant_offset",
            signal_id="NUM-SIG-TEST",
        )
        manifest = build_window(tmp_path, locator)

        assert manifest.rebuild_status == "ok"
        assert manifest.signal_id == "NUM-SIG-TEST"
        assert manifest.source_sha256 == sha
        assert len(manifest.headers) == 4
        assert manifest.headers[0] == "sample_id"
        # Rows 2-4 means data rows at index 1,2,3 (0-based)
        assert len(manifest.data) == 3
        assert manifest.data[0][0] == "S001"

    def test_build_window_csv_col_subset(
        self, tmp_path: Path, synthetic_csv: tuple[Path, str]
    ) -> None:
        csv_path, sha = synthetic_csv
        locator = EvidenceLocator(
            source_path=csv_path.name,
            source_sha256=sha,
            sheet="",
            rows="2-4",
            cols="2-3",
        )
        manifest = build_window(tmp_path, locator)
        assert len(manifest.headers) == 2
        assert manifest.headers == ["treatment", "value_a"]

    def test_build_window_from_locator_dict(
        self, tmp_path: Path, synthetic_csv: tuple[Path, str]
    ) -> None:
        csv_path, sha = synthetic_csv
        locator_dict = {
            "source_path": csv_path.name,
            "source_sha256": sha,
            "sheet": "",
            "rows": "2-4",
            "cols": "1-4",
        }
        manifest = build_window_from_locator(tmp_path, locator_dict)
        assert manifest.rebuild_status == "ok"
        assert len(manifest.data) == 3

    def test_missing_file_fails_loud(self, tmp_path: Path) -> None:
        locator = EvidenceLocator(
            source_path="nonexistent.csv",
            source_sha256="abc",
            sheet="",
            rows="1-5",
            cols="1-4",
        )
        with pytest.raises(EvidenceWindowError, match="Source file not found"):
            build_window(tmp_path, locator)

    def test_hash_mismatch_fails_loud(
        self, tmp_path: Path, synthetic_csv: tuple[Path, str]
    ) -> None:
        csv_path, _ = synthetic_csv
        locator = EvidenceLocator(
            source_path=csv_path.name,
            source_sha256="wrong_hash",
            sheet="",
            rows="1-5",
            cols="1-4",
        )
        with pytest.raises(EvidenceWindowError, match="hash mismatch"):
            build_window(tmp_path, locator)

    def test_deterministic_rebuild(
        self, tmp_path: Path, synthetic_csv: tuple[Path, str]
    ) -> None:
        """Same locator + same source -> same window (stability requirement)."""
        csv_path, sha = synthetic_csv
        locator = EvidenceLocator(
            source_path=csv_path.name,
            source_sha256=sha,
            sheet="",
            rows="2-6",
            cols="1-4",
        )
        m1 = build_window(tmp_path, locator)
        m2 = build_window(tmp_path, locator)
        assert m1.data == m2.data
        assert m1.headers == m2.headers
        assert m1.to_dict() == m2.to_dict()

    def test_unsupported_file_type(self, tmp_path: Path) -> None:
        bad = tmp_path / "data.json"
        bad.write_text("{}")
        sha = hashlib.sha256(bad.read_bytes()).hexdigest()
        locator = EvidenceLocator(
            source_path="data.json",
            source_sha256=sha,
            sheet="",
            rows="1-5",
            cols="1-4",
        )
        with pytest.raises(EvidenceWindowError, match="Unsupported"):
            build_window(tmp_path, locator)


class TestWindowBuilderXLSX:
    def test_build_window_xlsx(
        self, tmp_path: Path, synthetic_xlsx: tuple[Path, str]
    ) -> None:
        xlsx_path, sha = synthetic_xlsx
        locator = EvidenceLocator(
            source_path=xlsx_path.name,
            source_sha256=sha,
            sheet="Source Data Fig.4",
            rows="2-4",
            cols="1-4",
            highlight_rows=[2],
            highlight_cols=["C"],
        )
        manifest = build_window(tmp_path, locator)
        assert manifest.rebuild_status == "ok"
        assert manifest.sheet == "Source Data Fig.4"
        assert len(manifest.data) == 3
        # First data row
        assert manifest.data[0][0] == "S001"

    def test_xlsx_wrong_sheet_raises(
        self, tmp_path: Path, synthetic_xlsx: tuple[Path, str]
    ) -> None:
        xlsx_path, sha = synthetic_xlsx
        locator = EvidenceLocator(
            source_path=xlsx_path.name,
            source_sha256=sha,
            sheet="NonexistentSheet",
            rows="2-4",
            cols="1-4",
        )
        with pytest.raises(EvidenceWindowError, match="not found"):
            build_window(tmp_path, locator)


class TestLetterToIndex:
    def test_single_letter(self) -> None:
        assert _letter_to_index("A") == 1
        assert _letter_to_index("Z") == 26

    def test_double_letter(self) -> None:
        assert _letter_to_index("AA") == 27
        assert _letter_to_index("AB") == 28


# ---- Manifest tests ----


class TestEvidenceWindowManifest:
    def test_roundtrip(self) -> None:
        m = EvidenceWindowManifest(
            signal_id="NUM-SIG-0001",
            detector_id="test.detector",
            source_path="x.csv",
            source_sha256="abc",
            sheet="",
            rows="1-5",
            cols="1-3",
            headers=["a", "b", "c"],
            data=[["1", "2", "3"]],
            rebuild_status="ok",
        )
        d = m.to_dict()
        restored = EvidenceWindowManifest.from_dict(d)
        assert restored.signal_id == m.signal_id
        assert restored.data == m.data
        assert restored.headers == m.headers

    def test_manifest_to_json(self, tmp_path: Path) -> None:
        m = EvidenceWindowManifest(
            signal_id="NUM-SIG-0001",
            source_path="x.csv",
            source_sha256="abc",
            rows="1-5",
            cols="1-3",
        )
        # Should be JSON-serializable
        json_str = json.dumps(m.to_dict())
        assert "NUM-SIG-0001" in json_str
