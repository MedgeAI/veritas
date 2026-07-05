"""EvidenceWindowManifest: the output artifact of the window builder.

Contains the bounded window data, metadata, and provenance for a single
evidence locator. Designed to be written as evidence_window_manifest.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class EvidenceWindowManifest:
    """Manifest for a single rebuilt evidence window.

    Attributes:
        schema_version: Manifest schema version for forward compatibility.
        signal_id: Canonical numeric signal ID this window belongs to.
        detector_id: Detector that produced the original signal.
        source_path: Relative path to the original source file.
        source_sha256: SHA-256 hex digest of the source file.
        sheet: Sheet name (for XLSX) or empty string for CSV/TSV.
        rows: Row range as "start-end" (1-based, inclusive).
        cols: Column range as "start-end" or "A-D".
        highlight_rows: Specific rows highlighted in the window.
        highlight_cols: Specific columns highlighted in the window.
        headers: Column headers for the window.
        data: Row data for the window (list of rows, each a list of cell values).
        rebuild_status: "ok", "failed", or "partial".
        failure_reason: If rebuild failed, why.
        extraction_method: How the data was extracted.
        metadata: Additional detector-specific metadata.
    """

    schema_version: str = "1.0"
    signal_id: str = ""
    detector_id: str = ""
    source_path: str = ""
    source_sha256: str = ""
    sheet: str = ""
    rows: str = ""
    cols: str = ""
    highlight_rows: list[int] = field(default_factory=list)
    highlight_cols: list[str] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    data: list[list[Any]] = field(default_factory=list)
    rebuild_status: str = "ok"
    failure_reason: str = ""
    extraction_method: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceWindowManifest:
        """Deserialize from dictionary."""
        return cls(
            schema_version=data.get("schema_version", "1.0"),
            signal_id=data.get("signal_id", ""),
            detector_id=data.get("detector_id", ""),
            source_path=data.get("source_path", ""),
            source_sha256=data.get("source_sha256", ""),
            sheet=data.get("sheet", ""),
            rows=data.get("rows", ""),
            cols=data.get("cols", ""),
            highlight_rows=data.get("highlight_rows", []),
            highlight_cols=data.get("highlight_cols", []),
            headers=data.get("headers", []),
            data=data.get("data", []),
            rebuild_status=data.get("rebuild_status", "ok"),
            failure_reason=data.get("failure_reason", ""),
            extraction_method=data.get("extraction_method", ""),
            metadata=data.get("metadata", {}),
        )
