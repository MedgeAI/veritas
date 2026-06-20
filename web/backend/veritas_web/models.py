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
    JSON,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

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
    "Archived",
}

RUN_STATUSES: set[str] = {"queued", "running", "completed", "failed", "interrupted"}

STALE_RUN_THRESHOLD_SECONDS = 300  # 5 minutes — no heartbeat → stale

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseRecord":
        return cls(**{field_name: data[field_name] for field_name in cls.__dataclass_fields__ if field_name in data})

    @classmethod
    def from_model(cls, model: CaseModel) -> "CaseRecord":  # type: ignore[name-defined]  # forward ref
        return cls(
            case_id=model.case_id,
            paper_title=model.paper_title or "Unknown until parsed",
            status=model.status or "Draft",
            technical_risk=model.technical_risk or "pending",
            review_needed_count=model.review_needed_count or 0,
            owner=model.owner or "operator",
            created_at=model.created_at or utc_now(),
            updated_at=model.updated_at or utc_now(),
            latest_run_id=model.latest_run_id,
            input_count=model.input_count or 0,
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
        return cls(**{field_name: data[field_name] for field_name in cls.__dataclass_fields__ if field_name in data})

    @classmethod
    def from_model(cls, model: RunModel) -> "AuditRunRecord":  # type: ignore[name-defined]
        return cls(
            run_id=model.run_id,
            case_id=model.case_id,
            status=model.status or "queued",
            agent_mode=model.agent_mode or "review",
            started_at=model.started_at,
            completed_at=model.completed_at,
            summary=model.summary,
            workdir=model.workdir,
            final_html_report_url=model.final_html_report_url,
            error=model.error,
            last_event_at=model.last_event_at,
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

    case_id = Column(String(128), primary_key=True)
    paper_title = Column(Text, default="Unknown until parsed")
    status = Column(String(32), default="Draft")
    technical_risk = Column(String(32), default="pending")
    review_needed_count = Column(Integer, default=0)
    owner = Column(String(128), default="operator", nullable=False)
    created_at = Column(String(32), default=utc_now)
    updated_at = Column(String(32), default=utc_now)
    latest_run_id = Column(String(128), nullable=True)
    input_count = Column(Integer, default=0)

    runs = relationship("RunModel", back_populates="case", lazy="selectin")
    review_decisions = relationship("ReviewDecisionModel", back_populates="case", lazy="selectin")
    investigation_records = relationship("InvestigationRecordModel", back_populates="case", lazy="selectin")
    image_embeddings = relationship("ImageEmbeddingModel", back_populates="case", lazy="selectin")
    embedding_index_jobs = relationship("EmbeddingIndexJobModel", back_populates="case", lazy="selectin")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "paper_title": self.paper_title,
            "status": self.status,
            "technical_risk": self.technical_risk,
            "review_needed_count": self.review_needed_count,
            "owner": self.owner,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "latest_run_id": self.latest_run_id,
            "input_count": self.input_count,
        }


class RunModel(Base):
    __tablename__ = "runs"

    run_id = Column(String(128), primary_key=True)
    case_id = Column(String(128), ForeignKey("cases.case_id"), nullable=False, index=True)
    status = Column(String(32), default="queued")
    agent_mode = Column(String(32), default="review")
    started_at = Column(String(32), nullable=True)
    completed_at = Column(String(32), nullable=True)
    summary = Column(JSON, nullable=True)
    workdir = Column(Text, nullable=True)
    final_html_report_url = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    last_event_at = Column(String(32), nullable=True)
    created_at = Column(String(32), default=utc_now)

    case = relationship("CaseModel", back_populates="runs")
    events = relationship("RunEventModel", back_populates="run", lazy="selectin")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "status": self.status,
            "agent_mode": self.agent_mode,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "summary": self.summary,
            "workdir": self.workdir,
            "final_html_report_url": self.final_html_report_url,
            "error": self.error,
            "last_event_at": self.last_event_at,
        }


class RunEventModel(Base):
    __tablename__ = "run_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(128), ForeignKey("runs.run_id"), nullable=False, index=True)
    event_type = Column(String(64), default="progress")
    payload = Column(JSON, default=dict)
    created_at = Column(String(32), default=utc_now)

    run = relationship("RunModel", back_populates="events")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "timestamp": self.created_at,
            "event": self.event_type,
        }
        if isinstance(self.payload, dict):
            result.update(self.payload)
        return result


class InvestigationRecordModel(Base):
    __tablename__ = "investigation_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(128), ForeignKey("cases.case_id"), nullable=False, index=True)
    round_id = Column(Integer, nullable=True)
    action_id = Column(String(128), nullable=True)
    tool_id = Column(String(128), nullable=False)
    status = Column(String(32), default="completed")
    validation_status = Column(String(32), default="not_validated")
    hypothesis = Column(Text, default="")
    expected_evidence_type = Column(String(128), default="")
    params = Column(JSON, default=dict)
    depends_on_artifacts = Column(JSON, default=list)
    output_artifacts = Column(JSON, default=list)
    detail = Column(Text, default="")
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(String(32), default=utc_now)

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
            "created_at": self.created_at,
            "schema_version": "1.0",
        }


