"""Source Data LLM Verdict — Sheet-level batch false-positive adjudication.

Groups source_data findings by (workbook, sheet), reads XLSX column context,
and calls LLM (via AgentStepRunner / opencode) to judge each finding as
true_positive, false_positive, or uncertain.

Output: ``source_data/findings_verdict.json``

Design rationale
----------------
Deterministic pattern detectors (fixed_ratio, duplicate_row_vector, etc.)
flag many structurally normal data patterns as suspicious:

* Descriptive-statistics tables: Sum = Mean × N is a definitional relationship
* Index/time columns: parallel timelines have constant offsets
* scRNA-seq matrices: >60% zero-expression is biological dropout, not copy-paste
* Control groups: all-zero is a valid experimental outcome

Heuristic column-name enumeration cannot cover the open-ended vocabulary of
scientific data tables.  An LLM judge that sees the *actual column names*,
*sample values*, and *detected pattern* can understand the table's semantics
in one pass and return structured verdicts for every finding on the sheet.

Sheets are processed in parallel (ThreadPoolExecutor); each sheet is one LLM
call.  A typical paper produces 5-12 LLM calls, all parallel, so the wall-clock
latency equals a single LLM call.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from engine.static_audit.paths import resolve_artifact_path

logger = logging.getLogger(__name__)

# ── Prompt template ──────────────────────────────────────────────────

_VERDICT_PROMPT = """\
You are a data-forensics judge evaluating Source Data findings from a scientific paper.

The deterministic detector flagged statistical patterns (fixed ratio, fixed difference, \
duplicate columns, duplicate row vectors, paired ratio reuse, paired difference too narrow, \
row offset reuse) in the table below. Your task: decide whether EACH flagged pattern is a \
**false positive** (explainable by benign table structure) or **uncertain** (needs human review).

## Verdict Criteria

**false_positive** — ONLY when the relationship is *mechanically guaranteed* by table structure:
- Descriptive statistics: Sum = Mean × N, SD/SE derived from same data, Min/Mean/Max correlated by definition
- Index/time columns: sequential row numbers, parallel timelines across experimental groups
- Sparse count data: scRNA-seq columns with >60% zero expression — zeros are biological dropout
- Constant columns: a column with all identical values will have "fixed difference" with ANY other column

**uncertain** — when the pattern *might* be benign but you cannot rule out data manipulation:
- Duplicate measurements that could be independent replicates OR copy-paste
- Ratio patterns in measurement columns without clear definitional explanation
- Row vector matches where rows might represent independent samples

**true_positive** — ONLY for clear structural artifacts that ARE suspicious:
- Two measurement columns (not index/stats) with 100% identical values across all rows
- Ratio reuse in independently measured value columns (not descriptive stats)

## Critical Rules
1. Default to **uncertain** when in doubt — this is fraud detection, false negatives are worse than false positives
2. If the column labels clearly indicate a definitional relationship (Mean/Sum/Median of same data), mark false_positive
3. If columns represent independent experimental conditions or measurements, mark uncertain even if the pattern seems explainable
4. Consider the WHOLE table structure — not just the flagged columns, but all columns together
5. Provide a clear, one-sentence explanation for each verdict

## Input
Sheet context is in the attached JSON file. It contains:
- `columns`: column names and sample values from the actual spreadsheet
- `findings`: all findings for this sheet with detected patterns
- `profile`: sheet-level statistics (cell counts, formula counts)

## Output
Return JSON matching this schema exactly:
{
  "sheet_verdict": "mostly_false_positive" | "mixed" | "mostly_uncertain",
  "sheet_pattern": "descriptive_statistics_table" | "index_time_columns" | \
"sparse_count_data" | "control_group_constants" | "measurement_data" | \
"long_format_data" | "mixed_structure" | "unknown",
  "explanation": "one-paragraph summary of why this sheet's patterns are/isn't suspicious",
  "findings": [
    {
      "id": "<finding_id from input>",
      "verdict": "true_positive" | "false_positive" | "uncertain",
      "confidence": 0.0 to 1.0,
      "benign_pattern": "<short label if false_positive, else null>" | null,
      "explanation": "one sentence"
    }
  ]
}

