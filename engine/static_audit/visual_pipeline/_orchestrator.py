from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from engine.exceptions import VeritasError
from engine.static_audit._shared import (
    ProgressCallback,
    StepResult,
    emit_step_start,
    read_json,
    record_step,
    resolve_artifact_path,
    write_json_artifact,
)

logger = logging.getLogger(__name__)


def _visual_status(values: list[str]) -> str:
    if any(value == "ran" for value in values):
        return "ran"
    if any(value == "not_available" for value in values):
        return "not_available"
    if any(value == "failed" for value in values):
        return "failed"
    return "skipped"


def run_image_quality_detection(
    *,
    workdir: Path,
    force: bool,
    panel_extraction_status: str | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Run lightweight image quality anomaly detection on all figures."""
    steps: list[StepResult] = []
    output_path = resolve_artifact_path(workdir, "image_quality.json")
    if output_path.exists() and not force:
        record_step(
            steps,
            StepResult(
                "visual_image_quality",
                "图片质量异常检测",
                "reused",
                "Existing image_quality.json found.",
            ),
            progress,
        )
        return steps, {
            "image_quality": {"status": "reused", "output": str(output_path)}
        }

    emit_step_start(
        progress,
        "visual_image_quality",
        "图片质量异常检测",
        "Running image quality anomaly detection.",
    )

    visual_evidence_path = resolve_artifact_path(workdir, "visual_evidence.json")
    if not visual_evidence_path.exists():
        if panel_extraction_status in ("skipped", "ran"):
            record_step(
                steps,
                StepResult(
                    "visual_image_quality",
                    "图片质量异常检测",
                    "skipped",
                    "No visual evidence from upstream.",
                ),
                progress,
            )
            return steps, {
                "image_quality": {"status": "skipped", "detail": "no visual evidence"}
            }
        record_step(
            steps,
            StepResult(
                "visual_image_quality",
                "图片质量异常检测",
                "failed",
                "visual_evidence.json not found (upstream dependency).",
            ),
            progress,
        )
        return steps, {
            "image_quality": {
                "status": "failed",
                "failure_category": "dependency",
                "detail": "missing visual_evidence.json",
            }
        }

    visual_evidence = read_json(visual_evidence_path) or {}
    figures = visual_evidence.get("figures", [])

    if not figures:
        record_step(
            steps,
            StepResult(
                "visual_image_quality",
                "图片质量异常检测",
                "skipped",
                "Paper has no figures.",
            ),
            progress,
        )
        return steps, {
            "image_quality": {"status": "skipped", "detail": "no figures in paper"}
        }

    try:
        from engine.static_audit.tools.image_quality import (
            run_background_comparison,
            run_image_quality,
        )

        result = run_image_quality(figures, workdir=workdir)

        # Background texture consistency comparison (panel-level)
        panel_evidence_path = resolve_artifact_path(workdir, "panel_evidence.json")
        if panel_evidence_path.exists():
            panel_data = read_json(panel_evidence_path) or {}
            panels = panel_data.get("panels", [])
            if panels:
                try:
                    bg_result = run_background_comparison(
                        figures, panels, workdir=workdir
                    )
                    # Merge background anomalies into main result
                    bg_anomalies = bg_result.get("anomalies", [])
                    if bg_anomalies:
                        result["anomalies"].extend(bg_anomalies)
                        result["anomaly_count"] = len(result["anomalies"])
                    result["background_comparison"] = {
                        "status": bg_result.get("status", "skipped"),
                        "group_stats": bg_result.get("group_stats", {}),
                        "anomaly_count": bg_result.get("anomaly_count", 0),
                    }
                    result.setdefault("errors", []).extend(bg_result.get("errors", []))
                    result.setdefault("limitations", []).extend(
                        bg_result.get("limitations", [])
                    )
                except (OSError, ValueError) as e:
                    logger.warning("Background comparison failed: %s", e)
                    result.setdefault("errors", []).append(
                        f"Background comparison failed: {e}"
                    )
    except (OSError, VeritasError) as e:
        result = {
            "status": "failed",
            "anomaly_count": 0,
            "anomalies": [],
            "errors": [str(e)],
            "limitations": [],
        }

    write_json_artifact(output_path, result)
    status = result.get("status", "failed")
    detail = f"figures={result.get('figure_count', 0)} anomalies={result.get('anomaly_count', 0)}"
    if result.get("limitations"):
        detail += f" limitations={len(result['limitations'])}"
    step_status = "ran" if status == "ran" else "failed"
    record_step(
        steps,
        StepResult("visual_image_quality", "图片质量异常检测", step_status, detail),
        progress,
    )
    return steps, {
        "image_quality": {"status": status, "output": str(output_path), **result}
    }


def run_overlap_reuse_detection(
    *,
    workdir: Path,
    force: bool,
    panel_extraction_status: str | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Run cross-panel overlap/reuse detection via tile-level retrieval."""
    steps: list[StepResult] = []
    output_path = resolve_artifact_path(workdir, "overlap_reuse.json")
    if output_path.exists() and not force:
        record_step(
            steps,
            StepResult(
                "visual_overlap_reuse",
                "视觉 Overlap/Reuse 检测",
                "reused",
                "Existing overlap_reuse.json found.",
            ),
            progress,
        )
        return steps, {
            "overlap_reuse": {"status": "reused", "output": str(output_path)}
        }

    emit_step_start(
        progress,
        "visual_overlap_reuse",
        "视觉 Overlap/Reuse 检测",
        "Running tile-level overlap retrieval.",
    )

    panel_evidence_path = resolve_artifact_path(workdir, "panel_evidence.json")
    visual_evidence_path = resolve_artifact_path(workdir, "visual_evidence.json")
    if not panel_evidence_path.exists():
        record_step(
            steps,
            StepResult(
                "visual_overlap_reuse",
                "视觉 Overlap/Reuse 检测",
                "skipped",
                "No panel_evidence.json.",
            ),
            progress,
        )
        return steps, {
            "overlap_reuse": {"status": "skipped", "detail": "no panel evidence"}
        }

    panels = (read_json(panel_evidence_path) or {}).get("panels", [])
    if len(panels) < 2:
        record_step(
            steps,
            StepResult(
                "visual_overlap_reuse",
                "视觉 Overlap/Reuse 检测",
                "skipped",
                f"Only {len(panels)} panel(s).",
            ),
            progress,
        )
        return steps, {
            "overlap_reuse": {"status": "skipped", "detail": "insufficient panels"}
        }

    figures = []
    if visual_evidence_path.exists():
        figures = (read_json(visual_evidence_path) or {}).get("figures", [])

    try:
        from engine.static_audit.tools.overlap_reuse import detect_overlap_reuse

        result = detect_overlap_reuse(panels, figures, workdir=workdir)
    except (OSError, VeritasError) as e:
        result = {
            "status": "failed",
            "relationship_count": 0,
            "relationships": [],
            "errors": [str(e)],
            "limitations": ["overlap_reuse tool raised an exception"],
        }

    write_json_artifact(output_path, result)
    status = result.get("status", "failed")
    detail = f"panels={result.get('panel_count', 0)} tiles={result.get('tile_count', 0)} rels={result.get('relationship_count', 0)}"
    if result.get("limitations"):
        detail += f" limitations={len(result['limitations'])}"
    step_status = "ran" if status in ("ran", "skipped") else "failed"
    record_step(
        steps,
        StepResult(
            "visual_overlap_reuse", "视觉 Overlap/Reuse 检测", step_status, detail
        ),
        progress,
    )
    return steps, {
        "overlap_reuse": {"status": status, "output": str(output_path), **result}
    }


def run_provenance_graph(
    *,
    workdir: Path,
    force: bool,
    allow_env_skip: bool = False,
    panel_extraction_status: str | None = None,
    progress: ProgressCallback | None = None,
    elis_timeout: int | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Build provenance graph from cross-figure content sharing.

    Args:
        elis_timeout: HTTP timeout in seconds for ELIS service calls.
            If None, uses the default (120s).
    """
    steps: list[StepResult] = []
    output_path = resolve_artifact_path(workdir, "provenance_graph.json")
    if output_path.exists() and not force:
        record_step(
            steps,
            StepResult(
                "visual_provenance_graph",
                "溯源图构建",
                "reused",
                "Existing provenance_graph.json found.",
            ),
            progress,
        )
        return steps, {
            "provenance_graph": {"status": "reused", "output": str(output_path)}
        }

    emit_step_start(
        progress,
        "visual_provenance_graph",
        "溯源图构建",
        "Building provenance graph from figure evidence.",
    )

    visual_evidence_path = resolve_artifact_path(workdir, "visual_evidence.json")
    if not visual_evidence_path.exists():
        if panel_extraction_status in ("skipped", "ran"):
            record_step(
                steps,
                StepResult(
                    "visual_provenance_graph",
                    "溯源图构建",
                    "skipped",
                    "No visual evidence from upstream.",
                ),
                progress,
            )
            return steps, {
                "provenance_graph": {
                    "status": "skipped",
                    "detail": "no visual evidence",
                }
            }
        record_step(
            steps,
            StepResult(
                "visual_provenance_graph",
                "溯源图构建",
                "failed",
                "visual_evidence.json not found (upstream dependency).",
            ),
            progress,
        )
        return steps, {
            "provenance_graph": {
                "status": "failed",
                "failure_category": "dependency",
                "detail": "missing visual_evidence.json",
            }
        }

    visual_evidence = read_json(visual_evidence_path) or {}
    figures = visual_evidence.get("figures", [])

    if len(figures) < 2:
        # Legitimate scenario: paper has fewer than 2 figures. Skip without failure.
        record_step(
            steps,
            StepResult(
                "visual_provenance_graph",
                "溯源图构建",
                "skipped",
                f"Paper has {len(figures)} figure(s), need >= 2 for provenance.",
            ),
            progress,
        )
        return steps, {
            "provenance_graph": {"status": "skipped", "detail": "insufficient figures"}
        }

    try:
        from engine.static_audit.tools.provenance_graph import build_provenance_graph

        # Build kwargs, passing elis_timeout if provided
        kwargs: dict[str, Any] = {"workdir": workdir}
        if elis_timeout is not None:
            kwargs["timeout"] = elis_timeout
        result = build_provenance_graph(figures, **kwargs)
    except (OSError, VeritasError) as e:
        result = {
            "status": "failed",
            "failure_category": "runtime",
            "error": str(e),
            "nodes": [],
            "edges": [],
            "statistics": {},
        }

    write_json_artifact(output_path, result)
    status = result.get("status", "failed")
    stats = result.get("statistics", {})
    detail = f"nodes={stats.get('node_count', 0)} edges={stats.get('edge_count', 0)} components={stats.get('component_count', 0)}"
    if result.get("limitations"):
        detail += f" limitations={len(result['limitations'])}"
    failure_category = result.get("failure_category")
    step_status = "ran" if status == "ran" else "failed"
    if (
        status == "failed"
        and failure_category in ("dependency", "environment")
        and allow_env_skip
    ):
        detail = f"SKIPPED ({failure_category}): {detail}"
        step_status = "skipped_with_opt_in"
    record_step(
        steps,
        StepResult("visual_provenance_graph", "溯源图构建", step_status, detail),
        progress,
    )
    return steps, {
        "provenance_graph": {"status": status, "output": str(output_path), **result}
    }