class ReviewDecisionModel(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        UniqueConstraint("case_id", "source_ref", name="uq_review_decision_source"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(128), ForeignKey("cases.case_id"), nullable=False, index=True)
    source_ref = Column(String(256), nullable=False)
    status = Column(String(32), default="open")
    note = Column(Text, default="")
    decided_by = Column(String(128), nullable=True)
    decided_at = Column(String(32), default=utc_now)

    case = relationship("CaseModel", back_populates="review_decisions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ref": self.source_ref,
            "status": self.status,
            "note": self.note,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
        }


class ImageEmbeddingModel(Base):
    __tablename__ = "image_embeddings"
    __table_args__ = (
        Index("idx_image_embeddings_case", "case_id"),
        Index("idx_image_embeddings_level", "case_id", "embedding_level"),
        UniqueConstraint("case_id", "panel_id", "embedding_level", name="uq_image_embedding_case_panel_level"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(128), ForeignKey("cases.case_id"), nullable=False)
    panel_id = Column(String(128), nullable=False)
    figure_id = Column(String(128), nullable=True)
    image_path = Column(Text, nullable=False)
    embedding = Column(JSON, nullable=True)  # 512-dim float list; pgvector Vector in production
    embedding_level = Column(String(16), default="panel", nullable=False)  # "panel" or "figure"
    embedding_model = Column(String(64), default="sscd_disc_mixup", nullable=False)
    embedding_dim = Column(Integer, default=512, nullable=False)
    indexed_at = Column(String(32), default=utc_now)

    case = relationship("CaseModel", back_populates="image_embeddings")


class EmbeddingIndexJobModel(Base):
    __tablename__ = "embedding_index_jobs"

    case_id = Column(String(128), ForeignKey("cases.case_id"), primary_key=True)
    status = Column(String(32), default="not_indexed")
    indexed_count = Column(Integer, default=0)
    expected_count = Column(Integer, nullable=True)
    detail = Column(Text, default="")
    started_at = Column(String(32), nullable=True)
    completed_at = Column(String(32), nullable=True)
    updated_at = Column(String(32), default=utc_now)

    case = relationship("CaseModel", back_populates="embedding_index_jobs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "indexed_count": self.indexed_count,
            "expected_count": self.expected_count,
            "detail": self.detail,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "updated_at": self.updated_at,
        }


class ToolRegistryModel(Base):
    __tablename__ = "tool_registry"

    tool_id = Column(String(128), primary_key=True)
    step_key = Column(String(128), nullable=False)
    title = Column(Text, default="")
    source = Column(Text, default="")
    description = Column(Text, default="")
    deterministic = Column(Boolean, default=True)
    agent_selectable = Column(Boolean, default=False)
    input_artifacts = Column(JSON, default=list)
    output_artifacts = Column(JSON, default=list)
    parameter_defaults = Column(JSON, default=dict)
    param_schema = Column(JSON, default=dict)
    execution_phase = Column(String(32), default="agent_selectable")

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

    username = Column(String(128), primary_key=True)
    password_hash = Column(String(256), nullable=False)
    email = Column(String(256), default="")
    roles = Column(String(512), default="operator")
    created_at = Column(String(32), default=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "email": self.email,
            "roles": self.roles.split(",") if self.roles else [],
            "created_at": self.created_at,
        }


# ===================================================================
# Pydantic schemas for FastAPI request / response validation
# ===================================================================


# --- Cases ---

class CaseCreate(BaseModel):
    paper_title: str = "Unknown until parsed"
    case_id: str | None = None


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


class CaseUpdate(BaseModel):
    paper_title: str | None = None
    status: str | None = None


class InputUpload(BaseModel):
    filename: str = "paper.pdf"
    content_base64: str | None = None
    content: str | None = None


# --- Runs ---

class RunCreate(BaseModel):
    agent_mode: str = "review"


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


class ReviewDecisionRead(BaseModel):
    source_ref: str
    status: str = "open"
    note: str = ""
    decided_by: str | None = None
    decided_at: str = ""


class ReviewItemRead(BaseModel):
    source_ref: str
    title: str = ""
    risk_level: str = "medium"
    issue_category: str = ""
    source: str = ""
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    recommended_action: str = ""
    benign_explanation: str = ""
    decision: ReviewDecisionRead | None = None


# --- Embeddings ---

class EmbeddingStatusRead(BaseModel):
    case_id: str
    indexed_count: int = 0
    last_indexed_at: str | None = None
    status: str = "not_indexed"
    model_available: bool | None = None
    expected_count: int | None = None
    detail: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str | None = None


class SimilarityResult(BaseModel):
    panel_id: str
    similarity: float
    figure_id: str | None = None
    image_path: str = ""


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
