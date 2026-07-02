from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from engine.static_audit._shared import (
    ProgressCallback,
    StepResult,
    WET_LAB_TYPES,
    emit_step_start,
    read_json,
    record_step,
    resolve_artifact_path,
    write_json_artifact,
)
from engine.static_audit.tools.visual_finding_pipeline import (
    build_relationships,
    build_visual_finding_clusters,
    build_visual_findings,
    visual_review_queue,
)
from engine.static_audit.visual_pipeline.provenance_relationships import (
    write_provenance_relationship_artifacts,
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


def _cleanup_unused_overlays(
    workdir: Path, finding_doc: dict[str, Any]
) -> dict[str, Any]:
    """Delete overlay PNGs not referenced by review_queue entries.

    Scans ``copy_move_elis/single/`` and ``copy_move_elis/cross/`` for PNG
    files and removes any that are not cited by an ``overlay_path`` in the
    finding document's ``review_queue``.  Returns a stats dict.
    """
    referenced: set[Path] = set()
    for item in finding_doc.get("review_queue") or []:
        raw = item.get("overlay_path") if isinstance(item, dict) else None
        if not raw:
            continue
        p = Path(str(raw))
        if not p.is_absolute():
            p = workdir / p
        try:
            referenced.add(p.resolve())
        except OSError:
            referenced.add(p)

    deleted = 0
    scanned = 0
    for subdir_name in ("single", "cross"):
        overlay_dir = workdir / "copy_move_elis" / subdir_name
        if not overlay_dir.is_dir():
            continue
        for png in sorted(overlay_dir.glob("*.png")):
            scanned += 1
            try:
                resolved = png.resolve()
            except OSError:
                continue
            if resolved not in referenced:
                try:
                    png.unlink()
                    deleted += 1
                except OSError as exc:
                    logger.warning(
                        "Failed to remove unreferenced overlay %s: %s", png, exc
                    )

    if deleted:
        logger.info(
            "Cleaned up %d unreferenced overlay(s) (scanned %d).", deleted, scanned
        )

    return {"deleted_count": deleted, "scanned_count": scanned}


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
    dhash_candidates = _read_image_similarity_outputs(workdir)
    overlap_reuse_result = _read_overlap_reuse_outputs(workdir)

    # Build panel → classification lookup for wet-lab filtering
    panel_cls_lookup: dict[str, str] = {}
    for p in panels:
        if isinstance(p, dict):
            pid = p.get("panel_id", "")
            cls = p.get("panel_classification", "unknown")
            if pid:
                panel_cls_lookup[pid] = cls

    def _is_wet_lab_panel(panel_id: str) -> bool:
        """Return True if panel is wet_lab, mixed, or unknown (unclassified)."""
        cls = panel_cls_lookup.get(panel_id, "unknown")
        return cls in WET_LAB_TYPES or cls == "unknown"

    def _filter_wet_lab(rels: list[dict]) -> list[dict]:
        """Keep only relationships where both panels are wet-lab relevant."""
        return [
            r
            for r in rels
            if _is_wet_lab_panel(r.get("source_panel_id", ""))
            and _is_wet_lab_panel(r.get("target_panel_id", ""))
        ]

    # Filter copy-move, dhash, overlap_reuse to wet-lab panels only
    if copy_move_result:
        copy_move_result = dict(copy_move_result)
        copy_move_result["relationships"] = _filter_wet_lab(
            copy_move_result.get("relationships", [])
        )
    if dhash_candidates:
        dhash_candidates = dict(dhash_candidates)
        dhash_candidates["candidates"] = _filter_wet_lab(
            dhash_candidates.get("candidates", [])
        )
    if overlap_reuse_result:
        overlap_reuse_result = dict(overlap_reuse_result)
        overlap_reuse_result["relationships"] = _filter_wet_lab(
            overlap_reuse_result.get("relationships", [])
        )

    relationships = build_relationships(
        copy_move_result=copy_move_result,
        dhash_candidates=dhash_candidates,
        panel_evidence=panels,
        overlap_reuse_result=overlap_reuse_result,
    )
    findings = build_visual_findings(
        relationships,
        panel_evidence=panels,
        forged_region_evidence=forged_region_items,
    )

    # Count skipped relationships and TruFor findings due to code-generated modality
    skipped_relationships = [r for r in relationships if "skipped" in r]
    skipped_trufor = [
        f for f in forged_region_items if isinstance(f, dict) and "skipped" in f
    ]
    skipped_panels = set()
    for rel in skipped_relationships:
        skipped_panels.add(rel.get("source_panel_id", ""))
        skipped_panels.add(rel.get("target_panel_id", ""))
    for fre in skipped_trufor:
        skipped_panels.add(str(fre.get("figure_id", "")))
    skipped_panels.discard("")

    finding_clusters = build_visual_finding_clusters(findings)
    review_queue = visual_review_queue(finding_clusters)
    limitations = [
        "Visual relationships are screening signals and require manual review before escalation.",
    ]
    provenance_graph = (
        read_json(resolve_artifact_path(workdir, "provenance_graph.json")) or {}
    )
    relationship_findings: list[dict[str, Any]] = []
    provenance_filtered: dict[str, Any] = {}
    if provenance_graph:
        (
            relationship_findings,
            _relationship_doc,
            provenance_filtered,
        ) = write_provenance_relationship_artifacts(workdir, provenance_graph)
        findings.extend(relationship_findings)
        if relationship_findings:
            start_index = len(review_queue) + 1
            for index, finding in enumerate(relationship_findings, start=start_index):
                review_queue.append(
                    {
                        "task_id": f"VRT-{index:03d}",
                        "priority": finding.get("risk_level", "medium"),
                        "cluster_id": None,
                        "category": finding.get("category"),
                        "scope": "cross_figure",
                        "figure_ids": [
                            finding.get("source_figure"),
                            finding.get("target_figure"),
                        ],
                        "finding_count": 1,
                        "relationship_count": 1,
                        "panel_extraction_quality": "figure_level",
                        "question": finding.get("review_question"),
                        "evidence_refs": finding.get("evidence_refs") or [],
                        "representative_finding_ids": [finding.get("finding_id")],
                    }
                )
        elif provenance_filtered.get("total_edges", 0) > 0:
            limitations.append(
                "Provenance graph produced edges, but none passed the configured relationship threshold."
            )
    if len(skipped_panels) > 0:
        limitations.append(
            f"{len(skipped_panels)} panels skipped due to code-generated modality (Graphs/Flow Cytometry); "
            f"only exact_duplicate (SHA-256) retained for these modalities."
        )
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
        "visual_relationship_finding_count": len(relationship_findings),
        "findings": findings,
        "finding_clusters": finding_clusters,
        "review_queue": review_queue,
        "provenance_edge_filter": provenance_filtered,
        "errors": errors,
        "limitations": limitations,
    }
    write_json_artifact(relationships_output, relationship_doc)
    write_json_artifact(findings_output, finding_doc)

    cleanup_stats = _cleanup_unused_overlays(workdir, finding_doc)
    if cleanup_stats["deleted_count"] > 0:
        limitations.append(
            f"Removed {cleanup_stats['deleted_count']} unreferenced overlay PNG(s) "
            f"from copy_move_elis/ ({cleanup_stats['scanned_count']} scanned)."
        )
        # Re-write findings with updated limitations
        finding_doc["limitations"] = limitations
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
            "visual_relationship_finding_count": len(relationship_findings),
            "provenance_edge_filter": provenance_filtered,
            "copy_move_status": copy_move_result.get("status"),
            "overlay_cleanup": cleanup_stats,
        }
    }
