"""Code-level contracts for P0 injection classes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CellChange:
    ref: str
    orig: Any
    new: Any


@dataclass(frozen=True)
class InjectionOperation:
    injection_class: str
    claim_type: str
    workbook: str
    sheet: str
    target: str
    injection: dict[str, Any]
    cells: list[CellChange] = field(default_factory=list)

    def log_dict(self, *, seed: int) -> dict[str, Any]:
        payload = {
            "seed": seed,
            "class": self.injection_class,
            "claim_type": self.claim_type,
            "workbook": self.workbook,
            "sheet": self.sheet,
            "target": self.target,
            "injection": self.injection,
            "cells": [
                {"ref": item.ref, "orig": item.orig, "new": item.new}
                for item in self.cells
            ],
        }
        return payload


CLAIM_TYPES = {
    "duplicate_columns": "source_data.duplicate_columns",
    "duplicate_row_vector": "source_data.duplicate_row_vector",
    "fixed_ratio": "source_data.fixed_ratio",
    "fixed_difference": "source_data.fixed_difference",
    "row_offset_exact_reuse": "source_data.row_offset_exact_reuse",
    "paired_difference_spread": "source_data.paired_difference_spread",
    "cross_sheet_duplication": "source_data.cross_sheet_duplication",
    "p_value_inconsistency": "source_data.p_value_inconsistency",
    "grim_violation": "source_data.grim_violation",
}
