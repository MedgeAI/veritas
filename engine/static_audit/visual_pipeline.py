"""Visual forensics pipeline orchestration for Veritas static audit.

Extracted from orchestrator.py to reduce God Object complexity.
All public names are re-exported via orchestrator for backward compatibility.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Shared utilities (previously in orchestrator.py, now in _shared.py).
# ---------------------------------------------------------------------------
from engine.static_audit._shared import (
    ProgressCallback,
    StepResult,
    emit_step_start,
    read_json,
    record_step,
    resolve_artifact_path,
    write_json_artifact,
)
from engine.static_audit.tools.panel_extraction import (
    build_figure_evidence_from_images,
    build_figure_evidence_from_ledger,
    extract_panels_batch,
    whole_figure_panel,
)
from engine.static_audit.tools.visual_finding_pipeline import (
    build_relationships,
    build_visual_finding_clusters,
    build_visual_findings,
    visual_review_queue,
)


def _visual_status(values: list[str]) -> str:
    if any(value == "ran" for value in values):
        return "ran"
    if any(value == "not_available" for value in values):
        return "not_available"
    if any(value == "failed" for value in values):
        return "failed"
    return "skipped"


def _resolve_workdir_path(workdir: Path, relative_path: str) -> Path | None:
    if not relative_path:
        return None
    candidate = Path(relative_path)
    if not candidate.is_absolute():
        candidate = workdir / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    try:
        if not resolved.is_relative_to(workdir.resolve()):
            return None
    except OSError:
        return None
    return resolved if resolved.exists() else None


def run_visual_panel_extraction(
    *,
    workdir: Path,
    images_dir: Path,
    force: bool,
    progress: ProgressCallback | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Create canonical figure and panel evidence from extracted PDF images."""
    steps: list[StepResult] = []
    figure_output = resolve_artifact_path(workdir, "visual_evidence.json")
    panel_output = resolve_artifact_path(workdir, "panel_evidence.json")
    if figure_output.exists() and panel_output.exists() and not force:
        step = StepResult(
            "visual_panel_extraction",
            "图片 Panel 拆分",
            "reused",
            "Existing visual_evidence.json and panel_evidence.json found.",
        )
        record_step(steps, step, progress)
        return steps, {
            "panel_extraction": {
                "status": "reused",
                "figures_output": str(figure_output),
                "panels_output": str(panel_output),
            }
        }

    if not images_dir.is_dir():
        step = StepResult(
            "visual_panel_extraction",
            "图片 Panel 拆分",
            "skipped",
            "images directory missing.",
        )
        record_step(steps, step, progress)
        return steps, {"panel_extraction": {"status": "skipped", "detail": step.detail}}

    emit_step_start(
        progress,
        "visual_panel_extraction",
        "图片 Panel 拆分",
        "Building canonical figure_evidence and panel_evidence artifacts.",
    )

    evidence_ledger = (
        read_json(resolve_artifact_path(workdir, "evidence_ledger.json")) or {}
    )
    figures = build_figure_evidence_from_ledger(workdir, evidence_ledger)
    if not figures:
        figures = build_figure_evidence_from_images(workdir, images_dir)

    errors: list[str] = []
    limitations: list[str] = []
    panels: list[dict[str, Any]] = []
    extraction_statuses: list[str] = []

    if not figures:
        limitations.append(
            "No extracted figure images were available for panel extraction."
        )

    # Collect (figure_id, absolute_image_path) pairs for figures that exist on disk
    figure_path_pairs: list[tuple[str, Path]] = []
    figure_by_id: dict[str, dict[str, Any]] = {}
    for figure in figures:
        fid = str(figure.get("figure_id") or "")
        figure_by_id[fid] = figure
        source_path = _resolve_workdir_path(
            workdir, str(figure.get("source_image_path") or "")
        )
        if source_path is None:
            errors.append(f"Figure image not found: {figure.get('source_image_path')}")
            extraction_statuses.append("failed")
            continue
        figure_path_pairs.append((fid, source_path))

    # Batch YOLOv5 panel extraction — single subprocess call for all figures
    if figure_path_pairs:
        # Clean stale panel crops from previous runs to prevent orphans
        panels_dir = workdir / "panels"
        if panels_dir.is_dir():
            shutil.rmtree(str(panels_dir), ignore_errors=True)
        batch_panels = extract_panels_batch(figure_path_pairs, output_dir=workdir)
        extraction_statuses.append("ran" if any(batch_panels.values()) else "skipped")
    else:
        batch_panels = {}

    # Distribute panels to figures; fallback for figures with zero panels
    for fid, source_path in figure_path_pairs:
        figure = figure_by_id.get(fid)
        if figure is None:
            continue
        result_panels = batch_panels.get(fid, [])
        if not result_panels:
            fallback_panel = whole_figure_panel(
                figure, workdir=workdir, output_dir=workdir
            )
            if fallback_panel:
                result_panels = [fallback_panel]
                limitations.append(
                    f"{fid}: YOLOv5 panel extraction did not detect panels; whole-figure fallback panel was created."
                )

        panels.extend(result_panels)
        figure["panel_count"] = len(result_panels)
        metadata = (
            figure.get("metadata") if isinstance(figure.get("metadata"), dict) else {}
        )
        figure["metadata"] = {
            **metadata,
            "panel_extraction_status": "ran" if result_panels else "skipped",
        }

    status = "ran" if figures else "skipped"
    if figures and not panels:
        status = _visual_status(extraction_statuses)
        if status == "ran":
            status = "warning"

    visual_evidence = {
        "schema_version": "1.0",
        "created_by": "engine/static_audit/orchestrator.py",
        "status": status,
        "figure_count": len(figures),
        "panel_count": len(panels),
        "figures": figures,
        "errors": errors,
        "limitations": limitations,
    }
    panel_evidence = {
        "schema_version": "1.0",
        "created_by": "engine/static_audit/orchestrator.py",
        "status": status,
        "figure_count": len(figures),
        "panel_count": len(panels),
        "panels": panels,
        "errors": errors,
        "limitations": limitations,
    }
    write_json_artifact(figure_output, visual_evidence)
    write_json_artifact(panel_output, panel_evidence)

    detail = f"figures={len(figures)} panels={len(panels)}"
    if limitations:
        detail += f" limitations={len(limitations)}"
    step_status = (
        "ran"
        if status in {"ran", "warning"}
        else "warning"
        if status in {"not_available", "failed"}
        else status
    )
    step = StepResult("visual_panel_extraction", "图片 Panel 拆分", step_status, detail)
    record_step(steps, step, progress)
    return steps, {
        "panel_extraction": {
            "status": status,
            "figures_output": str(figure_output),
            "panels_output": str(panel_output),
            "figure_count": len(figures),
            "panel_count": len(panels),
            "errors": errors,
            "limitations": limitations,
        }
    }


