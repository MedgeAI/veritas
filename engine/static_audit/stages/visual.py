"""Visual stage — image duplicates, figure classification, visual baseline.

Corresponds to lines 491-552 of the original pipeline.py ``_run_static_audit_from_args``.
Also contains ``_run_visual_baseline`` which was moved here from pipeline.py.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.static_audit._shared import (
    PROJECT_ROOT,
    ProgressCallback,
    StepResult,
    record_step,
    resolve_artifact_path,
    run_command,
)


# ---------------------------------------------------------------------------
# Visual baseline (moved from pipeline.py)
# ---------------------------------------------------------------------------


def _run_visual_baseline(
    *,
    workdir: Path,
    images_dir: Path,
    args: argparse.Namespace,
    progress: ProgressCallback | None,
    figure_classification: dict[str, Any] | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    from engine.static_audit.visual_pipeline import (
        run_visual_panel_extraction,
        run_tru_for_detection,
        run_image_quality_detection,
        run_provenance_graph,
        run_visual_finding_pipeline,
    )

    steps: list[StepResult] = []
    manifest: dict[str, Any] = {}
    vs, vm = run_visual_panel_extraction(
        workdir=workdir,
        images_dir=images_dir,
        force=args.force,
        progress=progress,
        figure_classification=figure_classification,
    )
    steps.extend(vs)
    manifest["visual_forensics"] = vm
    allow_env_skip = getattr(args, "skip_unavailable_tools", False)
    pe_status = (
        manifest.get("visual_forensics", {}).get("panel_extraction", {}).get("status")
    )
    for runner in (
        run_tru_for_detection,
        run_image_quality_detection,
        run_provenance_graph,
    ):
        kw: dict[str, Any] = {
            "workdir": workdir,
            "force": args.force,
            "progress": progress,
        }
        if runner is run_tru_for_detection:
            kw["figure_classification"] = figure_classification
        if runner is not run_image_quality_detection:
            kw["allow_env_skip"] = allow_env_skip
        kw["panel_extraction_status"] = pe_status
        s, m = runner(**kw)
        steps.extend(s)
        manifest.setdefault("visual_forensics", {}).update(m)
    fs, fm = run_visual_finding_pipeline(
        workdir=workdir, force=args.force, progress=progress
    )
    steps.extend(fs)
    manifest.setdefault("visual_forensics", {}).update(fm)
    return steps, manifest


# ---------------------------------------------------------------------------
# Stage result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VisualResult:
    """Outputs of the visual stage."""

    figure_classification: dict[str, Any] | None
    steps: list[StepResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage entry point
# ---------------------------------------------------------------------------


def run(
    args: argparse.Namespace,
    *,
    workdir: Path,
    images_dir: Path,
    env: dict[str, str],
    agent_manifest: dict[str, Any],
    progress: ProgressCallback | None,
) -> VisualResult:
    """Run image duplicates, figure classification, and visual baseline."""
    steps: list[StepResult] = []

    # Image duplicates
    if images_dir.is_dir():
        steps.append(
            run_command(
                "exact_image_duplicates",
                "图片字节级重复检查",
                [
                    sys.executable,
                    "-m",
                    "engine.static_audit.tools.exact_image_duplicates",
                    str(images_dir),
                    "--output",
                    str(resolve_artifact_path(workdir, "exact_image_duplicates.json")),
                ],
                [resolve_artifact_path(workdir, "exact_image_duplicates.json")],
                cwd=PROJECT_ROOT,
                env=env,
                force=args.force,
                progress=progress,
            )
        )
    else:
        for k, t in [
            ("exact_image_duplicates", "图片字节级重复检查"),
            ("image_similarity_candidates", "图片近似相似候选检查"),
        ]:
            record_step(
                steps,
                StepResult(k, t, "skipped", "images directory missing."),
                progress,
            )

    # Figure classification (LLM legend analysis)
    from engine.static_audit.figure_classification import (
        run_figure_classification_step,
    )

    fc_steps, fc_manifest = run_figure_classification_step(
        workdir=workdir,
        force=args.force,
        progress=progress,
    )
    steps.extend(fc_steps)
    agent_manifest["figure_classification"] = fc_manifest.get("figure_classification")

    # Visual baseline
    vb_steps, vb_manifest = _run_visual_baseline(
        workdir=workdir,
        images_dir=images_dir,
        args=args,
        progress=progress,
        figure_classification=fc_manifest.get("figure_classification"),
    )
    steps.extend(vb_steps)
    agent_manifest.setdefault("visual_forensics", {}).update(
        {
            k: v
            for k, v in vb_manifest.get("visual_forensics", {}).items()
            if k not in (agent_manifest.get("visual_forensics") or {})
        }
    )

    return VisualResult(
        figure_classification=fc_manifest.get("figure_classification"),
        steps=steps,
    )
