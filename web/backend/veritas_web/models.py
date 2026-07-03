"""SQLAlchemy ORM models, legacy dataclasses, and Pydantic schemas.

This module is the single source of truth for the Veritas web data model.

* ``CaseModel``, ``RunModel``, ``RunEventModel``, etc. — SQLAlchemy ORM
  classes backed by PostgreSQL.
* ``CaseRecord``, ``AuditRunRecord``, ``ArtifactRef``, ``ProgressEvent`` —
  legacy dataclasses kept for backward compatibility with code that has not
  yet migrated to the SQL layer (CLI orchestrator, existing tests).  They
  will be removed once all consumers use the ORM models.
* ``*Create``, ``*Read``, ``*Update`` — Pydantic schemas for FastAPI
  request/response validation.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator

from .database import Base

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CASE_STATUSES: set[str] = {
    "Draft",
    "Uploaded",
    "Planning",
    "Running",
    "Review Needed",
    "Report Ready",
    "Cancelled",
    "Archived",
}

RUN_STATUSES: set[str] = {
    "queued",
    "running",
    "completed",
    "failed",
    "interrupted",
    "cancelled",
    "partial_available",
    "enhancing",
    "completed_with_warnings",
    "failed_timeout",
    "failed_dependency",
    "failed_runtime",
}

TECHNICAL_RISK_LEVELS: set[str] = {
    "pending",
    "unknown",
    "info",
    "low",
    "medium",
    "high",
    "critical",
}

REVIEW_DECISION_STATUSES: set[str] = {
    "open",
    "resolved",
    "dismissed",
    "needs_author_response",
}

INVESTIGATION_STATUSES: set[str] = {
    "queued",
    "running",
    "completed",
    "failed",
    "skipped",
    "cancelled",
}

VALIDATION_STATUSES: set[str] = {
    "not_validated",
    "valid",
    "invalid",
    "warning",
    "failed",
}

FINDING_STATUSES: set[str] = {
    "open",
    "review_needed",
    "resolved",
    "dismissed",
    "suppressed",
}

RISK_LEVELS: set[str] = {
    "info",
    "low",
    "medium",
    "high",
    "critical",
}

RUN_DIAGNOSTICS_STATUSES: set[str] = {
    "ok",
    "completed",
    "completed_with_warnings",
    "needs_attention",
    "failed",
}

STALE_RUN_THRESHOLD_SECONDS = 300  # 5 minutes — no heartbeat → stale

# Reproducibility tiers determine the maximum certification grade a case can receive.
REPRODUCIBILITY_TIERS: dict[str, str] = {
    "full": "A",
    "partial": "B",
    "code_only": "C",
    "static": "C-",
}

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _sql_values(values: set[str]) -> str:
    return ", ".join(f"'{value}'" for value in sorted(values))


class UTCDateTime(TypeDecorator[datetime]):
    """PostgreSQL timestamptz that accepts legacy ISO string inputs."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            raw = value.strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
        else:
            raise TypeError(f"unsupported datetime value: {type(value).__name__}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def process_result_value(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return self.process_bind_param(value, dialect)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string with ``Z`` suffix."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def utc_now_datetime() -> datetime:
    """Return the current UTC time for PostgreSQL timestamptz columns."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_iso_timestamp(value: Any) -> str:
    """Serialise DB timestamp values to the legacy ISO-8601 ``Z`` format."""
    if value is None:
        return utc_now()
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (
            dt.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    return str(value)


def normalize_case_status(status: str) -> str:
    if status not in CASE_STATUSES:
        raise ValueError(f"invalid case status: {status!r}")
    return status


def normalize_run_status(status: str) -> str:
    if status not in RUN_STATUSES:
        raise ValueError(f"invalid run status: {status!r}")
    return status


def safe_id(value: str) -> str:
    """Sanitise *value* for use as a filesystem-safe identifier."""
    cleaned = SAFE_NAME_RE.sub("-", value).strip("-")[:120]
    return cleaned or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


# ===================================================================
# Legacy dataclasses (backward compat — will be removed after full SQL migration)
# ===================================================================


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
    reproducibility_tier: str = "full"
    paper_pdf: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseRecord":
        return cls(
            **{
                field_name: data[field_name]
                for field_name in cls.__dataclass_fields__
                if field_name in data
            }
        )

    @classmethod
    def from_model(cls, model: CaseModel) -> "CaseRecord":  # type: ignore[name-defined]  # forward ref
        return cls(
            case_id=model.case_id,
            paper_title=model.paper_title or "Unknown until parsed",
            status=model.status or "Draft",
            technical_risk=model.technical_risk or "pending",
            review_needed_count=model.review_needed_count or 0,
            owner=model.owner or "operator",
            created_at=to_iso_timestamp(model.created_at),
            updated_at=to_iso_timestamp(model.updated_at),
            latest_run_id=model.latest_run_id,
            input_count=model.input_count or 0,
            reproducibility_tier=model.reproducibility_tier or "full",
            paper_pdf=model.paper_pdf,
        )


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
        return cls(
            **{
                field_name: data[field_name]
                for field_name in cls.__dataclass_fields__
                if field_name in data
            }
        )

    @classmethod
    def from_model(cls, model: RunModel) -> "AuditRunRecord":  # type: ignore[name-defined]
        return cls(
            run_id=model.run_id,
            case_id=model.case_id,
            status=model.status or "queued",
            agent_mode=model.agent_mode or "review",
            started_at=to_iso_timestamp(model.started_at) if model.started_at else None,
            completed_at=to_iso_timestamp(model.completed_at)
            if model.completed_at
            else None,
            summary=model.summary,
            workdir=model.workdir,
            final_html_report_url=model.final_html_report_url,
            error=model.error,
            last_event_at=to_iso_timestamp(model.last_event_at)
            if model.last_event_at
            else None,
        )


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


# ===================================================================
# SQLAlchemy ORM models
# ===================================================================


class CaseModel(Base):
    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_values(CASE_STATUSES)})",
            name="ck_cases_status",
        ),
        CheckConstraint(
            f"technical_risk IN ({_sql_values(TECHNICAL_RISK_LEVELS)})",
            name="ck_cases_technical_risk",
        ),
        CheckConstraint(
            f"reproducibility_tier IN ({_sql_values(set(REPRODUCIBILITY_TIERS))})",
            name="ck_cases_reproducibility_tier",
        ),
        CheckConstraint("review_needed_count >= 0", name="ck_cases_review_count"),
        CheckConstraint("input_count >= 0", name="ck_cases_input_count"),
        Index("ix_cases_owner_created_at", "owner", "created_at"),
        Index("ix_cases_status", "status"),
        Index("ix_cases_latest_run_id", "latest_run_id"),
    )

    case_id = Column(String(128), primary_key=True)
    paper_title = Column(Text, default="Unknown until parsed", nullable=False)
    status = Column(String(32), default="Draft", nullable=False)
    technical_risk = Column(String(32), default="pending", nullable=False)
    review_needed_count = Column(Integer, default=0, nullable=False)
    owner = Column(String(320), default="operator", nullable=False)
    created_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)
    updated_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)
    latest_run_id = Column(
        String(128),
        ForeignKey(
            "runs.run_id",
            name="fk_cases_latest_run_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    input_count = Column(Integer, default=0, nullable=False)
    reproducibility_tier = Column(String(32), default="full", nullable=False)
    paper_pdf = Column(String(512), nullable=True)

    runs = relationship(
        "RunModel",
        back_populates="case",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="RunModel.case_id",
    )
    latest_run = relationship(
        "RunModel",
        foreign_keys=[latest_run_id],
        post_update=True,
        lazy="joined",
    )
    review_decisions = relationship(
        "ReviewDecisionModel",
        back_populates="case",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    investigation_records = relationship(
        "InvestigationRecordModel",
        back_populates="case",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    artifacts = relationship(
        "ArtifactModel",
        back_populates="case",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    findings = relationship(
        "FindingModel",
        back_populates="case",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "paper_title": self.paper_title,
            "status": self.status,
            "technical_risk": self.technical_risk,
            "review_needed_count": self.review_needed_count,
            "owner": self.owner,
            "created_at": to_iso_timestamp(self.created_at),
            "updated_at": to_iso_timestamp(self.updated_at),
            "latest_run_id": self.latest_run_id,
            "input_count": self.input_count,
            "reproducibility_tier": self.reproducibility_tier or "full",
        }


class RunModel(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_values(RUN_STATUSES)})",
            name="ck_runs_status",
        ),
        Index("ix_runs_case_created_at", "case_id", "created_at"),
        Index("ix_runs_status", "status"),
        Index("ix_runs_case_status", "case_id", "status"),
        Index("ix_runs_celery_task_id", "celery_task_id"),
        Index("ix_runs_last_event_at", "last_event_at"),
    )

    run_id = Column(String(128), primary_key=True)
    case_id = Column(
        String(128),
        ForeignKey("cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(32), default="queued", nullable=False)
    agent_mode = Column(String(32), default="review", nullable=False)
    started_at = Column(UTCDateTime(), nullable=True)
    completed_at = Column(UTCDateTime(), nullable=True)
    summary = Column(MutableDict.as_mutable(JSONB), nullable=True)
    workdir = Column(Text, nullable=True)
    final_html_report_url = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    last_event_at = Column(UTCDateTime(), nullable=True)
    created_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)
    celery_task_id = Column(String(255), nullable=True)
    stages = Column(MutableList.as_mutable(JSONB), nullable=True)
    current_stage = Column(String(50), nullable=True)

    case = relationship(
        "CaseModel", back_populates="runs", foreign_keys=[case_id]
    )
    events = relationship(
        "RunEventModel",
        back_populates="run",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    artifacts = relationship(
        "ArtifactModel",
        back_populates="run",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    findings = relationship(
        "FindingModel",
        back_populates="run",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    diagnostics_summary = relationship(
        "RunDiagnosticsSummaryModel",
        back_populates="run",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "status": self.status,
            "agent_mode": self.agent_mode,
            "started_at": to_iso_timestamp(self.started_at)
            if self.started_at
            else None,
            "completed_at": to_iso_timestamp(self.completed_at)
            if self.completed_at
            else None,
            "summary": self.summary,
            "workdir": self.workdir,
            "final_html_report_url": self.final_html_report_url,
            "error": self.error,
            "last_event_at": to_iso_timestamp(self.last_event_at)
            if self.last_event_at
            else None,
            "celery_task_id": self.celery_task_id,
            "stages": self.stages,
            "current_stage": self.current_stage,
        }


class RunEventModel(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        Index("ix_run_events_run_id_id", "run_id", "id"),
        Index("ix_run_events_run_event_id", "run_id", "event_type", "id"),
        Index("ix_run_events_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        String(128),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(64), default="progress", nullable=False)
    payload = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    created_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)

    run = relationship("RunModel", back_populates="events")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "timestamp": to_iso_timestamp(self.created_at),
            "event": self.event_type,
        }
        if isinstance(self.payload, dict):
            result.update(self.payload)
        return result


class InvestigationRecordModel(Base):
    __tablename__ = "investigation_records"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_values(INVESTIGATION_STATUSES)})",
            name="ck_investigation_records_status",
        ),
        CheckConstraint(
            f"validation_status IN ({_sql_values(VALIDATION_STATUSES)})",
            name="ck_investigation_records_validation_status",
        ),
        Index("ix_investigation_records_case_created_at", "case_id", "created_at"),
        Index("ix_investigation_records_case_status", "case_id", "status"),
        Index("ix_investigation_records_tool_id", "tool_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(
        String(128),
        ForeignKey("cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_id = Column(Integer, nullable=True)
    action_id = Column(String(128), nullable=True)
    tool_id = Column(String(128), nullable=False)
    status = Column(String(32), default="completed", nullable=False)
    validation_status = Column(String(32), default="not_validated", nullable=False)
    hypothesis = Column(Text, default="", nullable=False)
    expected_evidence_type = Column(String(128), default="", nullable=False)
    params = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    depends_on_artifacts = Column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    output_artifacts = Column(
        MutableList.as_mutable(JSONB), default=list, nullable=False
    )
    detail = Column(Text, default="", nullable=False)
    metadata_ = Column("metadata", MutableDict.as_mutable(JSONB), default=dict)
    created_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)

    case = relationship("CaseModel", back_populates="investigation_records")

    def to_dict(self) -> dict[str, Any]:
        return {
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
            "metadata": self.metadata_,
            "created_at": to_iso_timestamp(self.created_at),
            "schema_version": "1.0",
        }


class ReviewDecisionModel(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        UniqueConstraint("case_id", "source_ref", name="uq_review_decision_source"),
        CheckConstraint(
            f"status IN ({_sql_values(REVIEW_DECISION_STATUSES)})",
            name="ck_review_decisions_status",
        ),
        Index("ix_review_decisions_case_status", "case_id", "status"),
        Index("ix_review_decisions_decided_at", "decided_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(
        String(128),
        ForeignKey("cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_ref = Column(String(256), nullable=False)
    status = Column(String(32), default="open", nullable=False)
    note = Column(Text, default="", nullable=False)
    decided_by = Column(String(128), nullable=True)
    decided_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)
    decision_type = Column(String(64), nullable=True)

    case = relationship("CaseModel", back_populates="review_decisions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ref": self.source_ref,
            "status": self.status,
            "note": self.note,
            "decided_by": self.decided_by,
            "decided_at": to_iso_timestamp(self.decided_at),
            "decision_type": self.decision_type,
        }


class ArtifactModel(Base):
    """Indexed metadata for filesystem-backed audit artifacts."""

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "artifact_type", "path", name="uq_artifact_run_path"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_artifacts_size"),
        Index("ix_artifacts_case_run", "case_id", "run_id"),
        Index("ix_artifacts_run_type", "run_id", "artifact_type"),
        Index("ix_artifacts_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(
        String(128),
        ForeignKey("cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(
        String(128),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_type = Column(String(128), nullable=False)
    path = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    schema_version = Column(String(64), nullable=True)
    metadata_ = Column("metadata", MutableDict.as_mutable(JSONB), default=dict)
    created_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)

    case = relationship("CaseModel", back_populates="artifacts")
    run = relationship("RunModel", back_populates="artifacts")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "run_id": self.run_id,
            "artifact_type": self.artifact_type,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "schema_version": self.schema_version,
            "metadata": self.metadata_ or {},
            "created_at": to_iso_timestamp(self.created_at),
        }


class FindingModel(Base):
    """Indexed metadata for report findings stored in run artifacts."""

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("run_id", "finding_id", name="uq_finding_run_id"),
        CheckConstraint(
            f"status IN ({_sql_values(FINDING_STATUSES)})",
            name="ck_findings_status",
        ),
        CheckConstraint(
            f"risk_level IN ({_sql_values(RISK_LEVELS)})",
            name="ck_findings_risk_level",
        ),
        Index("ix_findings_case_run", "case_id", "run_id"),
        Index("ix_findings_case_status", "case_id", "status"),
        Index("ix_findings_run_category", "run_id", "category"),
        Index("ix_findings_run_risk", "run_id", "risk_level"),
        Index("ix_findings_source_ref", "source_ref"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(
        String(128),
        ForeignKey("cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(
        String(128),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    finding_id = Column(String(128), nullable=False)
    category = Column(String(128), nullable=False)
    risk_level = Column(String(32), default="medium", nullable=False)
    status = Column(String(32), default="open", nullable=False)
    source_ref = Column(String(256), nullable=True)
    artifact_path = Column(Text, nullable=True)
    title = Column(Text, default="", nullable=False)
    summary = Column(Text, default="", nullable=False)
    metadata_ = Column("metadata", MutableDict.as_mutable(JSONB), default=dict)
    created_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)

    case = relationship("CaseModel", back_populates="findings")
    run = relationship("RunModel", back_populates="findings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "run_id": self.run_id,
            "finding_id": self.finding_id,
            "category": self.category,
            "risk_level": self.risk_level,
            "status": self.status,
            "source_ref": self.source_ref,
            "artifact_path": self.artifact_path,
            "title": self.title,
            "summary": self.summary,
            "metadata": self.metadata_ or {},
            "created_at": to_iso_timestamp(self.created_at),
        }


class RunDiagnosticsSummaryModel(Base):
    """Compact per-run diagnostics summary for agent feedback loops."""

    __tablename__ = "run_diagnostics_summary"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_values(RUN_DIAGNOSTICS_STATUSES)})",
            name="ck_run_diagnostics_summary_status",
        ),
        CheckConstraint(
            "quality_flags_count >= 0",
            name="ck_run_diagnostics_summary_quality_flags_count",
        ),
        Index("ix_run_diagnostics_summary_status", "status"),
        Index("ix_run_diagnostics_summary_generated_at", "generated_at"),
    )

    run_id = Column(
        String(128),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    status = Column(String(64), default="ok", nullable=False)
    quality_flags_count = Column(Integer, default=0, nullable=False)
    latest_path = Column(Text, nullable=True)
    recommended_action = Column(Text, nullable=True)
    summary = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    generated_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)

    run = relationship("RunModel", back_populates="diagnostics_summary")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "quality_flags_count": self.quality_flags_count,
            "latest_path": self.latest_path,
            "recommended_action": self.recommended_action,
            "summary": self.summary or {},
            "generated_at": to_iso_timestamp(self.generated_at),
        }


class ToolRegistryModel(Base):
    __tablename__ = "tool_registry"
    __table_args__ = (
        Index("ix_tool_registry_step_key", "step_key"),
        Index("ix_tool_registry_execution_phase", "execution_phase"),
    )

    tool_id = Column(String(128), primary_key=True)
    step_key = Column(String(128), nullable=False)
    title = Column(Text, default="", nullable=False)
    source = Column(Text, default="", nullable=False)
    description = Column(Text, default="", nullable=False)
    deterministic = Column(Boolean, default=True, nullable=False)
    agent_selectable = Column(Boolean, default=False, nullable=False)
    input_artifacts = Column(MutableList.as_mutable(JSONB), default=list)
    output_artifacts = Column(MutableList.as_mutable(JSONB), default=list)
    parameter_defaults = Column(MutableDict.as_mutable(JSONB), default=dict)
    param_schema = Column(MutableDict.as_mutable(JSONB), default=dict)
    execution_phase = Column(String(32), default="agent_selectable", nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "step_key": self.step_key,
            "title": self.title,
            "source": self.source,
            "description": self.description,
            "deterministic": self.deterministic,
            "agent_selectable": self.agent_selectable,
            "input_artifacts": self.input_artifacts,
            "output_artifacts": self.output_artifacts,
            "parameter_defaults": self.parameter_defaults,
            "param_schema": self.param_schema,
            "execution_phase": self.execution_phase,
        }


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_email", "email"),)

    username = Column(String(128), primary_key=True)
    password_hash = Column(String(256), nullable=False)
    email = Column(String(256), default="", nullable=False)
    roles = Column(String(512), default="operator", nullable=False)
    created_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "email": self.email,
            "roles": self.roles.split(",") if self.roles else [],
            "created_at": to_iso_timestamp(self.created_at),
        }


class CloudflareUserModel(Base):
    """Cloudflare Access authenticated user.

    Stored in PostgreSQL so that ``Base.metadata.create_all()`` discovers it
    during startup.  The ``cf_users`` table is intentionally separate from
    the ``users`` table (used by BasicAuthProvider's SQLite store).
    """

    __tablename__ = "cf_users"

    email = Column(String(320), primary_key=True)
    display_name = Column(String(256), default="", nullable=False)
    roles = Column(String(128), default="operator", nullable=False)
    created_at = Column(UTCDateTime(), default=utc_now_datetime, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "display_name": self.display_name,
            "roles": [r.strip() for r in self.roles.split(",") if r.strip()],
            "created_at": to_iso_timestamp(self.created_at),
        }


# ===================================================================
# Pydantic schemas for FastAPI request / response validation
# ===================================================================


# --- Cases ---


class CaseCreate(BaseModel):
    paper_title: str = "Unknown until parsed"
    case_id: str | None = None
    reproducibility_tier: str = "full"


class CaseRead(BaseModel):
    case_id: str
    paper_title: str = "Unknown until parsed"
    status: str = "Draft"
    technical_risk: str = "pending"
    review_needed_count: int = 0
    owner: str = "operator"
    created_at: str = ""
    updated_at: str = ""
    latest_run_id: str | None = None
    input_count: int = 0
    reproducibility_tier: str = "full"
    paper_pdf: str | None = None


class CaseUpdate(BaseModel):
    paper_title: str | None = None
    paper_pdf: str | None = None
    status: str | None = None


class InputUpload(BaseModel):
    filename: str = "paper.pdf"
    content_base64: str | None = None
    content: str | None = None


# --- Runs ---


class RunRead(BaseModel):
    run_id: str
    case_id: str
    status: str = "queued"
    agent_mode: str = "review"
    started_at: str | None = None
    completed_at: str | None = None
    summary: dict[str, Any] | None = None
    workdir: str | None = None
    error: str | None = None


# --- Investigation Records ---


class InvestigationRecordRead(BaseModel):
    round_id: int | None = None
    action_id: str | None = None
    tool_id: str
    status: str = "completed"
    validation_status: str = "not_validated"
    hypothesis: str = ""
    expected_evidence_type: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class InvestigationRunRequest(BaseModel):
    tool_id: str | None = None
    panel_ids: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    hypothesis: str | None = None
    action_id: str | None = None


# --- Review ---


class ReviewDecisionCreate(BaseModel):
    status: Literal["open", "resolved", "dismissed", "needs_author_response"] = "open"
    note: str = ""
    decision_type: (
        Literal["apply_suggestion", "manual_edit", "re_execute", "appeal"] | None
    ) = None


class ReviewDecisionRead(BaseModel):
    source_ref: str
    status: str = "open"
    note: str = ""
    decided_by: str | None = None
    decided_at: str = ""
    decision_type: str | None = None


class ReviewItemRead(BaseModel):
    source_ref: str
    title: str = ""
    risk_level: str = "medium"
    issue_category: str = ""
    source: str = ""
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    recommended_action: str = ""
    benign_explanation: str = ""
    finding_id: str | None = None
    decision: ReviewDecisionRead | None = None


# --- Tool Catalog ---


class ToolCatalogRead(BaseModel):
    tool_id: str
    title: str = ""
    source: str = ""
    description: str = ""
    deterministic: bool = True
    agent_selectable: bool = False
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    parameter_defaults: dict[str, Any] = Field(default_factory=dict)
    param_schema: dict[str, Any] = Field(default_factory=dict)


# --- Artifact Ref ---


class ArtifactRefRead(BaseModel):
    artifact_id: str
    kind: str
    label: str
    path: str
    url: str
    exists: bool
    size_bytes: int | None = None
    updated_at: str | None = None
