"""CNS-058 synthetic benchmark case: dirty twins + matched-clean controls + a real main-table row.

Proves twin generation generalises past CNS-098 AND that FAR is measurable on a second mother:

  DIRTY   two injection sites (I->AG, K->AJ) x three classes = 6 injected twins, each verified
          detectable by the numeric detectors.
  CLEAN   every other real-numeric column pair in the pristine substrate table = a benign
          "could these be a duplicate/ratio?" control (genuine, non-retracted paper => clean).
  SCORE   build ClaimPrediction records (dirty from detection, clean from whether the pristine
          detector flags them) and emit engine.benchmark.metrics.main_table_row — before and
          after the whitelist, so triage's effect on FAR is visible.

Mother: CNS-058 (mesothelioma multiomics, Nat Genet 2023), input/twins_work/CNS-058/.
Substrate: MOESM7 / Sample_features (real numeric cells; the MOFA tables store numbers as text
and are invisible to the numeric detectors, so they are avoided).

Run from repo root:  PYTHONPATH=. python3 scripts/generate_cns058_twins.py
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from engine.benchmark.bridge import dirty_prediction
from engine.benchmark.metrics import ClaimPrediction, main_table_row
from engine.static_audit.tools.source_data_findings import (
    duplicate_column_findings,
    fixed_relationship_findings,
    parse_workbook_vectors,
)
from engine.twins.generate import InjectionSpec, MotherConfig, generate_twins
from engine.twins.matched_clean import (
    clean_control_rows,
    detect_pairs,
    enumerate_clean_controls,
    far,
    flagged_pairs,
)
from engine.twins.whitelist import filter_whitelisted_findings

PAPER_ID = "CNS-058_5b88beb8_mesothelioma_multiomics"
BASE_DIR = Path("input/twins_work/CNS-058")
WORKBOOK = "41588_2023_1321_MOESM7_ESM.xlsx"
SHEET = "Sample_features"
START, END = 3, 122
SITES = [("I", "AG"), ("K", "AJ")]  # (source, target); both real-numeric, varied values

_EXPECT = {
    "duplicate_columns": {"duplicate_numeric_columns"},
    "fixed_ratio": {"fixed_ratio"},
    "fixed_difference": {"fixed_difference"},
}


def _specs() -> tuple[InjectionSpec, ...]:
    specs = []
    for seq, (src, dst) in enumerate(SITES, start=1):
        specs.append(InjectionSpec("duplicate_columns", WORKBOOK, SHEET, START, END, source_column=src, target_column=dst, seq=seq))
        specs.append(InjectionSpec("fixed_ratio", WORKBOOK, SHEET, START, END, source_column=src, target_column=dst, factor=2.0, seq=seq))
        specs.append(InjectionSpec("fixed_difference", WORKBOOK, SHEET, START, END, source_column=src, target_column=dst, delta=5.0, seq=seq))
    return tuple(specs)


def _twin_findings(supplementary: Path) -> list[dict]:
    findings: list[dict] = []
    for sheet in parse_workbook_vectors(supplementary / WORKBOOK):
        if sheet.sheet != SHEET:
            continue
        findings.extend(duplicate_column_findings(sheet, 8, 0.95, 200))
        findings.extend(fixed_relationship_findings(sheet, 8, 0.95, 200))
    return findings


def main() -> int:
    twins_root = BASE_DIR / "twins"
    config = MotherConfig(paper_id=PAPER_ID, base_dir=str(BASE_DIR), specs=_specs())
    generated = generate_twins(config, twins_root)

    # --- dirty predictions (verify each injected relationship is detectable on its twin) ---
    dirty_preds: list[ClaimPrediction] = []
    dirty_rows = []
    for row in generated:
        twin_dir = twins_root / row["twin"]
        cats = {f.get("category") for f in _twin_findings(twin_dir / "supplementary")}
        detected = bool(_EXPECT[row["class"]] & cats)
        dirty_preds.append(dirty_prediction(row["twin"], detected=detected, verdict="real" if detected else "missing"))
        dirty_rows.append({**row, "detected": detected})

    # --- matched-clean controls from the pristine mother ---
    injected_pairs = {frozenset(site) for site in SITES}
    controls = enumerate_clean_controls(BASE_DIR / WORKBOOK, SHEET, min_overlap=8, exclude_pairs=injected_pairs)

    raw_findings = detect_pairs(BASE_DIR / WORKBOOK, SHEET)
    kept, whitelisted = filter_whitelisted_findings(raw_findings)
    far_raw = far(controls, flagged_pairs(raw_findings))
    far_wl = far(controls, flagged_pairs(kept))

    # clean predictions at the raw operating point (no triage) => the honest FAR baseline
    flagged_raw = flagged_pairs(raw_findings)
    clean_preds = [
        ClaimPrediction(
            claim_id=f"{PAPER_ID}::clean::{c.col_a}-{c.col_b}",
            gt_label="clean",
            predicted_flag=(c.pair_key in flagged_raw),
            confidence=1.0 if c.pair_key in flagged_raw else 0.0,
        )
        for c in controls
    ]

    # --- write the clean-controls annotations.yaml (loads via load_annotations, label=clean) ---
    clean_doc = {
        "paper": {"base_paper_id": PAPER_ID, "source": "injected",
                  "note": "matched-clean controls from the pristine mother; label=clean"},
        "claims": clean_control_rows(controls),
    }
    clean_path = twins_root / "cns058_clean_controls.annotations.yaml"
    clean_path.write_text(yaml.safe_dump(clean_doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # --- the real main-table row for the deterministic-proxy system on CNS-058 ---
    row = main_table_row(dirty_preds + clean_preds)

    summary = {
        "paper_id": PAPER_ID,
        "substrate": f"{WORKBOOK}/{SHEET} rows {START}-{END}, sites {SITES}",
        "dirty": {"count": len(dirty_rows), "all_detected": all(r["detected"] for r in dirty_rows), "twins": dirty_rows},
        "clean_controls": {"count": len(controls), "far_raw": far_raw, "far_after_whitelist": far_wl,
                           "whitelisted_findings": len(whitelisted)},
        "main_table_row_raw_operating_point": row,
        "clean_annotations": str(clean_path),
    }
    out = twins_root / "cns058_generation_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(out),
        "dirty_twins": len(dirty_rows),
        "all_detected": summary["dirty"]["all_detected"],
        "clean_controls": len(controls),
        "far_raw": round(far_raw["far"], 4),
        "far_after_whitelist": round(far_wl["far"], 4),
        "claim_f1": round(row["claim_f1"], 4),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
