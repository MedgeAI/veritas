"""Investigation round models and utilities.

This module contains models for investigation rounds and utilities for
managing investigation records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.shared.helpers import EXPECTED_EVIDENCE_TYPES, normalize_expected_evidence_type
from engine.shared.types import InvestigationAction
from engine.static_audit.models import utc_now_iso

INVESTIGATION_ROUNDS_FILENAME = "investigation_rounds.jsonl"

# Re-export for backward compatibility
__all__ = [
    "InvestigationAction",
    "InvestigationRecord",
    "EXPECTED_EVIDENCE_TYPES",
    "INVESTIGATION_ROUNDS_FILENAME",
    "investigation_rounds_path",
    "append_investigation_record",
    "read_investigation_records",
    "normalize_expected_evidence_type",
]

# Re-export InvestigationAction for backward compatibility
__all__ = [
    "InvestigationAction",
    "InvestigationRecord",
    "EXPECTED_EVIDENCE_TYPES",
    "INVESTIGATION_ROUNDS_FILENAME",
    "investigation_rounds_path",
    "append_investigation_record",
    "read_investigation_records",
    "normalize_expected_evidence_type",
]


@dataclass
class InvestigationRecord:
    round_id: int
    action_id: str
    tool_id: str
    status: str
    hypothesis: str = ""
    expected_evidence_type: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    depends_on_artifacts: list[str] = field(default_factory=list)
    validation_status: str = "not_validated"
    output_artifacts: list[str] = field(default_factory=list)
    detail: str = ""
    command: list[str] | None = None
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "created_at": self.created_at,
            "round_id": self.round_id,
            "action_id": self.action_id,
            "tool_id": self.tool_id,
            "status": self.status,
            "validation_status": self.validation_status,
            "hypothesis": self.hypothesis,
            "expected_evidence_type": self.expected_evidence_type,
            "params": self.params,
            "depends_on_artifacts": self.depends_on_artifacts,
            "output_artifacts": self.output_artifacts,
            "detail": self.detail,
            "command": self.command or [],
            "metadata": self.metadata,
        }


def investigation_rounds_path(workdir: Path) -> Path:
    """Return the path to investigation_rounds.jsonl in the investigation subdirectory."""
    return workdir / "investigation" / INVESTIGATION_ROUNDS_FILENAME


def append_investigation_record(workdir: Path, record: InvestigationRecord) -> None:
    path = investigation_rounds_path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def read_investigation_records(workdir: Path) -> list[dict[str, Any]]:
    path = investigation_rounds_path(workdir)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records
