"""Agent Function Runtime — shared contracts.

This module defines the data structures used by AgentStepRunner,
AgentContextPack, and progress event emission. All agents in the
P0 parallel streams reference these definitions as the single
source of truth.

See PRD: prd/opencode-agent-function-runtime.md
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# AgentRunResult — unified result from AgentStepRunner
# ---------------------------------------------------------------------------

AgentErrorCategory = Literal[
    "timeout",
    "schema_validation",
    "permission_rejected",
    "model_failure",
    "non_zero_exit",
]

AgentRunStatus = Literal["success", "failed", "skipped"]


@dataclass
class AgentRunResult:
    """Result of a single Agent step invocation.

    Replaces the legacy AgentRunResult in opencode_agent.py during
    migration. The new shape adds structured error classification,
    log artifact references, and metadata for observability.
    """
    status: AgentRunStatus
    role: str
    output: dict[str, Any] | None = None
    error_category: AgentErrorCategory | None = None
    runtime_seconds: float = 0.0
    log_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# AgentContextPack — bounded context for Agent reasoning
# ---------------------------------------------------------------------------

TruncationStrategy = Literal["head_tail", "summary"]


@dataclass
class TruncationConfig:
    """Token budget constraints for context packs.

    Hard limits prevent context overflow and cost explosion.
    head_tail strategy keeps first 30% + last 30% of text,
    inserting [...truncated...] in the middle.
    """
    max_tokens_per_pack: int = 200_000
    max_tokens_per_excerpt: int = 50_000
    strategy: TruncationStrategy = "head_tail"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentContextPack:
    """Bounded context input for Agent reasoning.

    Contains compact summaries and evidence references instead of
    raw artifacts. Token budget is enforced at construction time.

    Must contain: artifact_manifest, evidence_refs, top_n_findings,
    limitations, bounded_excerpts, truncation_config.

    Must NOT contain: raw PDF, images, full evidence ledger,
    large investigation output.
    """
    artifact_manifest: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    top_n_findings: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    bounded_excerpts: dict[str, str] = field(default_factory=dict)
    truncation_config: TruncationConfig = field(default_factory=TruncationConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_manifest": self.artifact_manifest,
            "evidence_refs": self.evidence_refs,
            "top_n_findings": self.top_n_findings,
            "limitations": self.limitations,
            "bounded_excerpts": self.bounded_excerpts,
            "truncation_config": self.truncation_config.to_dict(),
        }

    def to_json_bytes(self) -> bytes:
        import json
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# ProgressEvent — short, structured event contract
# ---------------------------------------------------------------------------

ProgressEventStatus = Literal["started", "success", "failed", "skipped"]

PROGRESS_EVENT_SUMMARY_MAX_CHARS = 200


@dataclass
class ProgressEvent:
    """Short, structured progress event for Web event stream.

    Contract:
    - summary: max 200 chars
    - log_ref: required when status="failed"
    - MUST NOT contain: stdout, stderr, full traceback, context_pack, agent_output

    Long output goes to log artifact, referenced via log_ref.
    """
    step: str
    status: ProgressEventStatus
    summary: str = ""
    log_ref: str | None = None
    timestamp: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "step": self.step,
            "status": self.status,
            "summary": self.summary[:PROGRESS_EVENT_SUMMARY_MAX_CHARS],
            "timestamp": self.timestamp,
        }
        if self.log_ref is not None:
            d["log_ref"] = self.log_ref
        return d

    def validate(self) -> None:
        """Raise ValueError if contract is violated."""
        if len(self.summary) > PROGRESS_EVENT_SUMMARY_MAX_CHARS:
            raise ValueError(
                f"summary too long: {len(self.summary)} > {PROGRESS_EVENT_SUMMARY_MAX_CHARS}"
            )
        if self.status == "failed" and not self.log_ref:
            raise ValueError("log_ref is required when status='failed'")
