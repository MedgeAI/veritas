"""Evidence item collection for Veritas static audit report.

Extracts audit artifacts from the workdir and builds a flat list of
``EvidenceItem`` records consumed by the static audit bundle.
"""

from __future__ import annotations

from pathlib import Path

from engine.static_audit.models import EvidenceItem
from engine.static_audit._shared import (
    resolve_artifact_path,
    read_json,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_evidence_items(workdir: Path) -> list[EvidenceItem]:
    """Collect all audit artifacts and visual evidence items from *workdir*.

    Scans deterministic artifact files (``full.md``, ``material_inventory.json``,
    etc.), then augments with figure, panel, source-data, and pair-forensics
    evidence records parsed from their respective JSON outputs.
    """
    items: list[EvidenceItem] = []
    for name, kind in [
        ("full.md", "output_artifact"),
        ("material_inventory.json", "output_artifact"),
        ("agent_material_plan.json", "output_artifact"),
        ("evidence_ledger.json", "output_artifact"),
        ("numeric_forensics.json", "output_artifact"),
        ("paperfraud_rule_matches.json", "output_artifact"),
        ("source_data_profile.json", "output_artifact"),
        ("source_data_findings.json", "output_artifact"),
        ("source_data_pair_forensics.json", "output_artifact"),
        ("exact_image_duplicates.json", "output_artifact"),
        ("image_similarity_candidates.json", "output_artifact"),
        ("visual_evidence.json", "output_artifact"),
        ("panel_evidence.json", "output_artifact"),
        ("visual_copy_move.json", "output_artifact"),
        ("image_relationships.json", "output_artifact"),
        ("visual_findings.json", "output_artifact"),
        ("forged_region_evidence.json", "output_artifact"),
        ("investigation_rounds.jsonl", "output_artifact"),
    ]:
        path = resolve_artifact_path(workdir, name)
        if path.exists():
            items.append(
                EvidenceItem(
                    evidence_id=f"EV-ART-{len(items) + 1:04d}",
                    kind=kind,  # type: ignore[arg-type]
                    source_path=str(path),
                    summary=f"Audit artifact: {name}",
                    metadata={"bytes": path.stat().st_size, "artifact_name": name},
                )
            )

    _extend_with_visual_figures(items, workdir)
    _extend_with_visual_panels(items, workdir)
    _extend_with_source_data_findings(items, workdir)
    _extend_with_pair_forensics_findings(items, workdir)
    return items


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extend_with_visual_figures(
    items: list[EvidenceItem], workdir: Path
) -> None:
    visual_evidence = (
        read_json(resolve_artifact_path(workdir, "visual_evidence.json")) or {}
    )
    for figure in visual_evidence.get("figures") or []:
        if not isinstance(figure, dict):
            continue
        figure_id = str(figure.get("figure_id") or "")
        if not figure_id:
            continue
        items.append(
            EvidenceItem(
                evidence_id=f"EV-FIG-{len(items) + 1:04d}",
                kind="figure",
                source_path=str(figure.get("source_image_path") or ""),
                locator={
                    "figure_id": figure_id,
                    "label": figure.get("label"),
                    "page_number": figure.get("page_number"),
                    "bbox": figure.get("bbox"),
                },
                summary=f"Canonical figure evidence {figure_id}",
                metadata={"figure_id": figure_id, "source": "visual_evidence.json"},
            )
        )


def _extend_with_visual_panels(
    items: list[EvidenceItem], workdir: Path
) -> None:
    panel_evidence = (
        read_json(resolve_artifact_path(workdir, "panel_evidence.json")) or {}
    )
    for panel in panel_evidence.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        panel_id = str(panel.get("panel_id") or "")
        if not panel_id:
            continue
        items.append(
            EvidenceItem(
                evidence_id=f"EV-PANEL-{len(items) + 1:04d}",
                kind="panel",
                source_path=str(panel.get("crop_path") or ""),
                locator={
                    "panel_id": panel_id,
                    "parent_figure_id": panel.get("parent_figure_id"),
                    "label": panel.get("label"),
                    "bbox": panel.get("bbox"),
                },
                summary=f"Canonical panel evidence {panel_id}",
                metadata={
                    "panel_id": panel_id,
                    "parent_figure_id": panel.get("parent_figure_id"),
                    "source": "panel_evidence.json",
                },
            )
        )


def _extend_with_source_data_findings(
    items: list[EvidenceItem], workdir: Path
) -> None:
    source_findings = (
        read_json(resolve_artifact_path(workdir, "source_data_findings.json")) or {}
    )
    for finding in (source_findings.get("priority_findings") or [])[:100]:
        items.append(
            EvidenceItem(
                evidence_id=f"EV-SD-{len(items) + 1:04d}",
                kind="sheet",
                source_path=str(finding.get("workbook", "")),
                locator={
                    "sheet": finding.get("sheet"),
                    "columns": finding.get("column_pair"),
                    "support_rows": finding.get("support_rows")
                    or finding.get("equal_rows"),
                    "overlap_rows": finding.get("overlap_rows"),
                },
                summary=f"Source Data priority finding {finding.get('finding_id')}",
                metadata={"finding_id": finding.get("finding_id")},
            )
        )


def _extend_with_pair_forensics_findings(
    items: list[EvidenceItem], workdir: Path
) -> None:
    pair_forensics = (
        read_json(resolve_artifact_path(workdir, "source_data_pair_forensics.json"))
        or {}
    )
    for finding in (pair_forensics.get("priority_findings") or [])[:100]:
        items.append(
            EvidenceItem(
                evidence_id=f"EV-PF-{len(items) + 1:04d}",
                kind="sheet",
                source_path=str(finding.get("workbook", "")),
                locator={
                    "sheet": finding.get("sheet"),
                    "row_offset": finding.get("row_offset"),
                    "columns": finding.get("columns")
                    or finding.get("column_pair")
                    or finding.get("column"),
                    "support_rows": finding.get("support_rows")
                    or finding.get("matched_pairs")
                    or finding.get("duplicate_row_count"),
                    "overlap_rows": finding.get("overlap_rows")
                    or finding.get("overlap_pairs"),
                },
                summary=f"Source Data pair-forensics finding {finding.get('finding_id')}",
                metadata={
                    "finding_id": finding.get("finding_id"),
                    "source": "source_data_pair_forensics",
                },
            )
        )