def _read_visual_copy_move_outputs(workdir: Path) -> dict[str, Any]:
    relationships: list[dict[str, Any]] = []
    statuses: list[str] = []
    errors: list[str] = []
    limitations: list[str] = []
    paths = []
    baseline = resolve_artifact_path(workdir, "visual_copy_move.json")
    if baseline.exists():
        paths.append(baseline)
    paths.extend(
        sorted(
            (resolve_artifact_path(workdir, "investigation")).rglob(
                "visual_copy_move.json"
            )
        )
        if (resolve_artifact_path(workdir, "investigation")).exists()
        else []
    )
    for path in paths:
        data = read_json(path) or {}
        statuses.append(str(data.get("status") or "unknown"))
        relationships.extend(
            item for item in (data.get("relationships") or []) if isinstance(item, dict)
        )
        errors.extend(str(item) for item in (data.get("errors") or []))
        limitations.extend(str(item) for item in (data.get("limitations") or []))
    return {
        "status": _visual_status(statuses) if statuses else "skipped",
        "relationships": relationships,
        "errors": errors,
        "limitations": limitations,
        "source_paths": [str(path) for path in paths],
    }


def _read_overlap_reuse_outputs(workdir: Path) -> dict[str, Any]:
    """Merge baseline + investigation overlap_reuse.json outputs."""
    relationships: list[dict[str, Any]] = []
    statuses: list[str] = []
    limitations: list[str] = []
    paths = []
    baseline = resolve_artifact_path(workdir, "overlap_reuse.json")
    if baseline.exists():
        paths.append(baseline)
    inv_dir = resolve_artifact_path(workdir, "investigation")
    if inv_dir.exists():
        paths.extend(sorted(inv_dir.rglob("overlap_reuse.json")))
    for path in paths:
        data = read_json(path) or {}
        statuses.append(str(data.get("status") or "unknown"))
        relationships.extend(
            item for item in (data.get("relationships") or []) if isinstance(item, dict)
        )
        limitations.extend(str(item) for item in (data.get("limitations") or []))
    return {
        "status": _visual_status(statuses) if statuses else "skipped",
        "relationships": relationships,
        "limitations": limitations,
        "source_paths": [str(path) for path in paths],
    }


