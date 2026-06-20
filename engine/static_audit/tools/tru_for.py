"""TruFor forgery detection adapter.

Wraps the ELIS TruFor deep-learning forgery detector as a Veritas tool.
Runs TruFor inference on all figure images via subprocess, producing
per-figure ``ForgedRegionEvidence`` records with localization heatmaps.

Startup prerequisites are checked in three layers (D-5):
  1. ``timm`` -- importable; missing means ``make sync`` is needed.
  2. Model weights -- ``models/trufor/weights/trufor.pth.tar`` must exist;
     missing causes the entire tool to be *skipped* with ONE limitation.
  3. GPU/CPU -- CUDA preferred, CPU fallback; never skipped for lack of GPU.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from engine.static_audit.visual_schemas import (
    ForgedRegionEvidence,
    VISUAL_SCHEMA_VERSION,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_WEIGHTS = _REPO_ROOT / "models" / "trufor" / "weights" / "trufor.pth.tar"


def _check_prerequisites(weights_path: Path) -> dict[str, Any] | str:
    """Three-layer prerequisite check (D-5).

    Returns:
        ``"cuda:0"`` or ``"cpu"`` when all checks pass.
        A ``skipped`` result dict when a layer blocks execution.
    """
    # Layer 1: timm
    try:
        import timm  # noqa: F401
    except ImportError:
        return _skipped_result(
            "timm not installed. Run `make sync` to install dependencies."
        )

    # Layer 2: model weights
    if not weights_path.is_file():
        return _skipped_result(f"TruFor model weights not found at {weights_path}.")

    # Layer 3: GPU / CPU
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _skipped_result(reason: str) -> dict[str, Any]:
    """Return a skipped result with exactly ONE limitation entry."""
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/tru_for.py",
        "status": "skipped",
        "failure_category": "environment",
        "figure_count": 0,
        "forged_region_count": 0,
        "suspicious_count": 0,
        "forged_region_evidence": [],
        "errors": [],
        "limitations": [f"TruFor skipped: {reason}"],
    }


def run_tru_for(
    figure_evidence: list[dict[str, Any]],
    *,
    workdir: Path,
    weights_path: Path = DEFAULT_WEIGHTS,
    score_threshold: float = 0.5,
) -> dict[str, Any]:
    """Run TruFor forgery detection on all figures.

    Args:
        figure_evidence: List of figure evidence dicts with source_image_path.
        workdir: Working directory for resolving image paths and writing output.
        weights_path: Path to TruFor model weights.
        score_threshold: Threshold for is_suspicious flag.

    Returns:
        Canonical result dict with forged_region_evidence list.
    """
    output_dir = workdir / "tru_for"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Three-layer prerequisite check (D-5).
    prereq = _check_prerequisites(weights_path)
    if isinstance(prereq, dict):
        return prereq  # skipped result
    device = prereq  # "cuda:0" or "cpu"

    # Build figure list with absolute paths
    figures = []
    for fig in figure_evidence:
        source = str(fig.get("source_image_path") or "")
        if not source:
            continue
        fig_path = workdir / source
        if fig_path.exists():
            figures.append(
                {
                    "figure_id": str(fig.get("figure_id") or ""),
                    "path": str(fig_path),
                }
            )

    if not figures:
        return _failed_result(
            failure_category="dependency",
            errors=["No figure images available for TruFor analysis."],
        )

    # Call runner subprocess
    input_data = {
        "figures": figures,
        "output_dir": str(output_dir),
        "weights_path": str(weights_path),
        "device": device,
        "score_threshold": score_threshold,
    }

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "engine.static_audit.tools._elis_trufor_runner"],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=max(600, len(figures) * 10),
            check=False,
        )
        if proc.returncode != 0:
            return _failed_result(
                failure_category="runtime",
                errors=[
                    f"TruFor runner exited with code {proc.returncode}: {proc.stderr[:500]}"
                ],
            )
        runner_output = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        return _failed_result(
            failure_category="runtime", errors=[f"TruFor runner failed: {e}"]
        )

    # Convert runner results to ForgedRegionEvidence
    forged_evidence = []
    errors: list[str] = []
    limitations: list[str] = []

    for idx, r in enumerate(runner_output.get("results", []), start=1):
        status = r.get("status", "failed")
        figure_id = r.get("figure_id", "")

        if status == "failed":
            errors.append(
                f"TruFor failed for {figure_id}: {r.get('skip_reason', 'unknown')}"
            )
            continue

        if status == "skipped":
            limitations.append(
                f"TruFor skipped for {figure_id}: {r.get('skip_reason', 'unknown')}"
            )
            continue

        # Make paths relative to workdir
        loc_path = r.get("localization_map_path")
        conf_path = r.get("confidence_map_path")
        if loc_path:
            try:
                loc_path = str(Path(loc_path).relative_to(workdir))
            except ValueError:
                pass
        if conf_path:
            try:
                conf_path = str(Path(conf_path).relative_to(workdir))
            except ValueError:
                pass

        fre = ForgedRegionEvidence(
            forged_region_evidence_id=f"FRE-{idx:04d}",
            figure_id=figure_id,
            status="completed",
            integrity_score=r.get("integrity_score"),
            is_suspicious=r.get("is_suspicious", False),
            localization_map_path=loc_path,
            confidence_map_path=conf_path,
            image_width=r.get("image_width", 0),
            image_height=r.get("image_height", 0),
            inference_seconds=r.get("inference_seconds", 0.0),
            metadata={
                "score_threshold": score_threshold,
                "device": device,
                "model_weights": str(weights_path.name),
            },
        )
        forged_evidence.append(fre.to_dict())

    suspicious_count = sum(1 for f in forged_evidence if f.get("is_suspicious"))

    # Delete heatmaps for non-suspicious figures to save disk space.
    # Only pred_map/conf_map for suspicious figures are kept as visual evidence.
    for f in forged_evidence:
        if f.get("is_suspicious"):
            continue
        for key in ("localization_map_path", "confidence_map_path"):
            rel = f.get(key)
            if rel:
                abs_path = workdir / rel
                if abs_path.is_file():
                    abs_path.unlink()
                f[key] = None

    if forged_evidence:
        limitations.append(
            f"TruFor processed {len(forged_evidence)} figures; "
            f"{suspicious_count} flagged as suspicious (score > {score_threshold}). "
            f"These are candidates for human review, not conclusions."
        )

    # "ran" only if we actually produced evidence.  Empty results after a
    # successful subprocess call is still a failure — something is wrong.
    if not forged_evidence:
        return _failed_result(
            failure_category="runtime",
            errors=errors or ["TruFor runner returned no results for any figure."],
        )

    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/tru_for.py",
        "status": "ran",
        "figure_count": len(figures),
        "forged_region_count": len(forged_evidence),
        "suspicious_count": suspicious_count,
        "forged_region_evidence": forged_evidence,
        "errors": errors,
        "limitations": limitations,
    }


def _failed_result(
    *,
    failure_category: str,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Return a failed result with explicit failure category.

    failure_category values:
    - "environment": missing GPU, model weights, Docker, etc.
    - "dependency": upstream artifact missing (visual_evidence.json, etc.)
    - "runtime": inference error, subprocess crash, etc.
    """
    return {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "created_by": "engine/static_audit/tools/tru_for.py",
        "status": "failed",
        "failure_category": failure_category,
        "figure_count": 0,
        "forged_region_count": 0,
        "suspicious_count": 0,
        "forged_region_evidence": [],
        "errors": errors or [],
        "limitations": [],
    }
