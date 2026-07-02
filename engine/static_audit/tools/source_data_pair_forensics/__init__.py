"""Detect row-offset and paired-cohort patterns in XLSX Source Data.

This package replaces the former ``source_data_pair_forensics.py`` module.
All public names are re-exported here for backward compatibility.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from engine.static_audit.tools.source_data_findings import (
    parse_workbook_vectors,
)

from ._shared import (
    PairForensicsParams,
    RISK_ORDER,
    build_sheet_numeric_index,
    candidate_offsets,
    common_offset_pairs,
    decimal_places,
    is_low_information_numeric_column,
    numeric_value_diversity,
    ratio_key,
    risk_rank,
)
from .binary_arithmetic import binary_arithmetic_relation_findings
from .cross_block_diff import cross_block_paired_diff_findings
from .duplicate_row import duplicate_row_vector_findings
from .paired_ratio import (
    copy_paste_modify_findings,
    long_format_paired_ratio_reuse_findings,
    long_format_within_pair_ratio_enrichment_findings,
    paired_ratio_reuse_findings,
    row_offset_scalar_findings,
    row_offset_rounding_bias_findings,
    shifted_paste_findings,
    strict_linear_relation_findings,
)
from .paired_spread import paired_difference_spread_findings
from .review_tasks import (
    assign_ids,
    cluster_pair_forensics_findings,
    pair_forensics_review_tasks,
)
from .sequence_relation import internal_sequence_relation_findings
from .small_patterns import (
    cross_sheet_fractional_tail_reuse_findings,
    decimal_tail_match_shifted_findings,
    repeated_measurement_value_findings,
    small_n_fixed_relationship_findings,
    within_sheet_fractional_tail_reuse_findings,
)

__all__ = [
    "RISK_ORDER",
    "PairForensicsParams",
    "analyze_xlsx_root",
    "assign_ids",
    "binary_arithmetic_relation_findings",
    "candidate_offsets",
    "cluster_pair_forensics_findings",
    "common_offset_pairs",
    "copy_paste_modify_findings",
    "cross_block_paired_diff_findings",
    "decimal_places",
    "decimal_tail_match_shifted_findings",
    "duplicate_row_vector_findings",
    "internal_sequence_relation_findings",
    "is_low_information_numeric_column",
    "long_format_paired_ratio_reuse_findings",
    "long_format_within_pair_ratio_enrichment_findings",
    "numeric_value_diversity",
    "paired_difference_spread_findings",
    "paired_ratio_reuse_findings",
    "pair_forensics_review_tasks",
    "ratio_key",
    "risk_rank",
    "row_offset_rounding_bias_findings",
    "row_offset_scalar_findings",
    "cross_sheet_fractional_tail_reuse_findings",
    "repeated_measurement_value_findings",
    "shifted_paste_findings",
    "small_n_fixed_relationship_findings",
    "strict_linear_relation_findings",
    "within_sheet_fractional_tail_reuse_findings",
]


def analyze_xlsx_root(xlsx_root: Path, params: PairForensicsParams) -> dict[str, Any]:
    errors = []
    scalar_findings = []
    ratio_findings = []
    duplicate_rows = []
    long_ratio_reuse = []
    long_ratio_enrichment = []
    rounding_bias = []
    narrow_diff_spread = []
    cross_block_narrow = []
    repeated_values = []
    fractional_tail_reuse = []
    small_n_fixed_relationships = []
    binary_arithmetic = []
    copy_paste_modify = []
    shifted_paste = []
    internal_sequence = []
    decimal_tail_shifted = []
    strict_linear = []
    all_sheets = []
    detector_skips: list[dict[str, Any]] = []
    performance: dict[str, Any] = {
        "numeric_index_sheets": 0,
        "numeric_index_columns": 0,
        "numeric_index_cells": 0,
        "numeric_index_build_seconds": 0.0,
    }
    workbook_count = 0
    sheet_count = 0
    for workbook_path in sorted(xlsx_root.glob("*.xlsx")):
        workbook_count += 1
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
        sheet_count += len(sheets)
        all_sheets.extend(sheets)
        for sheet in sheets:
            index_start = time.perf_counter()
            numeric_index = build_sheet_numeric_index(sheet, params)
            performance["numeric_index_build_seconds"] = float(
                performance["numeric_index_build_seconds"]
            ) + (time.perf_counter() - index_start)
            performance["numeric_index_sheets"] = int(
                performance["numeric_index_sheets"]
            ) + 1
            performance["numeric_index_columns"] = int(
                performance["numeric_index_columns"]
            ) + len(numeric_index.valid_columns)
            performance["numeric_index_cells"] = int(
                performance["numeric_index_cells"]
            ) + sum(len(values) for values in numeric_index.values_by_col.values())
            scalar_findings.extend(row_offset_scalar_findings(sheet, params))
            ratio_findings.extend(paired_ratio_reuse_findings(sheet, params))
            duplicate_rows.extend(duplicate_row_vector_findings(sheet, params))
            long_ratio_reuse.extend(
                long_format_paired_ratio_reuse_findings(sheet, params)
            )
            long_ratio_enrichment.extend(
                long_format_within_pair_ratio_enrichment_findings(sheet, params)
            )
            rounding_bias.extend(row_offset_rounding_bias_findings(sheet, params))
            narrow_diff_spread.extend(paired_difference_spread_findings(sheet, params))
            cross_block_narrow.extend(cross_block_paired_diff_findings(sheet, params))
            repeated_values.extend(repeated_measurement_value_findings(sheet, params))
            fractional_tail_reuse.extend(
                within_sheet_fractional_tail_reuse_findings(sheet, params)
            )
            small_n_fixed_relationships.extend(
                small_n_fixed_relationship_findings(sheet, params)
            )
            binary_arithmetic.extend(
                binary_arithmetic_relation_findings(
                    numeric_index,
                    params,
                    performance=performance,
                    detector_skips=detector_skips,
                )
            )
            copy_paste_modify.extend(
                copy_paste_modify_findings(
                    numeric_index,
                    params,
                    performance=performance,
                    detector_skips=detector_skips,
                )
            )
            shifted_paste.extend(
                shifted_paste_findings(
                    numeric_index,
                    params,
                    performance=performance,
                    detector_skips=detector_skips,
                )
            )
            internal_sequence.extend(
                internal_sequence_relation_findings(numeric_index, params)
            )
            decimal_tail_shifted.extend(
                decimal_tail_match_shifted_findings(
                    numeric_index,
                    params,
                    performance=performance,
                    detector_skips=detector_skips,
                )
            )
            strict_linear.extend(
                strict_linear_relation_findings(
                    numeric_index,
                    params,
                    performance=performance,
                    detector_skips=detector_skips,
                )
            )
    cross_sheet_fractional_tail_reuse = cross_sheet_fractional_tail_reuse_findings(
        all_sheets, params
    )

    findings = [
        *scalar_findings,
        *ratio_findings,
        *duplicate_rows,
        *long_ratio_reuse,
        *long_ratio_enrichment,
        *rounding_bias,
        *narrow_diff_spread,
        *cross_block_narrow,
        *repeated_values,
        *fractional_tail_reuse,
        *small_n_fixed_relationships,
        *cross_sheet_fractional_tail_reuse,
        *binary_arithmetic,
        *copy_paste_modify,
        *shifted_paste,
        *internal_sequence,
        *decimal_tail_shifted,
        *strict_linear,
    ]
    findings = sorted(
        findings,
        key=lambda item: (
            -risk_rank(item["risk_level"]),
            str(item.get("workbook")),
            str(item.get("sheet")),
        ),
    )
    assign_ids(findings)
    priority_findings = [
        finding
        for finding in findings
        if risk_rank(finding.get("risk_level", "")) >= 2
        and finding.get("artifact_likelihood") != "high"
    ]
    finding_clusters = cluster_pair_forensics_findings(priority_findings)
    review_tasks = pair_forensics_review_tasks(finding_clusters)
    by_category = Counter(finding["category"] for finding in findings)
    performance["numeric_index_build_seconds"] = round(
        float(performance["numeric_index_build_seconds"]), 6
    )
    return {
        "schema_version": "1.0",
        "created_by": "engine/static_audit/tools/source_data_pair_forensics.py",
        "inputs": {"xlsx_root": str(xlsx_root)},
        "parameters": {
            "min_pairs": params.min_pairs,
            "min_support": params.min_support,
            "ratio_places": params.ratio_places,
            "max_offset": params.max_offset,
            "max_findings_per_category": params.max_findings_per_category,
            "min_duplicate_row_width": params.min_duplicate_row_width,
        },
        "summary": {
            "workbook_count": workbook_count,
            "sheet_count": sheet_count,
            "findings": len(findings),
            "priority_findings": len(priority_findings),
            "finding_clusters": len(finding_clusters),
            "review_tasks": len(review_tasks),
            "row_offset_scalar_findings": len(scalar_findings),
            "paired_ratio_reuse_findings": len(ratio_findings),
            "duplicate_row_vector_findings": len(duplicate_rows),
            "long_format_paired_ratio_reuse_findings": len(long_ratio_reuse),
            "long_format_within_pair_ratio_enrichment_findings": len(
                long_ratio_enrichment
            ),
            "rounding_bias_findings": len(rounding_bias),
            "paired_difference_too_narrow_findings": len(narrow_diff_spread),
            "cross_block_paired_diff_too_narrow_findings": len(cross_block_narrow),
            "repeated_measurement_value_findings": len(repeated_values),
            "fractional_tail_reuse_findings": len(fractional_tail_reuse),
            "small_n_fixed_relationship_findings": len(
                small_n_fixed_relationships
            ),
            "cross_sheet_fractional_tail_reuse_findings": len(
                cross_sheet_fractional_tail_reuse
            ),
            "binary_arithmetic_relation_findings": len(binary_arithmetic),
            "copy_paste_modify_findings": len(copy_paste_modify),
            "shifted_paste_findings": len(shifted_paste),
            "internal_sequence_relation_findings": len(internal_sequence),
            "decimal_tail_match_shifted_findings": len(decimal_tail_shifted),
            "strict_linear_relation_findings": len(strict_linear),
            "by_category": dict(by_category),
            "errors": len(errors),
            "detector_skips": len(detector_skips),
            "performance": performance,
        },
        "findings": findings,
        "priority_findings": priority_findings,
        "finding_clusters": finding_clusters,
        "review_tasks": review_tasks,
        "row_offset_scalar_findings": scalar_findings,
        "paired_ratio_reuse_findings": ratio_findings,
        "duplicate_row_vector_findings": duplicate_rows,
        "long_format_paired_ratio_reuse_findings": long_ratio_reuse,
        "long_format_within_pair_ratio_enrichment_findings": long_ratio_enrichment,
        "rounding_bias_findings": rounding_bias,
        "paired_difference_too_narrow_findings": narrow_diff_spread,
        "cross_block_paired_diff_too_narrow_findings": cross_block_narrow,
        "repeated_measurement_value_findings": repeated_values,
        "fractional_tail_reuse_findings": fractional_tail_reuse,
        "small_n_fixed_relationship_findings": small_n_fixed_relationships,
        "cross_sheet_fractional_tail_reuse_findings": cross_sheet_fractional_tail_reuse,
        "binary_arithmetic_relation_findings": binary_arithmetic,
        "copy_paste_modify_findings": copy_paste_modify,
        "shifted_paste_findings": shifted_paste,
        "internal_sequence_relation_findings": internal_sequence,
        "decimal_tail_match_shifted_findings": decimal_tail_shifted,
        "strict_linear_relation_findings": strict_linear,
        "detector_skips": detector_skips,
        "performance": performance,
        "errors": errors,
        "limitations": [
            "该工具只识别 XLSX 中的通用行偏移、配对比例复用、long-format 成对比例复用、小样本数值复用和低宽度行重复模式，不判断最终科研诚信。",
            "行是否代表独立样本、患者或技术重复需要结合 sheet 注释、论文方法和原始仪器输出人工确认。",
            "ratio_places 会影响 paired ratio reuse 的敏感度；高精度与展示值四舍五入场景应分开解释。",
            "低信息数值列会被视为分组/类别/编号候选并排除在连续测量列检测之外，可能降低二分类测量场景的敏感度。",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect generic paired-cohort and row-offset patterns in XLSX Source Data."
    )
    parser.add_argument(
        "xlsx_root", help="Directory containing .xlsx source data files."
    )
    parser.add_argument(
        "--output", required=True, help="Output source_data_pair_forensics.json path."
    )
    parser.add_argument("--min-pairs", type=int, default=8)
    parser.add_argument("--min-support", type=float, default=0.95)
    parser.add_argument("--ratio-places", type=int, default=4)
    parser.add_argument("--max-offset", type=int, default=80)
    parser.add_argument("--max-findings-per-category", type=int, default=50)
    parser.add_argument("--min-duplicate-row-width", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    xlsx_root = Path(args.xlsx_root).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    params = PairForensicsParams(
        min_pairs=max(2, args.min_pairs),
        min_support=min(1.0, max(0.0, args.min_support)),
        ratio_places=max(1, args.ratio_places),
        max_offset=max(1, args.max_offset),
        max_findings_per_category=max(1, args.max_findings_per_category),
        min_duplicate_row_width=max(2, args.min_duplicate_row_width),
    )
    result = analyze_xlsx_root(xlsx_root, params)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"output": str(output), **result["summary"]}, ensure_ascii=False))
    return 0