def _read_image_similarity_outputs(workdir: Path) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    paths = []
    baseline = resolve_artifact_path(workdir, "image_similarity_candidates.json")
    if baseline.exists():
        paths.append(baseline)
    paths.extend(
        sorted(
            (resolve_artifact_path(workdir, "investigation")).rglob(
                "image_similarity_candidates.json"
            )
        )
        if (resolve_artifact_path(workdir, "investigation")).exists()
        else []
    )
    for path in paths:
        data = read_json(path) or {}
        candidates.extend(
            item for item in (data.get("candidates") or []) if isinstance(item, dict)
        )
    return {"candidates": candidates, "source_paths": [str(path) for path in paths]}


def run_visual_finding_pipeline(
    *,
    workdir: Path,
    force: bool,
    progress: ProgressCallback | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Aggregate visual tool outputs into canonical relationships/findings."""
    steps: list[StepResult] = []
    relationships_output = resolve_artifact_path(workdir, "image_relationships.json")
    findings_output = resolve_artifact_path(workdir, "visual_findings.json")
    if relationships_output.exists() and findings_output.exists() and not force:
        step = StepResult(
            "visual_finding_pipeline",
            "视觉证据聚合管线",
            "reused",
            "Existing image_relationships.json and visual_findings.json found.",
        )
        record_step(steps, step, progress)
        return steps, {
            "finding_pipeline": {
                "status": "reused",
                "relationships_output": str(relationships_output),
                "findings_output": str(findings_output),
            }
        }

    panel_doc = read_json(resolve_artifact_path(workdir, "panel_evidence.json")) or {}
    panels = [
        item for item in (panel_doc.get("panels") or []) if isinstance(item, dict)
    ]
    forged_region_doc = (
        read_json(resolve_artifact_path(workdir, "forged_region_evidence.json")) or {}
    )
    forged_region_items = [
        item
        for item in (forged_region_doc.get("forged_region_evidence") or [])
        if isinstance(item, dict)
    ]
    if not panels and not forged_region_items:
        relationship_doc = {
            "schema_version": "1.0",
            "created_by": "engine/static_audit/orchestrator.py",
            "status": "skipped",
            "relationship_count": 0,
            "relationships": [],
            "errors": [],
            "limitations": ["panel_evidence.json is missing or contains no panels."],
        }
        finding_doc = {
            "schema_version": "1.0",
            "created_by": "engine/static_audit/orchestrator.py",
            "status": "skipped",
            "finding_count": 0,
            "finding_cluster_count": 0,
            "review_queue_count": 0,
            "findings": [],
            "finding_clusters": [],
            "review_queue": [],
            "errors": [],
            "limitations": relationship_doc["limitations"],
        }
        write_json_artifact(relationships_output, relationship_doc)
        write_json_artifact(findings_output, finding_doc)
        step = StepResult(
            "visual_finding_pipeline",
            "视觉证据聚合管线",
            "skipped",
            relationship_doc["limitations"][0],
        )
        record_step(steps, step, progress)
        return steps, {
            "finding_pipeline": {
                "status": "skipped",
                "relationships_output": str(relationships_output),
                "findings_output": str(findings_output),
            }
        }

    emit_step_start(
        progress,
        "visual_finding_pipeline",
        "视觉证据聚合管线",
        "Aggregating visual relationships and findings.",
    )
    copy_move_result = _read_visual_copy_move_outputs(workdir)
    exact_duplicates = (
        read_json(resolve_artifact_path(workdir, "exact_image_duplicates.json")) or {}
    )
    dhash_candidates = _read_image_similarity_outputs(workdir)
    overlap_reuse_result = _read_overlap_reuse_outputs(workdir)
    relationships = build_relationships(
        copy_move_result=copy_move_result,
        exact_duplicates=exact_duplicates,
        dhash_candidates=dhash_candidates,
        panel_evidence=panels,
        overlap_reuse_result=overlap_reuse_result,
    )
    findings = build_visual_findings(
        relationships,
        panel_evidence=panels,
        forged_region_evidence=forged_region_items,
    )
    finding_clusters = build_visual_finding_clusters(findings)
    review_queue = visual_review_queue(finding_clusters)
    limitations = [
        "Visual relationships are screening signals and require manual review before escalation.",
    ]
    limitations.extend(copy_move_result.get("limitations") or [])
    limitations.extend(overlap_reuse_result.get("limitations") or [])
    if forged_region_items:
        limitations.append(
            "TruFor forged-region findings are deep-learning screening signals; "
            "a suspicious integrity_score does not constitute proof of manipulation "
            "and requires human review of the original image and localization heatmap."
        )
    errors = list(copy_move_result.get("errors") or [])

    relationship_doc = {
        "schema_version": "1.0",
        "created_by": "engine/static_audit/orchestrator.py",
        "status": "ran",
        "panel_count": len(panels),
        "relationship_count": len(relationships),
        "relationships": relationships,
        "source_artifacts": {
            "copy_move": copy_move_result.get("source_paths") or [],
            "image_similarity": dhash_candidates.get("source_paths") or [],
            "exact_duplicates": str(
                resolve_artifact_path(workdir, "exact_image_duplicates.json")
            )
            if (resolve_artifact_path(workdir, "exact_image_duplicates.json")).exists()
            else None,
            "overlap_reuse": str(resolve_artifact_path(workdir, "overlap_reuse.json"))
            if (resolve_artifact_path(workdir, "overlap_reuse.json")).exists()
            else None,
            "tru_for": str(
                resolve_artifact_path(workdir, "forged_region_evidence.json")
            )
            if (resolve_artifact_path(workdir, "forged_region_evidence.json")).exists()
            else None,
        },
        "errors": errors,
        "limitations": limitations,
    }
    finding_doc = {
        "schema_version": "1.0",
        "created_by": "engine/static_audit/orchestrator.py",
        "status": "ran",
        "relationship_count": len(relationships),
        "finding_count": len(findings),
        "finding_cluster_count": len(finding_clusters),
        "review_queue_count": len(review_queue),
        "findings": findings,
        "finding_clusters": finding_clusters,
        "review_queue": review_queue,
        "errors": errors,
        "limitations": limitations,
    }
    write_json_artifact(relationships_output, relationship_doc)
    write_json_artifact(findings_output, finding_doc)
    step = StepResult(
        "visual_finding_pipeline",
        "视觉证据聚合管线",
        "ran",
        f"relationships={len(relationships)} visual_findings={len(findings)} visual_review_queue={len(review_queue)}",
    )
    record_step(steps, step, progress)
    return steps, {
        "finding_pipeline": {
            "status": "ran",
            "relationships_output": str(relationships_output),
            "findings_output": str(findings_output),
            "relationship_count": len(relationships),
            "finding_count": len(findings),
            "finding_cluster_count": len(finding_clusters),
            "review_queue_count": len(review_queue),
            "copy_move_status": copy_move_result.get("status"),
        }
    }


def run_tru_for_detection(
    *,
    workdir: Path,
    force: bool,
    allow_env_skip: bool = False,
    panel_extraction_status: str | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Run TruFor forgery detection on all figures."""
    steps: list[StepResult] = []
    output_path = resolve_artifact_path(workdir, "forged_region_evidence.json")
    if output_path.exists() and not force:
        record_step(
            steps,
            StepResult(
                "visual_tru_for",
                "TruFor 深度学习伪造检测",
                "reused",
                "Existing forged_region_evidence.json found.",
            ),
            progress,
        )
        return steps, {"tru_for": {"status": "reused", "output": str(output_path)}}

    emit_step_start(
        progress,
        "visual_tru_for",
        "TruFor 深度学习伪造检测",
        "Running TruFor forgery detection on all figures.",
    )

    visual_evidence_path = resolve_artifact_path(workdir, "visual_evidence.json")
    if not visual_evidence_path.exists():
        # If panel_extraction was skipped or ran with no figures, this is a legitimate skip.
        if panel_extraction_status in ("skipped", "ran"):
            record_step(
                steps,
                StepResult(
                    "visual_tru_for",
                    "TruFor 深度学习伪造检测",
                    "skipped",
                    "No visual evidence from upstream.",
                ),
                progress,
            )
            return steps, {
                "tru_for": {"status": "skipped", "detail": "no visual evidence"}
            }
        # Otherwise, it's a dependency failure.
        record_step(
            steps,
            StepResult(
                "visual_tru_for",
                "TruFor 深度学习伪造检测",
                "failed",
                "visual_evidence.json not found (upstream dependency).",
            ),
            progress,
        )
        return steps, {
            "tru_for": {
                "status": "failed",
                "failure_category": "dependency",
                "detail": "missing visual_evidence.json",
            }
        }

    visual_evidence = read_json(visual_evidence_path) or {}
    figures = visual_evidence.get("figures", [])

    if not figures:
        # Legitimate scenario: paper has no figures. Skip without failure.
        record_step(
            steps,
            StepResult(
                "visual_tru_for",
                "TruFor 深度学习伪造检测",
                "skipped",
                "Paper has no figures.",
            ),
            progress,
        )
        return steps, {
            "tru_for": {"status": "skipped", "detail": "no figures in paper"}
        }

    try:
        from engine.static_audit.tools.tru_for import run_tru_for

        result = run_tru_for(figures, workdir=workdir)
    except Exception as e:
        result = {
            "status": "failed",
            "failure_category": "runtime",
            "forged_region_evidence": [],
            "errors": [str(e)],
            "limitations": [],
        }

    write_json_artifact(output_path, result)
    status = result.get("status", "failed")
    failure_category = result.get("failure_category")

    # Environment failures are only skippable with explicit opt-in
    if status == "failed" and failure_category == "environment" and not allow_env_skip:
        detail = f"FAILED (environment): {'; '.join(result.get('errors', []))}"
        record_step(
            steps,
            StepResult("visual_tru_for", "TruFor 深度学习伪造检测", "failed", detail),
            progress,
        )
        return steps, {
            "tru_for": {
                "status": "failed",
                "failure_category": failure_category,
                "output": str(output_path),
                **result,
            }
        }

    detail = f"figures={result.get('figure_count', 0)} forged_regions={result.get('forged_region_count', 0)} suspicious={result.get('suspicious_count', 0)}"
    if result.get("limitations"):
        detail += f" limitations={len(result['limitations'])}"
    step_status = "ran" if status == "ran" else "failed"
    if status == "failed" and failure_category == "environment" and allow_env_skip:
        detail = f"SKIPPED (environment): {'; '.join(result.get('errors', []))}"
        step_status = "skipped_with_opt_in"
    record_step(
        steps,
        StepResult("visual_tru_for", "TruFor 深度学习伪造检测", step_status, detail),
        progress,
    )
    return steps, {"tru_for": {"status": status, "output": str(output_path), **result}}


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
        from engine.static_audit.tools.image_quality import run_image_quality

        result = run_image_quality(figures, workdir=workdir)
    except Exception as e:
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
    except Exception as e:
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
) -> tuple[list[StepResult], dict[str, Any]]:
    """Build provenance graph from cross-figure content sharing."""
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

        result = build_provenance_graph(figures, workdir=workdir)
    except Exception as e:
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


