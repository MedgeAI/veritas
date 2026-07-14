from __future__ import annotations

from engine.twins.scorer import (
    CellAnchor,
    delta_findings,
    score_verdict_level,
)
from engine.twins.whitelist import whitelist_reason
from cli.main import build_parser


def test_whitelist_recognizes_declared_auc_difference() -> None:
    finding = {
        "category": "fixed_difference",
        "column_labels": ["auc_null", "auc_full", "auc_diff"],
        "relationship_value": "0.04",
    }

    assert whitelist_reason(finding) == "declared_difference_or_ratio_column"


def test_whitelist_recognizes_hr_loghr_transform() -> None:
    finding = {
        "category": "fixed_ratio",
        "column_labels": ["HR", "logHR"],
    }

    assert whitelist_reason(finding) == "exp_log_transform"


def test_delta_findings_removes_mother_finding_at_same_injected_cells() -> None:
    anchor = CellAnchor.from_log_cells(
        [{"ref": "F3", "orig": 1.0, "new": 2.0}],
        workbook="book.xlsx",
        sheet="s1",
    )
    mother = [{"category": "fixed_ratio", "workbook": "book.xlsx", "sheet": "s1", "cells": ["F3"]}]
    twin = [
        {"category": "fixed_ratio", "workbook": "book.xlsx", "sheet": "s1", "cells": ["F3"]},
        {"category": "duplicate_columns", "workbook": "book.xlsx", "sheet": "s1", "cells": ["F3"]},
    ]

    assert delta_findings(twin, mother, anchor) == [
        {"category": "duplicate_columns", "workbook": "book.xlsx", "sheet": "s1", "cells": ["F3"]}
    ]


def test_verdict_level_far_and_hallucination_ignore_benign() -> None:
    injected = [
        {"class": "fixed_ratio", "detected": True, "verdict": "real"},
        {"class": "fixed_ratio", "detected": False, "verdict": "missing"},
        {"class": "fixed_ratio", "detected": True, "verdict": "benign_artifact"},
    ]
    mother = [
        {"class": "fixed_ratio", "verdict": "real"},
        {"class": "fixed_ratio", "verdict": "benign_artifact"},
        {"class": "fixed_ratio", "verdict": "indeterminate"},
    ]

    metrics = score_verdict_level(injected, mother)

    assert metrics["by_class"]["fixed_ratio"]["tp"] == 1
    assert metrics["by_class"]["fixed_ratio"]["fn_or_benign"] == 2
    assert metrics["by_class"]["fixed_ratio"]["far"] == 2 / 3
    assert metrics["hallucination_rate"] == 1 / 3


def test_audit_paper_accepts_llm_only_ablation_flag() -> None:
    args = build_parser().parse_args(
        ["audit-paper", "paper", "--llm-only-ablation", "--agent-mode", "review"]
    )

    assert args.llm_only_ablation is True
