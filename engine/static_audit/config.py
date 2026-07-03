"""Configuration dataclass for the static audit pipeline.

Centralizes the 14 configuration parameters that ``run_static_audit`` passes
through to the stage modules.  Keeps the public API surface narrow: a single
``AuditConfig`` argument replaces the previous 14 keyword parameters.

The ``progress`` callback is intentionally NOT part of this dataclass — it is
a runtime callback, not configuration, and is passed separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from engine.llm.config import DEFAULT_LLM_MODEL


@dataclass(frozen=True)
class AuditConfig:
    """Configuration for a single static audit pipeline run.

    Field semantics mirror the former ``run_static_audit`` keyword parameters
    one-to-one.  ``audit_profile`` is stored as the raw profile name string
    (e.g. ``"fast"``, ``"standard"``, ``"full"``); the resolved profile dict
    is computed inside ``run_static_audit`` via ``resolve_audit_profile``.
    """

    paper_dir: str | Path
    paper_pdf: str | Path | None = None
    paper_pdf_selection_source: str | None = None
    case_id: str | None = None
    output_root: str = "outputs"
    fresh: bool = False
    force: bool = False
    no_env_file: bool = False
    agent_mode: str = "full"
    agent_model: str = field(default_factory=lambda: DEFAULT_LLM_MODEL)
    opencode_bin: str = "opencode"
    agent_timeout_seconds: int = 600
    agent_max_retries: int = 1
    reproducibility_tier: str = "full"
    skip_unavailable_tools: bool = False
    audit_profile: str = "fast"