def run_sila_dense_detection(
    *,
    workdir: Path,
    force: bool,
    allow_env_skip: bool = False,
    panel_extraction_status: str | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[StepResult], dict[str, Any]]:
    """Run SILA dense copy-move detection via Docker."""
    steps: list[StepResult] = []
    output_path = resolve_artifact_path(workdir, "visual_copy_move_dense.json")
    if output_path.exists() and not force:
        record_step(
            steps,
            StepResult(
                "visual_copy_move_dense",
                "SILA Dense Copy-Move",
                "reused",
                "Existing visual_copy_move_dense.json found.",
            ),
            progress,
        )
        return steps, {"sila_dense": {"status": "reused", "output": str(output_path)}}

    emit_step_start(
        progress,
        "visual_copy_move_dense",
        "SILA Dense Copy-Move",
        "Running SILA dense copy-move detection via Docker.",
    )

    panel_evidence_path = resolve_artifact_path(workdir, "panel_evidence.json")
    if not panel_evidence_path.exists():
        if panel_extraction_status in ("skipped", "ran"):
            record_step(
                steps,
                StepResult(
                    "visual_copy_move_dense",
                    "SILA Dense Copy-Move",
                    "skipped",
                    "No panel evidence from upstream.",
                ),
                progress,
            )
            return steps, {
                "sila_dense": {"status": "skipped", "detail": "no panel evidence"}
            }
        record_step(
            steps,
            StepResult(
                "visual_copy_move_dense",
                "SILA Dense Copy-Move",
                "failed",
                "panel_evidence.json not found (upstream dependency).",
            ),
            progress,
        )
        return steps, {
            "sila_dense": {
                "status": "failed",
                "failure_category": "dependency",
                "detail": "missing panel_evidence.json",
            }
        }

    panel_evidence = read_json(panel_evidence_path) or {}
    panels = panel_evidence.get("panels", [])

    visual_evidence_path = resolve_artifact_path(workdir, "visual_evidence.json")
    visual_evidence = (
        read_json(visual_evidence_path) or {} if visual_evidence_path.exists() else {}
    )
    figures = visual_evidence.get("figures", [])

    if not panels:
        # Legitimate scenario: no panels extracted (paper has no figures or extraction found none).
        record_step(
            steps,
            StepResult(
                "visual_copy_move_dense",
                "SILA Dense Copy-Move",
                "skipped",
                "No panels to process.",
            ),
            progress,
        )
        return steps, {"sila_dense": {"status": "skipped", "detail": "no panels"}}

    try:
        from engine.static_audit.tools.sila_dense import detect_sila_dense

        result = detect_sila_dense(panels, figures, workdir=workdir)
    except Exception as e:
        result = {
            "status": "failed",
            "failure_category": "runtime",
            "relationships": [],
            "errors": [str(e)],
            "limitations": [],
        }

    write_json_artifact(output_path, result)
    status = result.get("status", "failed")
    failure_category = result.get("failure_category")

    # Environment failures are only skippable with explicit opt-in
    if status == "failed" and failure_category == "environment" and not allow_env_skip:
        detail = f"FAILED (environment): {'; '.join(result.get('errors', []))}"
        record_step(
            steps,
            StepResult(
                "visual_copy_move_dense", "SILA Dense Copy-Move", "failed", detail
            ),
            progress,
        )
        return steps, {
            "sila_dense": {
                "status": "failed",
                "failure_category": failure_category,
                "output": str(output_path),
                **result,
            }
        }

    detail = f"panels={result.get('panel_count', 0)} relationships={result.get('relationship_count', 0)}"
    if result.get("limitations"):
        detail += f" limitations={len(result['limitations'])}"
    step_status = "ran" if status == "ran" else "failed"
    if status == "failed" and failure_category == "environment" and allow_env_skip:
        detail = f"SKIPPED (environment): {'; '.join(result.get('errors', []))}"
        step_status = "skipped_with_opt_in"
    record_step(
        steps,
        StepResult(
            "visual_copy_move_dense", "SILA Dense Copy-Move", step_status, detail
        ),
        progress,
    )
    return steps, {
        "sila_dense": {"status": status, "output": str(output_path), **result}
    }
