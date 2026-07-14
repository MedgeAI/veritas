"""Config-driven multi-mother twin generation.

`scripts/round1_generate_cns098.py` hardcodes one mother (CNS-098): its workbooks, sheet
names, and column layout are baked in. The injection *primitives* in `injector.py`, however,
are already mother-agnostic — each takes (source_path, sheet, columns, rows) as parameters.

This module closes the gap with a small declarative config so a NEW mother paper becomes a
data change, not a code change:

    MotherConfig(paper_id, base_dir, specs=[InjectionSpec(...), ...])
    generate_twins(config, twins_root)  ->  one twin dir per spec, each with:
        supplementary/<mother xlsx copies, one injected>
        injection_log.json     (deterministic cell-level ground truth)
        annotations.yaml       (loads via engine.benchmark.schema.load_annotations, source=injected)

The output layout mirrors CNS-098 so `scripts/round2_score_cns098.py` scoring works unchanged.

IMPORTANT (mother selection): the injection *source* column must hold REAL numeric cells, not
numbers stored as text. `parse_workbook_vectors` files text-stored numbers as text_columns, so
the numeric duplicate/ratio/difference detectors never see them and the injected twin becomes
undetectable. Validate a candidate substrate with `parse_workbook_vectors(...).numeric_columns`
before wiring it into a config. See `engine/benchmark` notes.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import InjectionOperation
from .injector import (
    annotations_yaml,
    inject_duplicate_columns,
    inject_duplicate_row_vector,
    inject_fixed_difference,
    inject_fixed_ratio,
    inject_paired_difference_spread,
    inject_row_offset_exact_reuse,
)

# injection_class -> primitive; only single-workbook, single-sheet classes are config-driven here.
# (cross_sheet_duplication / p_value_inconsistency / grim_violation need extra params and stay
# in the mother-specific scripts until a config schema for them is agreed with w1.)
_COLUMN_PAIR_CLASSES = {"duplicate_columns", "fixed_ratio", "fixed_difference", "paired_difference_spread"}


@dataclass(frozen=True)
class InjectionSpec:
    """One single-factor injection to apply to a copy of the mother workbook.

    Column-pair classes (duplicate_columns/fixed_ratio/fixed_difference/paired_difference_spread)
    use source_column + target_column. row_offset_exact_reuse uses source_column as the single
    column. duplicate_row_vector uses `columns` + source_row/target_row instead of column pair.
    """

    injection_class: str
    workbook: str                     # basename of the mother xlsx to inject into
    sheet: str
    start_row: int
    end_row: int
    source_column: str | None = None
    target_column: str | None = None
    factor: float | None = None       # fixed_ratio
    delta: float | None = None        # fixed_difference
    band: float | None = None         # paired_difference_spread
    offset: int | None = None         # row_offset_exact_reuse
    ratio: float | None = None        # row_offset_exact_reuse
    columns: tuple[str, ...] = ()      # duplicate_row_vector
    source_row: int | None = None      # duplicate_row_vector
    target_row: int | None = None      # duplicate_row_vector
    seq: int = 1
    seed: int | None = None


@dataclass(frozen=True)
class MotherConfig:
    paper_id: str
    base_dir: str                     # directory holding the mother's *.xlsx
    specs: tuple[InjectionSpec, ...] = field(default_factory=tuple)


def _copy_supplementary(base_dir: Path, twin_dir: Path) -> Path:
    supplementary = twin_dir / "supplementary"
    if supplementary.exists():
        shutil.rmtree(supplementary)
    supplementary.mkdir(parents=True)
    for workbook in sorted(base_dir.glob("*.xlsx")):
        shutil.copy2(workbook, supplementary / workbook.name)
    return supplementary


def _apply(spec: InjectionSpec, workbook_path: Path, seed: int) -> InjectionOperation:
    """Dispatch a spec to its injection primitive, injecting in place on the copied workbook."""
    kind = spec.injection_class
    common = dict(
        source_path=workbook_path,
        output_path=workbook_path,
        sheet_name=spec.sheet,
        seed=seed,
    )
    if kind == "duplicate_columns":
        return inject_duplicate_columns(
            source_column=spec.source_column, target_column=spec.target_column,
            start_row=spec.start_row, end_row=spec.end_row, **common,
        )
    if kind == "fixed_ratio":
        if spec.factor is None:
            raise ValueError(f"{kind}: factor is required")
        return inject_fixed_ratio(
            source_column=spec.source_column, target_column=spec.target_column,
            start_row=spec.start_row, end_row=spec.end_row, factor=spec.factor, **common,
        )
    if kind == "fixed_difference":
        if spec.delta is None:
            raise ValueError(f"{kind}: delta is required")
        return inject_fixed_difference(
            source_column=spec.source_column, target_column=spec.target_column,
            start_row=spec.start_row, end_row=spec.end_row, delta=spec.delta, **common,
        )
    if kind == "paired_difference_spread":
        if spec.band is None:
            raise ValueError(f"{kind}: band is required")
        return inject_paired_difference_spread(
            left_column=spec.source_column, right_column=spec.target_column,
            start_row=spec.start_row, end_row=spec.end_row, band=spec.band, **common,
        )
    if kind == "row_offset_exact_reuse":
        if spec.offset is None or spec.ratio is None:
            raise ValueError(f"{kind}: offset and ratio are required")
        return inject_row_offset_exact_reuse(
            column=spec.source_column, start_row=spec.start_row, end_row=spec.end_row,
            offset=spec.offset, ratio=spec.ratio, **common,
        )
    if kind == "duplicate_row_vector":
        if spec.source_row is None or spec.target_row is None or not spec.columns:
            raise ValueError(f"{kind}: source_row, target_row and columns are required")
        return inject_duplicate_row_vector(
            source_row=spec.source_row, target_row=spec.target_row,
            columns=list(spec.columns), **common,
        )
    raise ValueError(f"unsupported injection_class for config-driven generation: {kind!r}")


def generate_one(config: MotherConfig, twins_root: Path, spec: InjectionSpec) -> dict:
    base_dir = Path(config.base_dir)
    seed = spec.seed if spec.seed is not None else 990000 + spec.seq
    twin_dir = twins_root / f"{config.paper_id}__{spec.injection_class}__{spec.seq:02d}"
    if twin_dir.exists():
        shutil.rmtree(twin_dir)
    twin_dir.mkdir(parents=True)
    supplementary = _copy_supplementary(base_dir, twin_dir)

    target_workbook = supplementary / spec.workbook
    if not target_workbook.exists():
        raise FileNotFoundError(f"mother workbook not found: {target_workbook}")
    operation = _apply(spec, target_workbook, seed)

    (twin_dir / "injection_log.json").write_text(
        json.dumps(operation.log_dict(seed=seed), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (twin_dir / "annotations.yaml").write_text(
        annotations_yaml(operation, base_paper_id=config.paper_id),
        encoding="utf-8",
    )
    return {
        "twin": twin_dir.name,
        "class": spec.injection_class,
        "seq": spec.seq,
        "changed_cells": len(operation.cells),
    }


def generate_twins(config: MotherConfig, twins_root: Path) -> list[dict]:
    """Generate one twin per spec under twins_root; returns a per-twin summary list."""
    twins_root = Path(twins_root)
    twins_root.mkdir(parents=True, exist_ok=True)
    return [generate_one(config, twins_root, spec) for spec in config.specs]
