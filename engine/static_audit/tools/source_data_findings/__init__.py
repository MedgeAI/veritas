"""Generate higher-level findings from XLSX source-data profiles and workbooks.

This package replaces the former ``source_data_findings.py`` module.  All public
names are re-exported here for backward compatibility.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ._shared import (
    FORMULA_REF_RE,
    SENTENCE_SPLIT_RE,
    SUMMARY_MEAN_TERMS,
    SUMMARY_N_TERMS,
    SUMMARY_SUM_TERMS,
    TIME_EVENT_TERMS,
    SheetVectors,
    _decimal_close,
    _extract_raw_data_samples,
    _has_any,
    _integer_like_ratio,
    _is_mean_label,
    _is_n_label,
    _is_sum_label,
    _label_lower,
    assign_ids,
    clean_text,
    col_to_idx,
    col_to_name,
    column_label,
    common_rows,
    decimal_key,
    is_index_like_column,
    is_integer_like,
    load_profile,
    parse_workbook_vectors,
    risk_rank,
)
from .claim_mappings import (
    candidate_claims_from_refs,
    claim_mappings,
    figure_keys_from_sheet_name,
    finding_index,
    markdown_blocks,
)
from .duplicate_columns import duplicate_column_findings
from .formula_findings import (
    _adjacent_row_rate,
    formula_findings,
    formula_pattern,
    referenced_columns,
)
from .relationships import fixed_relationship_findings, relationship_record
from .summary_statistics import (
    is_summary_statistic_pair,
    is_time_event_design_pair,
    zero_inflated_pair_artifact,
)

__all__ = [
    "FORMULA_REF_RE",
    "SENTENCE_SPLIT_RE",
    "SUMMARY_MEAN_TERMS",
    "SUMMARY_N_TERMS",
    "SUMMARY_SUM_TERMS",
    "TIME_EVENT_TERMS",
    "SheetVectors",
    "_adjacent_row_rate",
    "_decimal_close",
    "_extract_raw_data_samples",
    "_has_any",
    "_integer_like_ratio",
    "_is_mean_label",
    "_is_n_label",
    "_is_sum_label",
    "_label_lower",
    "assign_ids",
    "candidate_claims_from_refs",
    "claim_mappings",
    "clean_text",
    "col_to_idx",
    "col_to_name",
    "column_label",
    "common_rows",
    "decimal_key",
    "duplicate_column_findings",
    "figure_keys_from_sheet_name",
    "finding_index",
    "fixed_relationship_findings",
    "formula_findings",
    "formula_pattern",
    "is_index_like_column",
    "is_integer_like",
    "is_summary_statistic_pair",
    "is_time_event_design_pair",
    "load_profile",
    "markdown_blocks",
    "parse_workbook_vectors",
    "referenced_columns",
    "relationship_record",
    "risk_rank",
    "zero_inflated_pair_artifact",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate findings from XLSX source data."
    )
    parser.add_argument(
        "xlsx_root", help="Directory containing .xlsx source data files."
    )
    parser.add_argument(
        "--profile", required=True, help="source_data_profile.json path."
    )
    parser.add_argument("--full-md", help="MinerU full.md path for claim mapping.")
    parser.add_argument(
        "--output", required=True, help="Output source_data_findings.json path."
    )
    parser.add_argument("--min-overlap", type=int, default=12)
    parser.add_argument("--min-support", type=float, default=0.98)
    parser.add_argument("--max-findings-per-category", type=int, default=200)
    parser.add_argument("--max-paper-refs", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    xlsx_root = Path(args.xlsx_root).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    profile_path = Path(args.profile).expanduser().resolve()
    full_md = Path(args.full_md).expanduser().resolve() if args.full_md else None
    profile = load_profile(profile_path)

    duplicate_columns = []
    fixed_relationships = []
    formulas = []
    errors = []
    for workbook_path in sorted(xlsx_root.glob("*.xlsx")):
        try:
            sheets = parse_workbook_vectors(workbook_path)
        except Exception as exc:  # Deliberately broad: per-workbook parsing may raise InvalidFileException, XML errors, etc.
            errors.append(
                {
                    "workbook": workbook_path.name,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        for sheet in sheets:
            duplicate_columns.extend(
                duplicate_column_findings(
                    sheet,
                    args.min_overlap,
                    args.min_support,
                    args.max_findings_per_category,
                )
            )
            fixed_relationships.extend(
                fixed_relationship_findings(
                    sheet,
                    args.min_overlap,
                    args.min_support,
                    args.max_findings_per_category,
                )
            )
            formulas.extend(formula_findings(sheet, args.max_findings_per_category))

    duplicate_columns = sorted(
        duplicate_columns, key=lambda item: (-item["equal_rows"], item["workbook"])
    )[: args.max_findings_per_category]
    fixed_relationships = sorted(
        fixed_relationships, key=lambda item: (-item["support_rows"], item["workbook"])
    )[: args.max_findings_per_category]
    formulas = sorted(
        formulas, key=lambda item: (-item["formula_count"], item["workbook"])
    )[: args.max_findings_per_category]
    findings = [*duplicate_columns, *fixed_relationships, *formulas]
    assign_ids(findings)
    priority_findings = [
        finding
        for finding in findings
        if risk_rank(finding.get("risk_level", "")) >= 2
        and finding.get("artifact_likelihood") != "high"
    ]

    mappings = (
        claim_mappings(profile, full_md, args.max_paper_refs, findings)
        if full_md
        else []
    )
    result = {
        "schema_version": "1.1",
        "created_by": "engine/static_audit/tools/source_data_findings.py",
        "inputs": {
            "xlsx_root": str(xlsx_root),
            "profile": str(profile_path),
            "full_md": str(full_md) if full_md else None,
        },
        "parameters": {
            "min_overlap": args.min_overlap,
            "min_support": args.min_support,
            "max_findings_per_category": args.max_findings_per_category,
        },
        "summary": {
            "workbook_count": profile.get("summary", {}).get("workbook_count"),
            "sheet_count": profile.get("summary", {}).get("sheet_count"),
            "duplicate_column_findings": len(duplicate_columns),
            "fixed_relationship_findings": len(fixed_relationships),
            "formula_derived_columns": len(formulas),
            "priority_findings": len(priority_findings),
            "claim_to_source_data_mappings": len(mappings),
            "errors": len(errors),
        },
        "findings": findings,
        "priority_findings": priority_findings,
        "duplicate_columns": duplicate_columns,
        "fixed_relationships": fixed_relationships,
        "formula_derived_columns": formulas,
        "claim_to_source_data": mappings,
        "errors": errors,
        "limitations": [
            "列标签来自 XLSX 顶部文本的启发式提取，可能无法准确表达多层表头。",
            "固定差/固定比仅说明机械关系候选，需排除公式列、单位换算、设计矩阵和合法派生指标。",
            "claim-to-source-data 映射基于 sheet 名称和论文 figure 引用，尚未达到 panel 级强确认。",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(output), **result["summary"]}, ensure_ascii=False))
    return 0
