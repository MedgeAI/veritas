"""Shared types for Veritas audit engine.

This module contains data structures and type aliases used across
engine.static_audit and engine.investigation modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class StepResult:
    """Result of a pipeline step execution."""
    key: str
    title: str
    status: str
    detail: str
    command: list[str] | None = None


@dataclass(frozen=True)
class InvestigationAction:
    """An action to be performed during investigation rounds."""
    round_id: int
    action_id: str
    tool_id: str
    params: dict[str, Any]
    hypothesis: str
    depends_on_artifacts: list[str]
    expected_evidence_type: str
    stop_if_no_new_evidence: bool = True
    output_artifacts: list[str] = field(default_factory=list)

    def signature(self) -> str:
        """Generate a signature for deduplication."""
        import hashlib
        import json
        payload = {
            "tool_id": self.tool_id,
            "params": self.params,
            "depends_on_artifacts": sorted(self.depends_on_artifacts),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "round_id": self.round_id,
            "action_id": self.action_id,
            "tool_id": self.tool_id,
            "params": self.params,
            "hypothesis": self.hypothesis,
            "depends_on_artifacts": self.depends_on_artifacts,
            "expected_evidence_type": self.expected_evidence_type,
            "stop_if_no_new_evidence": self.stop_if_no_new_evidence,
            "output_artifacts": self.output_artifacts,
            "signature": self.signature(),
        }


ProgressCallback = Callable[[dict[str, Any]], None]
