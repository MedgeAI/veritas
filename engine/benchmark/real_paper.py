"""Config-driven scoring of a REAL PubPeer-flagged paper — the headline test unit.

Adding a real paper to VeritasBench should be a config, not a bespoke script. A `RealPaperCase`
declares the paper (DOI + local data dir) and its PubPeer-confirmed dirty source-data sheets;
`score_real_paper` then does the "一鱼两吃" (one fish, two dishes):

  RECALL  did the auditor flag each PubPeer-confirmed dirty sheet (real fabrication, not our
          injection recipe -> a valid held-out generalisation signal).
  FAR     every OTHER sheet in the same paper's source data is presumed benign; its real-numeric
          column pairs are matched-clean controls. Flagging one is a false accusation.

The Springer supplementary URL rule (validated on CNS-058 and paper2) is derived from the DOI:
  DOI 10.1038/s{J}-{Y}-{N}-{v}  ->  file prefix  {J}_{Y}_{int(N)}   (N has leading zeros stripped,
  e.g. 02253 -> 2253, 01321 -> 1321), at
  https://static-content.springer.com/esm/art%3A{doi-with %2F}/MediaObjects/{prefix}_MOESM{k}_ESM.xlsx

Downloading is network I/O; keep it in scripts (call `download_source_data` explicitly), not in
the scoring path, so scoring stays pure over already-local files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from engine.benchmark.metrics import ClaimPrediction, main_table_row
from engine.env import real_papers_root
from engine.static_audit.tools.source_data_findings import (
    duplicate_column_findings,
    fixed_relationship_findings,
    parse_workbook_vectors,
)
from engine.static_audit.tools.source_data_pair_forensics import (
    PairForensicsParams,
    duplicate_row_vector_findings,
    paired_difference_spread_findings,
    paired_ratio_reuse_findings,
    row_offset_scalar_findings,
)
from engine.twins.matched_clean import CleanControl, enumerate_clean_controls, far, flagged_pairs

_PARAMS = PairForensicsParams(min_pairs=8, min_support=0.95, ratio_places=4, max_offset=100,
                              max_findings_per_category=200, min_duplicate_row_width=2)


def sanitize_doi(doi: str) -> str:
    """DOI -> a filesystem-safe token ('/' -> '_'), for the shared per-paper directory name."""
    return doi.replace("/", "_")


def case_data_dir(doi: str, *, root: Path | str | None = None) -> Path:
    """Canonical shared source-data dir for a paper: <root>/<sanitized-doi>/source_data.

    The DOI alone is the directory key (no human slug — see house convention). root defaults to
    engine.env.real_papers_root() so every window/host resolves the same shared location
    (override centrally via VERITAS_REAL_PAPERS_ROOT).
    """
    base = Path(root) if root is not None else real_papers_root()
    return base / sanitize_doi(doi) / "source_data"


@dataclass(frozen=True)
class DirtyLocus:
    """One PubPeer-confirmed source-data fabrication, mapped to its workbook/sheet."""

    workbook: str          # MOESM basename
    sheet: str
    claim_type: str        # source_data.*
    comment_id: str        # PubPeer ref


@dataclass(frozen=True)
class RealPaperCase:
    paper_id: str
    doi: str
    data_dir: str          # local dir holding the downloaded MOESM xlsx
    dirty: tuple[DirtyLocus, ...] = field(default_factory=tuple)


def springer_prefix(doi: str) -> str:
    """10.1038/s41588-025-02253-8 -> '41588_2025_2253'.

    The DOI carries a 3-digit year segment (025 -> 2025, 023 -> 2023) and a zero-padded article
    number (02253 -> 2253); the supplementary file prefix uses the 4-digit year and the number
    with leading zeros stripped.
    """
    m = re.search(r"s(\d+)-(\d+)-(\d+)", doi)
    if not m:
        raise ValueError(f"unrecognised Springer DOI: {doi!r}")
    journal, year, num = m.groups()
    return f"{journal}_{2000 + int(year)}_{int(num)}"


def springer_moesm_url(doi: str, k: int, ext: str = "xlsx") -> str:
    prefix = springer_prefix(doi)
    art = "art%3A" + quote(doi, safe="")
    return (f"https://static-content.springer.com/esm/{art}/MediaObjects/"
            f"{prefix}_MOESM{k}_ESM.{ext}")


def _all_findings(sv) -> list[dict]:
    if sv is None:
        return []
    return (
        duplicate_column_findings(sv, 8, 0.95, 200)
        + fixed_relationship_findings(sv, 8, 0.95, 200)
        + row_offset_scalar_findings(sv, _PARAMS)
        + paired_ratio_reuse_findings(sv, _PARAMS)
        + duplicate_row_vector_findings(sv, _PARAMS)
        + paired_difference_spread_findings(sv, _PARAMS)
    )


def _sheet_vectors(workbook: Path, sheet: str):
    if not workbook.exists():
        return None
    for sv in parse_workbook_vectors(workbook):
        if sv.sheet == sheet:
            return sv
    return None


def score_real_paper(case: RealPaperCase) -> dict:
    """Recall (over dirty sheets) + FAR (over benign column-pair controls) + a main-table row."""
    data = Path(case.data_dir)
    dirty_sheets = {(d.workbook, d.sheet) for d in case.dirty}

    dirty_preds, dirty_rows = [], []
    for d in case.dirty:
        sv = _sheet_vectors(data / d.workbook, d.sheet)
        cats = sorted({f.get("category") for f in _all_findings(sv)} - {None})
        detected = bool(cats)
        dirty_preds.append(ClaimPrediction(f"{case.paper_id}::{d.sheet}", "dirty",
                                           predicted_flag=detected, confidence=1.0 if detected else 0.0,
                                           evidence_correct=detected))
        dirty_rows.append({"sheet": d.sheet, "pubpeer": d.comment_id, "claim_type": d.claim_type,
                           "detected": detected, "categories": cats})

    controls: list[CleanControl] = []
    flagged: set[frozenset[str]] = set()
    for wb_path in sorted(data.glob("*.xlsx")):
        for sv in parse_workbook_vectors(wb_path):
            if (wb_path.name, sv.sheet) in dirty_sheets:
                continue
            controls.extend(enumerate_clean_controls(wb_path, sv.sheet, min_overlap=8))
            flagged |= flagged_pairs(_all_findings(sv))
    far_result = far(controls, flagged)

    clean_preds = [
        ClaimPrediction(f"{case.paper_id}::clean::{c.workbook}:{c.sheet}:{c.col_a}-{c.col_b}", "clean",
                        predicted_flag=(c.pair_key in flagged),
                        confidence=1.0 if c.pair_key in flagged else 0.0)
        for c in controls
    ]

    predictions = dirty_preds + clean_preds
    return {
        "paper_id": case.paper_id,
        "doi": case.doi,
        "recall": {"dirty_sheets": len(case.dirty),
                   "detected": sum(r["detected"] for r in dirty_rows), "rows": dirty_rows},
        "far": far_result,
        "controls": controls,
        "predictions": predictions,          # dirty + clean ClaimPredictions, for cross-paper pooling
        "main_table_row": main_table_row(predictions),
    }