Be thorough. Do NOT mark findings as false_positive unless the explanation is crystal clear.
"""


# ── XLSX context extraction ─────────────────────────────────────────

def _safe_value(cell_value: Any, max_len: int = 60) -> Any:
    """Convert a cell value to a JSON-safe primitive."""
    if cell_value is None:
        return None
    if isinstance(cell_value, (int, float, bool)):
        return cell_value
    s = str(cell_value)
    return s[:max_len] if len(s) > max_len else s


def read_xlsx_column_context(
    xlsx_path: Path,
    sheet_name: str,
    *,
    max_header_rows: int = 15,
    max_sample_rows: int = 5,
) -> dict[str, Any] | None:
    """Read column headers + sample values from an XLSX sheet.

    Handles multi-level merged-cell headers by:
    1. Scanning all rows until the first numeric-data row
    2. Collecting non-None header values per column (the "header hierarchy")
    3. Returning sample data rows after the header section

    Returns ``None`` if the file cannot be read (openpyxl missing, file
    corrupted, sheet not found).  The caller should treat ``None`` as
    "no XLSX context available" and still include the findings.
    """
    try:
        import openpyxl
    except ImportError:
        logger.debug("openpyxl not available — XLSX context unavailable")
        return None

    try:
        wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    except Exception:
        return None

    try:
        if sheet_name not in wb.sheetnames:
            return None
        ws = wb[sheet_name]

        # Phase 1: scan for the header/data boundary.
        # A "data row" has at least one numeric (int/float) cell value.
        all_rows: list[list[Any]] = []
        first_data_row = -1
        for i, row in enumerate(
            ws.iter_rows(max_row=200, values_only=True)
        ):
            row_vals = [_safe_value(c) for c in row]
            all_rows.append(row_vals)
            if first_data_row < 0 and any(
                isinstance(c, (int, float)) for c in row if c is not None
            ):
                first_data_row = i
            if first_data_row >= 0 and i >= first_data_row + max_sample_rows:
                break

        if not all_rows or first_data_row < 0:
            return None

        header_section = all_rows[:first_data_row]
        data_section = all_rows[first_data_row : first_data_row + max_sample_rows]

        # Drop all-None trailing header rows
        while header_section and all(v is None for v in header_section[-1]):
            header_section.pop()

        num_cols = max((len(r) for r in all_rows), default=0)

        # Phase 2: build per-column header hierarchy
        columns: list[dict[str, Any]] = []
        for col_idx in range(min(num_cols, 60)):
            hierarchy = []
            for row in header_section:
                if col_idx < len(row) and row[col_idx] is not None:
                    val = str(row[col_idx])
                    if val and val not in hierarchy:
                        hierarchy.append(val)
            columns.append({
                "col_idx": col_idx,
                "name": hierarchy[-1] if hierarchy else None,
                "header_hierarchy": hierarchy,
                "sample_values": [
                    row[col_idx]
                    for row in data_section
                    if col_idx < len(row)
                ],
            })

        return {
            "num_columns": num_cols,
            "num_rows_approx": ws.max_row or 0,
            "header_row_count": len(header_section),
            "data_start_row": first_data_row,
            "columns": columns,
        }
    except Exception:
        return None
    finally:
        try:
            wb.close()
        except Exception:
            pass


# ── Sheet context builder ────────────────────────────────────────────

def _build_sheet_context(
    workbook_name: str,
    sheet_name: str,
    findings: list[dict],
    source_data_dir: Path,
    profile: dict | None,
) -> dict[str, Any]:
    """Assemble the per-sheet context payload sent to the LLM."""
    xlsx_path = source_data_dir / workbook_name

    xlsx_context = None
    if xlsx_path.exists():
        xlsx_context = read_xlsx_column_context(xlsx_path, sheet_name)

    profile_stats: dict[str, Any] = {}
    if profile:
        for wb in profile.get("workbooks", []):
            if wb.get("file_name") == workbook_name:
                for sh in wb.get("sheets", []):
                    if sh.get("name") == sheet_name:
                        profile_stats = {
                            k: sh[k]
                            for k in (
                                "cell_count",
                                "numeric_cell_count",
                                "formula_count",
                                "formula_sample",
                                "terminal_digit_counts",
                                "terminal_0_or_5_rate",
                                "duplicate_numeric_rows",
                            )
                            if k in sh
                        }
                        break
                break

    # Compact finding representation — only fields the LLM needs
    compact_findings: list[dict[str, Any]] = []
    for f in findings:
        cf: dict[str, Any] = {
            "id": f.get("finding_id"),
            "type": f.get("category"),
            "risk_level": f.get("risk_level"),
            "support_rate": f.get("support_rate"),
        }
        # Column identifiers — different finding types use different keys
        for key in ("column_pair", "column_labels", "columns", "column_a", "column_b"):
            if key in f and f[key]:
                cf[key] = f[key]
        # Pattern parameters
        for key in (
            "relationship_value",
            "row_offset",
            "overlap_rows",
            "equal_rows",
            "support_rows",
            "matched_pairs",
            "overlap_pairs",
            "duplicate_row_count",
            "width",
            "values",
            "max_abs_diff",
            "min_abs_diff",
            "data_range",
            "pair_count",
        ):
            if key in f and f[key] is not None:
                cf[key] = f[key]
        # Existing detector hints
        if f.get("artifact_likelihood"):
            cf["artifact_likelihood"] = f["artifact_likelihood"]
        if f.get("artifact_reason"):
            cf["artifact_reason"] = f["artifact_reason"]
        if f.get("pressure_test_result"):
            cf["pressure_test_result"] = f["pressure_test_result"]

        compact_findings.append(cf)

    return {
        "workbook": workbook_name,
        "sheet": sheet_name,
        "columns": (xlsx_context or {}).get("columns"),
        "header_row_count": (xlsx_context or {}).get("header_row_count"),
        "data_start_row": (xlsx_context or {}).get("data_start_row"),
        "xlsx_num_rows": (xlsx_context or {}).get("num_rows_approx"),
        "profile": profile_stats,
        "findings": compact_findings,
    }


# ── Schema validator ─────────────────────────────────────────────────

def _validate_verdict_output(data: Any) -> dict:
    """Validate LLM output against the verdict schema.

    Raises ``ValueError`` with a specific message on schema mismatch so
    AgentStepRunner can feed the error back to the LLM for retry.
    """
    if not isinstance(data, dict):
        raise ValueError("output is not a JSON object")
    if "sheet_verdict" not in data:
        raise ValueError("missing 'sheet_verdict'")
    if data["sheet_verdict"] not in (
        "mostly_false_positive",
        "mixed",
        "mostly_uncertain",
    ):
        raise ValueError(
            f"invalid sheet_verdict: {data['sheet_verdict']!r}; "
            "must be mostly_false_positive | mixed | mostly_uncertain"
        )
    if "findings" not in data:
        raise ValueError("missing 'findings'")
    if not isinstance(data["findings"], list):
        raise ValueError("'findings' is not a list")
    for fv in data["findings"]:
        if not isinstance(fv, dict):
            raise ValueError(f"finding entry is not an object: {fv!r}")
        if "id" not in fv:
            raise ValueError(f"finding entry missing 'id': {fv!r}")
        if fv.get("verdict") not in ("true_positive", "false_positive", "uncertain"):
            raise ValueError(
                f"invalid verdict {fv.get('verdict')!r} for {fv.get('id')}; "
                "must be true_positive | false_positive | uncertain"
            )
    return data


# ── Single-sheet LLM call ────────────────────────────────────────────

def get_sheet_verdict(
    sheet_context: dict[str, Any],
    *,
    project_root: Path,
    env: dict[str, str],
    model: str = "dashscope/qwen3.7-plus",
    opencode_bin: str = "opencode",
    timeout_seconds: int = 300,
    max_retries: int = 2,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    """Call LLM to adjudicate all findings for a single sheet.

    Returns a verdict dict on success, or a fallback dict with
    ``verdict_status='failed'`` on failure.
    """
    from engine.investigation.agent_step_runner import AgentStepRunner

    workbook = sheet_context["workbook"]
    sheet = sheet_context["sheet"]
    tag = f"{workbook}__{sheet}".replace(" ", "_").replace("/", "_")

    runner = AgentStepRunner(
        project_root=project_root,
        model=model,
        opencode_bin=opencode_bin,
        env=env,
    )

    # Write context to a JSON file and attach via --file
    ctx_path = (log_dir or project_root / ".veritas-tmp") / f"verdict_ctx_{tag}.json"
    ctx_path.parent.mkdir(parents=True, exist_ok=True)
    ctx_path.write_text(json.dumps(sheet_context, indent=2, ensure_ascii=False))

    prompt = (
        f"{_VERDICT_PROMPT}\n\n"
        f"## This Sheet\n"
        f"Workbook: {workbook}\n"
        f"Sheet: {sheet}\n"
        f"Number of findings to evaluate: {len(sheet_context.get('findings', []))}\n\n"
        f"Read the attached JSON file for full table structure and findings. "
        f"Return your verdict JSON."
    )

    try:
        result = runner.run(
            role=f"verdict_{tag}",
            prompt=prompt,
            output_validator=_validate_verdict_output,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            files=[ctx_path],
            log_dir=log_dir,
        )
    finally:
        try:
            ctx_path.unlink(missing_ok=True)
        except Exception:
            pass

    if result.status == "success" and result.output:
        output = dict(result.output)
        output["verdict_status"] = "success"
        output["runtime_seconds"] = result.runtime_seconds
        return output

    # Failure fallback — keep findings unjudged
    detail = result.metadata.get("last_detail", "") if result.metadata else ""
    logger.warning("LLM verdict failed for %s/%s: %s", workbook, sheet, detail)
    return {
        "sheet_verdict": "unknown",
        "sheet_pattern": "unknown",
        "verdict_status": "failed",
        "explanation": f"LLM verdict call failed: {detail}",
        "findings": [
            {"id": f.get("id"), "verdict": "uncertain", "confidence": 0.0,
             "explanation": "LLM verdict unavailable"}
            for f in sheet_context.get("findings", [])
        ],
    }


# ── Grouping logic ───────────────────────────────────────────────────

def _group_findings_by_sheet(
    findings_data: dict | None,
    pair_forensics_data: dict | None,
) -> dict[tuple[str, str], list[dict]]:
    """Merge findings from both sources, grouped by (workbook, sheet)."""
    grouped: dict[tuple[str, str], list[dict]] = {}

    def _add(finding: dict) -> None:
        wb = finding.get("workbook", "")
        sh = finding.get("sheet", "")
        if not wb or not sh:
            return
        grouped.setdefault((wb, sh), []).append(finding)

    for f in (findings_data or {}).get("findings", []):
        _add(f)
    for f in (pair_forensics_data or {}).get("findings", []):
        _add(f)

    return grouped


# ── Main entry point ─────────────────────────────────────────────────

def run_source_data_verdict(
    workdir: Path,
    *,
    source_data_dir: Path,
    project_root: Path,
    env: dict[str, str],
    model: str = "dashscope/qwen3.7-plus",
    opencode_bin: str = "opencode",
    force: bool = False,
    progress: Any = None,
    timeout_seconds: int = 300,
    max_retries: int = 2,
    max_workers: int = 4,
) -> dict[str, Any]:
    """Run LLM verdict on all source-data findings.

    Reads ``source_data/findings.json`` and ``source_data/pair_forensics.json``,
    groups by sheet, calls LLM in parallel for each sheet, and writes
    ``source_data/findings_verdict.json``.

    Returns the full verdict result dict.
    """
    output_path = resolve_artifact_path(workdir, "source_data_findings_verdict.json")

    if output_path.exists() and not force:
        logger.info("Reusing existing findings_verdict.json")
        return json.loads(output_path.read_text(encoding="utf-8"))

    findings_path = resolve_artifact_path(workdir, "source_data_findings.json")
    pair_path = resolve_artifact_path(workdir, "source_data_pair_forensics.json")

    findings_data = (
        json.loads(findings_path.read_text(encoding="utf-8"))
        if findings_path.exists()
        else None
    )
    pair_forensics_data = (
        json.loads(pair_path.read_text(encoding="utf-8"))
        if pair_path.exists()
        else None
    )

    if not findings_data and not pair_forensics_data:
        result: dict[str, Any] = {
            "schema_version": "1.0",
            "verdict_status": "skipped",
            "explanation": "No source data findings to adjudicate.",
            "sheets": [],
            "summary": {
                "total_sheets": 0,
                "total_findings": 0,
                "true_positive": 0,
                "false_positive": 0,
                "uncertain": 0,
            },
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        return result

    grouped = _group_findings_by_sheet(findings_data, pair_forensics_data)

    # Profile for per-sheet statistics
    profile_path = resolve_artifact_path(workdir, "source_data_profile.json")
    profile = (
        json.loads(profile_path.read_text(encoding="utf-8"))
        if profile_path.exists()
        else None
    )

    log_dir = resolve_artifact_path(workdir, "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    # Build sheet contexts
    sheet_contexts: list[dict[str, Any]] = []
    for (wb, sh), fs in sorted(grouped.items()):
        ctx = _build_sheet_context(wb, sh, fs, source_data_dir, profile)
        sheet_contexts.append(ctx)

    # Parallel LLM calls
    sheet_verdicts: list[dict[str, Any]] = []
    workers = min(max_workers, len(sheet_contexts)) or 1
    logger.info(
        "Running LLM verdict on %d sheets (%d workers)",
        len(sheet_contexts),
        workers,
    )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_ctx = {
            pool.submit(
                get_sheet_verdict,
                ctx,
                project_root=project_root,
                env=env,
                model=model,
                opencode_bin=opencode_bin,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                log_dir=log_dir,
            ): ctx
            for ctx in sheet_contexts
        }
        for future in as_completed(future_to_ctx):
            ctx = future_to_ctx[future]
            try:
                verdict = future.result()
            except Exception as exc:
                logger.warning(
                    "Verdict exception for %s/%s: %s",
                    ctx["workbook"],
                    ctx["sheet"],
                    exc,
                )
                verdict = {
                    "sheet_verdict": "unknown",
                    "sheet_pattern": "unknown",
                    "verdict_status": "failed",
                    "explanation": f"Exception: {exc}",
                    "findings": [
                        {"id": f.get("id"), "verdict": "uncertain", "confidence": 0.0,
                         "explanation": "LLM verdict unavailable"}
                        for f in ctx.get("findings", [])
                    ],
                }
            # Ensure workbook/sheet are in the verdict
            verdict["workbook"] = ctx["workbook"]
            verdict["sheet"] = ctx["sheet"]
            verdict["finding_count"] = len(ctx.get("findings", []))
            sheet_verdicts.append(verdict)

    # Stable ordering by (workbook, sheet)
    sheet_verdicts.sort(key=lambda v: (v.get("workbook", ""), v.get("sheet", "")))

    # Summary
    tp = fp = un = 0
    for sv in sheet_verdicts:
        for fv in sv.get("findings", []):
            v = fv.get("verdict", "uncertain")
            if v == "true_positive":
                tp += 1
            elif v == "false_positive":
                fp += 1
            else:
                un += 1

    result = {
        "schema_version": "1.0",
        "created_by": "engine/static_audit/tools/source_data_verdict.py",
        "model": model,
        "sheets": sheet_verdicts,
        "summary": {
            "total_sheets": len(sheet_verdicts),
            "total_findings": tp + fp + un,
            "true_positive": tp,
            "false_positive": fp,
            "uncertain": un,
            "failed_sheets": sum(
                1 for sv in sheet_verdicts if sv.get("verdict_status") == "failed"
            ),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    logger.info(
        "Verdict complete: %d sheets, %d TP, %d FP, %d uncertain",
        len(sheet_verdicts),
        tp,
        fp,
        un,
    )
    return result
