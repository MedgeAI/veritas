"""Reproduction stage -- Veritas-Auditor claim reproduction.

Runs after the visual stage and before investigation.  This stage checks
whether code artifacts are available and, if so, executes Veritas-Auditor
on extracted claims to produce reproduction verdicts.

When no code artifacts are provided the stage degrades gracefully: it
records a ``skipped`` step and does **not** break the pipeline.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.static_audit._shared import (
    ProgressCallback,
    StepResult,
    record_step,
    resolve_artifact_path,
)

logger = logging.getLogger(__name__)

# Directory names (relative to workdir) that indicate code artifacts.
_CODE_ARTIFACT_DIRS = ("code", "source_code", "reproduction")


@dataclass(frozen=True, slots=True)
class ReproductionResult:
    """Outputs of the reproduction stage."""

    reproduction_evidence: list[dict[str, Any]]
    claim_verdicts: list[dict[str, Any]]
    steps: list[StepResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_code_artifacts(workdir: Path) -> Path | None:
    """Return the first recognised code-artifact directory, or *None*."""
    for name in _CODE_ARTIFACT_DIRS:
        candidate = workdir / name
        if candidate.is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------


def run(
    args: argparse.Namespace,
    *,
    workdir: Path,
    agent_manifest: dict[str, Any],
    progress: ProgressCallback | None,
) -> ReproductionResult:
    """Run the reproduction/auditor stage.

    This stage:
    1. Checks if code artifacts are available under *workdir*.
    2. If not, records a ``skipped`` step and returns empty evidence.
    3. If available, creates stub claim verdicts and updates
       *agent_manifest* with reproduction evidence.

    The stage is intentionally non-fatal: any failure is caught and
    recorded as a ``warning`` step so that the rest of the pipeline
    continues unaffected.
    """
    steps: list[StepResult] = []

    code_dir = _detect_code_artifacts(workdir)

    if code_dir is None:
        record_step(
            steps,
            StepResult(
                "reproduction",
                "Reproduction / Veritas-Auditor",
                "skipped",
                "Reproduction stage: no code artifacts provided.",
            ),
            progress,
        )
        return ReproductionResult(
            reproduction_evidence=[],
            claim_verdicts=[],
            steps=steps,
        )

    # --- Code artifacts detected -- run Veritas-Auditor ---------------------
    try:
        # TODO: Replace stub with real Veritas-Auditor invocation.
        claims = agent_manifest.get("claims", [])
        claim_verdicts: list[dict[str, Any]] = [
            {
                "claim_id": c.get("claim_id", ""),
                "verdict": "pending",
                "evidence": [],
            }
            for c in claims
        ]
        reproduction_evidence: list[dict[str, Any]] = [
            {
                "type": "reproduction_stub",
                "code_dir": str(code_dir),
                "claim_count": len(claim_verdicts),
            }
        ]

        artifact_path = resolve_artifact_path(workdir, "reproduction_evidence.json")
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            _json_dumps(reproduction_evidence), encoding="utf-8"
        )

        record_step(
            steps,
            StepResult(
                "reproduction",
                "Reproduction / Veritas-Auditor",
                "ran",
                f"Processed {len(claim_verdicts)} claim(s) from {code_dir}.",
                output_artifacts=[str(artifact_path)],
            ),
            progress,
        )

        # Propagate results into agent_manifest for downstream consumers.
        agent_manifest["reproduction_evidence"] = reproduction_evidence
        agent_manifest["claim_verdicts"] = claim_verdicts

        return ReproductionResult(
            reproduction_evidence=reproduction_evidence,
            claim_verdicts=claim_verdicts,
            steps=steps,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Reproduction stage failed: %s", exc)
        record_step(
            steps,
            StepResult(
                "reproduction",
                "Reproduction / Veritas-Auditor",
                "warning",
                f"Reproduction stage failed: {exc}",
            ),
            progress,
        )
        return ReproductionResult(
            reproduction_evidence=[],
            claim_verdicts=[],
            steps=steps,
        )


# ---------------------------------------------------------------------------
# Minimal JSON helper (avoids importing heavy deps at module scope)
# ---------------------------------------------------------------------------


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2)


# Public alias matching the function signature referenced in pipeline docs.
run_reproduction_stage = run
