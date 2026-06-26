"""Completeness findings for figure panels missing source data.

Parses figure panel references from the evidence ledger and full markdown,
compares against source data sheet coverage, and generates summary findings
for uncovered panels.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from engine.static_audit.models import Finding
from engine.static_audit._shared import resolve_artifact_path, read_json


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_missing_source_data_findings(workdir: Path) -> list[Finding]:
    """Generate completeness findings for figure panels without source data sheets."""
    profile = read_json(resolve_artifact_path(workdir, "source_data_profile.json"))
    if not profile or not profile.get("workbooks"):
        return []

    # Collect figure keys covered by source data sheets.
    covered: set[tuple[str, str, str | None]] = set()
    for wb in profile["workbooks"]:
        for sheet in wb.get("sheets", []):
            for key in _parse_sheet_figure_keys(sheet.get("name", "")):
                covered.add(key)

    # Collect figure panel references from the evidence ledger.
    ledger = read_json(resolve_artifact_path(workdir, "evidence_ledger.json"))
    if not ledger:
        return []
    captions = ledger.get("captions", [])

    # Map: (kind, fig_num) -> set of panel letters
    paper_panels: dict[tuple[str, str], set[str]] = {}

    # Pre-pass: identify extended-data figure numbers from main captions.
    ext_data_fig_nums: set[str] = set()
    for cap in captions:
        raw = (cap.get("raw_label", "") or "").replace("\xa0", " ")
        text = cap.get("text", "") or ""
        main_fig_match = re.match(r"(?:Extended Data )?Fig\.\s*(\d+)$", raw)
        if main_fig_match and "|" in text and "See next page" not in text:
            is_ext = (
                "Extended Data" in raw
                or "Extended Data Fig" in text
                or re.search(r"Extended\s+Data\s+Fig", text) is not None
            )
            if is_ext:
                ext_data_fig_nums.add(main_fig_match.group(1))

    logger.debug(
        "source_data_missing: ext_data_fig_nums from main captions: %s",
        sorted(ext_data_fig_nums),
    )

    for cap in captions:
        raw = (cap.get("raw_label", "") or "").replace("\xa0", " ")
        text = cap.get("text", "") or ""

        # Main figure caption: raw_label = "Fig. N" (no panel letter), text has "|"
        main_fig_match = re.match(r"(?:Extended Data )?Fig\.\s*(\d+)$", raw)
        if main_fig_match and "|" in text and "See next page" not in text:
            fig_num = main_fig_match.group(1)
            is_ext = (
                "Extended Data" in raw
                or "Extended Data Fig" in text
                or re.search(r"Extended\s+Data\s+Fig", text) is not None
            )
            kind = "extended_data" if is_ext else "main_figure"
            body = text.split("|", 1)[-1].strip()
            panels = _panels_from_caption_body(body)
            paper_panels.setdefault((kind, fig_num), set()).update(panels)
            logger.debug(
                "source_data_missing: main_caption kind=%s fig=%s panels=%s",
                kind,
                fig_num,
                sorted(panels),
            )

        # Body text reference: raw_label = "Fig. 7d" (with panel letter)
        panel_ref_match = re.match(r"(Extended Data )?Fig\.\s*(\d+)([a-z])$", raw)
        if panel_ref_match:
            fig_num = panel_ref_match.group(2)
            panel = panel_ref_match.group(3)
            is_ext = (
                bool(panel_ref_match.group(1))
                or "Extended Data Fig" in text
                or fig_num in ext_data_fig_nums
            )
            kind = "extended_data" if is_ext else "main_figure"
            paper_panels.setdefault((kind, fig_num), set()).add(panel)

    logger.debug(
        "source_data_missing: paper_panels summary: %d main_figure, %d extended_data; "
        "covered keys: %d",
        sum(1 for k in paper_panels if k[0] == "main_figure"),
        sum(1 for k in paper_panels if k[0] == "extended_data"),
        len(covered),
    )
    # Log per-figure coverage for debug traceability.
    for (kind, fig_num), panels in sorted(paper_panels.items()):
        missing_in_fig = [
            p for p in sorted(panels) if (kind, fig_num, p) not in covered
        ]
        if missing_in_fig:
            logger.debug(
                "source_data_missing: %s fig=%s missing_panels=%s (of %d total)",
                kind,
                fig_num,
                missing_in_fig,
                len(panels),
            )

    # Also scan the full paper markdown for "Fig. Xy" references.
    full_md_path = resolve_artifact_path(workdir, "full.md")
    if full_md_path.exists():
        try:
            full_text = full_md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            full_text = ""
        for m in re.finditer(r"(?:Extended\s+Data\s+)?Fig\.\s*(\d+)([a-z])", full_text):
            prefix = full_text[max(0, m.start() - 20) : m.start()]
            is_ext = "Extended Data" in prefix or "extended data" in prefix.lower()
            kind = "extended_data" if is_ext else "main_figure"
            fig_num = m.group(1)
            panel = m.group(2)
            paper_panels.setdefault((kind, fig_num), set()).add(panel)

    # Generate findings for paper panels not covered by source data.
    raw_findings: list[Finding] = []
    counter = 1
    for (kind, fig_num), panels in sorted(paper_panels.items()):
        for panel in sorted(panels):
            if (kind, fig_num, panel) not in covered:
                if kind == "extended_data":
                    fig_id = f"Extended Data Fig. {fig_num}{panel}"
                else:
                    fig_id = f"Fig. {fig_num}{panel}"
                raw_findings.append(
                    Finding(
                        finding_id=f"COMP-SRC-{counter:03d}",
                        category="source_data_missing",
                        risk_level="medium",
                        summary=f"Figure {fig_id} has no corresponding source data sheet",
                        issue_category="completeness",
                        metadata={
                            "figure_id": fig_id,
                            "kind": kind,
                            "figure_number": fig_num,
                            "panel": panel,
                            "covered_sheets": sorted(
                                f"{k[1]}.{k[2]}" if k[2] else k[1]
                                for k in covered
                                if k[0] == kind and k[1] == fig_num and k[2] is not None
                            ),
                        },
                    )
                )
                counter += 1

    logger.debug(
        "source_data_missing: raw_findings=%d before summary merge",
        len(raw_findings),
    )

    # Group by figure (kind + fig_num) and create summary findings.
    findings: list[Finding] = []
    grouped: dict[tuple[str, str], list[Finding]] = {}
    for f in raw_findings:
        key = (f.metadata["kind"], f.metadata["figure_number"])
        grouped.setdefault(key, []).append(f)

    summary_idx = 1
    for (kind, fig_num), group in sorted(grouped.items()):
        panels = [f.metadata["panel"] for f in group]
        if kind == "extended_data":
            fig_label = f"Extended Data Fig. {fig_num}"
        else:
            fig_label = f"Fig. {fig_num}"
        summary_id = f"SDM-SUMMARY-{summary_idx:03d}"
        findings.append(
            Finding(
                finding_id=summary_id,
                category="source_data_missing",
                risk_level="low",
                summary=f"Figure {fig_label} 缺失 {len(panels)} 个 panel 的 source data: {', '.join(panels)}",
                issue_category="completeness",
                metadata={
                    "figure_label": fig_label,
                    "kind": kind,
                    "figure_number": fig_num,
                    "missing_panels": panels,
                    "original_finding_ids": [f.finding_id for f in group],
                    "merged_figure_panels": [f"{fig_label}{p}" for p in panels],
                },
            )
        )
        logger.debug(
            "source_data_missing: summary %s = %s, merged %d panels: %s",
            summary_id,
            fig_label,
            len(panels),
            panels,
        )
        # Mark original findings as suppressed.
        for f in group:
            f.metadata["suppressed_by"] = summary_id
        findings.extend(group)
        summary_idx += 1

    return findings


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_sheet_figure_keys(sheet_name: str) -> list[tuple[str, str, str | None]]:
    """Extract (kind, figure_number, panel_letter) from a source data sheet name.

    Handles formats beyond what figure_keys_from_sheet_name covers, such as
    comma-separated panels ("fig.7j,k") and ranges ("fig.5 l-n").
    """
    text = re.sub(r"[\s ]+", " ", sheet_name).strip()
    text_lower = text.lower()
    is_extended = "extended data" in text_lower
    kind = "extended_data" if is_extended else "main_figure"
    if is_extended:
        m = re.search(r"extended\s+data\s+fig\.?\s*(\d+)([a-z]?)", text_lower)
    else:
        m = re.search(r"fig\.?\s*(\d+)([a-z]?)", text_lower)
    if not m:
        return []
    fig_num = m.group(1)
    first_panel = m.group(2) or None
    keys: list[tuple[str, str, str | None]] = []
    if first_panel:
        keys.append((kind, fig_num, first_panel))
    else:
        keys.append((kind, fig_num, None))
    rest = text_lower[m.end() :]
    for pm in re.finditer(r"[,]\s*([a-z])", rest):
        keys.append((kind, fig_num, pm.group(1)))
    for pm in re.finditer(r"\band\s+([a-z])", rest):
        keys.append((kind, fig_num, pm.group(1)))
    for pm in re.finditer(r"([a-z])\s*[-–]\s*([a-z])", rest):
        s, e = ord(pm.group(1)), ord(pm.group(2))
        if 0 < e - s < 10:
            for i in range(s, e + 1):
                keys.append((kind, fig_num, chr(i)))
    return keys


def _panels_from_caption_body(body: str) -> set[str]:
    """Extract single-letter panel references from a figure caption body.

    Matches the standard format "a, description. b, description." where panel
    labels appear after sentence-ending punctuation followed by whitespace.
    """
    panels: set[str] = set()
    for m in re.finditer(r"(?<=[\.\;]\s)([a-z](?:\s*,\s*[a-z])*)\s*,", body):
        for letter in re.findall(r"[a-z]", m.group(1)):
            panels.add(letter)
    for m in re.finditer(r"(?<=[\.\;]\s)([a-z])\s*[-–]\s*([a-z])\s*,", body):
        s, e = ord(m.group(1)), ord(m.group(2))
        if 0 < e - s < 10:
            for i in range(s, e + 1):
                panels.add(chr(i))
    return panels
