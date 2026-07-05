"""EvidenceLocator: identifies a bounded region in a source data file.

The locator is a stable, reproducible pointer — not the data itself.
It captures enough information to rebuild the bounded window on demand
from the original file (which must still be available and hash-match).

Per PRD §3.3 "Evidence Bounded, Not Evidence Bulk".
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class EvidenceLocator:
    """Immutable pointer to a bounded region in a source data file.

    Attributes:
        source_path: Relative path to the source file (XLSX/CSV/TSV).
        source_sha256: SHA-256 hex digest of the source file.
        sheet: Sheet name (for XLSX) or empty string for CSV/TSV.
        rows: Row range as "start-end" (1-based, inclusive).
        cols: Column range as "start-end" (1-based) or "A-D" letter range.
        highlight_rows: Specific rows to highlight within the window.
        highlight_cols: Specific columns to highlight within the window.
        detector_id: Detector that produced this locator.
        signal_id: Canonical numeric signal ID this locator belongs to.
        extraction_method: How the data was extracted (e.g., "openpyxl", "pandas").
    """

    source_path: str
    source_sha256: str
    sheet: str
    rows: str
    cols: str
    highlight_rows: list[int] = field(default_factory=list)
    highlight_cols: list[str] = field(default_factory=list)
    detector_id: str = ""
    signal_id: str = ""
    extraction_method: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceLocator:
        """Deserialize from dictionary.

        Raises:
            ValueError: If required fields are missing.
        """
        required = {"source_path", "source_sha256", "sheet", "rows", "cols"}
        missing = required - set(data.keys())
        if missing:
            raise ValueError(f"EvidenceLocator missing required fields: {missing}")
        return cls(
            source_path=data["source_path"],
            source_sha256=data["source_sha256"],
            sheet=data["sheet"],
            rows=data["rows"],
            cols=data["cols"],
            highlight_rows=data.get("highlight_rows", []),
            highlight_cols=data.get("highlight_cols", []),
            detector_id=data.get("detector_id", ""),
            signal_id=data.get("signal_id", ""),
            extraction_method=data.get("extraction_method", ""),
        )

    def parse_row_range(self) -> tuple[int, int]:
        """Parse the rows field into (start, end) inclusive 1-based indices."""
        return _parse_range(self.rows)

    def parse_col_range(self) -> tuple[int, int] | tuple[str, str]:
        """Parse the cols field.

        Returns:
            If numeric ("2-4"): (2, 4)
            If letter ("A-D"): ("A", "D")
        """
        parts = self.cols.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid cols range format: {self.cols!r}, expected 'start-end'")
        start, end = parts[0].strip(), parts[1].strip()
        if start.isdigit() and end.isdigit():
            return (int(start), int(end))
        return (start, end)


def _parse_range(s: str) -> tuple[int, int]:
    """Parse a range string like '5-39' into (start, end) inclusive."""
    parts = s.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid range format: {s!r}, expected 'start-end'")
    start, end = int(parts[0].strip()), int(parts[1].strip())
    if start < 1:
        raise ValueError(f"Range start must be >= 1, got {start}")
    if end < start:
        raise ValueError(f"Range end must be >= start, got {end} < {start}")
    return (start, end)
