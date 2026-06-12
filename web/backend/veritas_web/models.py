from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


CASE_STATUSES = {
    "Draft",
    "Uploaded",
    "Planning",
    "Running",
    "Review Needed",
    "Report Ready",
    "Archived",
}

RUN_STATUSES = {"queued", "running", "completed", "failed", "interrupted"}

STALE_RUN_THRESHOLD_SECONDS = 300  # 5 minutes — no heartbeat → stale


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class CaseRecord:
    case_id: str
    paper_title: str = "Unknown until parsed"
    status: str = "Draft"
    technical_risk: str = "pending"
    review_needed_count: int = 0
    owner: str = "operator"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    latest_run_id: str | None = None
    input_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseRecord":
        return cls(**{field_name: data[field_name] for field_name in cls.__dataclass_fields__ if field_name in data})


@dataclass
class AuditRunRecord:
    run_id: str
    case_id: str
    status: str = "queued"
    agent_mode: str = "review"
    started_at: str | None = None
    completed_at: str | None = None
    summary: dict[str, Any] | None = None
    workdir: str | None = None
    final_html_report_url: str | None = None
    error: str | None = None
    last_event_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditRunRecord":
        return cls(**{field_name: data[field_name] for field_name in cls.__dataclass_fields__ if field_name in data})


@dataclass
class ArtifactRef:
    artifact_id: str
    kind: str
    label: str
    path: str
    url: str
    exists: bool
    size_bytes: int | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProgressEvent:
    timestamp: str
    event: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "event": self.event, **self.payload}


def normalize_case_status(status: str) -> str:
    if status not in CASE_STATUSES:
        raise ValueError(f"unsupported case status: {status}")
    return status


def normalize_run_status(status: str) -> str:
    if status not in RUN_STATUSES:
        raise ValueError(f"unsupported run status: {status}")
    return status
