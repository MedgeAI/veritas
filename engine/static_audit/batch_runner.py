"""Batch benchmark runner — parallel execution of papers × tiers.

Executes ``run_static_audit()`` for every (paper, tier) combination using
a ``ThreadPoolExecutor``.  Each combination is an independent pipeline run
with its own output directory.  Results are collected into a structured
summary suitable for paper ablation tables.

Output layout::

    {output_dir}/
    ├── summary.json        # machine-readable aggregated results
    ├── summary.md          # human-readable comparison table
    ├── manifest.json       # paper → case_id × tier mapping
    └── papers/
        ├── {paper_name}/
        │   ├── bare/       # full audit output for this paper × tier
        │   ├── structured/
        │   └── ...
        └── ...
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from engine.static_audit.config import AuditConfig
from engine.static_audit.pipeline import run_static_audit

logger = logging.getLogger(__name__)

ALL_TIERS = ["bare", "structured", "artifact", "provenance", "dual-layer"]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class BatchRunResult:
    """Result of a single (paper, tier) pipeline run."""

    paper_dir: str
    paper_name: str
    tier: str
    case_id: str | None = None
    exit_code: int = -1
    duration_seconds: float = 0.0
    error: str | None = None
    findings_count: int = 0
    stage_status: dict[str, str] = field(default_factory=dict)


@dataclass
class BatchResult:
    """Aggregated results for an entire batch run."""

    runs: list[BatchRunResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    output_dir: str = ""
    papers_count: int = 0
    tiers_run: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Papers file parser
# ---------------------------------------------------------------------------


def parse_papers_file(path: str | Path) -> list[str]:
    """Read a papers list file, returning non-empty, non-comment lines.

    Lines starting with ``#`` are treated as comments.  Blank lines are
    skipped.  Each remaining line is stripped and treated as a paper
    directory path.
    """
    papers_path = Path(path)
    if not papers_path.is_file():
        raise FileNotFoundError(f"Papers file not found: {papers_path}")

    entries: list[str] = []
    for raw_line in papers_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line)
    return entries


# ---------------------------------------------------------------------------
# Single-task wrapper
# ---------------------------------------------------------------------------


def _run_single(
    paper_dir: str,
    tier: str,
    output_dir: Path,
    progress: Any | None = None,
) -> BatchRunResult:
    """Execute one (paper, tier) pipeline run and return a result record."""
    paper_name = Path(paper_dir).name
    tier_output = output_dir / "papers" / paper_name / tier

    result = BatchRunResult(
        paper_dir=paper_dir,
        paper_name=paper_name,
        tier=tier,
    )

    t0 = time.monotonic()
    try:
        summary = run_static_audit(
            AuditConfig(
                paper_dir=paper_dir,
                output_root=str(tier_output),
                audit_profile="fast",
                benchmark_tier=tier,
            ),
            progress=progress,
        )
        result.exit_code = int(summary.pop("exit_code", -1))
        result.case_id = summary.get("case_id")
        result.findings_count = _count_findings(summary)
        result.stage_status = _extract_stage_status(summary)
    except Exception as exc:
        result.exit_code = -1
        result.error = str(exc)
        logger.exception("Batch run failed: %s × %s", paper_name, tier)
    finally:
        result.duration_seconds = time.monotonic() - t0

    return result


def _count_findings(summary: dict[str, Any]) -> int:
    """Extract total findings count from a pipeline summary dict."""
    # The summary shape depends on the report stage output.
    # Best-effort: look for common keys.
    for key in ("total_findings", "findings_count", "finding_count"):
        if key in summary:
            return int(summary[key])
    return 0


def _extract_stage_status(summary: dict[str, Any]) -> dict[str, str]:
    """Extract per-stage status from a pipeline summary dict."""
    stages: dict[str, str] = {}
    steps = summary.get("steps", [])
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict) and "key" in step and "status" in step:
                stages[step["key"]] = step["status"]
    return stages


# ---------------------------------------------------------------------------
# Summary writers
# ---------------------------------------------------------------------------


def _write_summary_json(batch: BatchResult, output_dir: Path) -> None:
    """Write aggregated results to ``summary.json``."""
    payload = {
        "output_dir": batch.output_dir,
        "papers_count": batch.papers_count,
        "tiers_run": batch.tiers_run,
        "total_duration_seconds": round(batch.total_duration_seconds, 2),
        "runs": [asdict(r) for r in batch.runs],
    }
    path = output_dir / "summary.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_summary_md(batch: BatchResult, output_dir: Path) -> None:
    """Write a human-readable comparison table to ``summary.md``."""
    lines: list[str] = []
    lines.append("# Benchmark Summary\n")
    lines.append(
        f"Papers: {batch.papers_count} | "
        f"Tiers: {', '.join(batch.tiers_run)} | "
        f"Total time: {batch.total_duration_seconds:.1f}s\n"
    )

    # Per-tier aggregation
    tier_stats: dict[str, dict[str, Any]] = {}
    for tier in batch.tiers_run:
        tier_runs = [r for r in batch.runs if r.tier == tier]
        if not tier_runs:
            continue
        durations = [r.duration_seconds for r in tier_runs]
        findings = [r.findings_count for r in tier_runs]
        errors = sum(1 for r in tier_runs if r.exit_code != 0)
        tier_stats[tier] = {
            "count": len(tier_runs),
            "avg_duration": sum(durations) / len(durations),
            "total_findings": sum(findings),
            "errors": errors,
        }

    # Table: Tier | Runs | Avg Duration | Total Findings | Errors
    lines.append("## Tier Comparison\n")
    lines.append("| Tier | Runs | Avg Duration (s) | Total Findings | Errors |")
    lines.append("|------|------|------------------|----------------|--------|")
    for tier in batch.tiers_run:
        if tier not in tier_stats:
            continue
        s = tier_stats[tier]
        lines.append(
            f"| {tier} | {s['count']} | {s['avg_duration']:.1f} "
            f"| {s['total_findings']} | {s['errors']} |"
        )

    lines.append("")

    # Per-paper detail
    lines.append("## Per-Paper Detail\n")
    lines.append("| Paper | Tier | Exit Code | Duration (s) | Findings | Case ID |")
    lines.append("|-------|------|-----------|--------------|----------|---------|")
    for r in sorted(batch.runs, key=lambda x: (x.paper_name, x.tier)):
        case = r.case_id or "—"
        err = f" ({r.error[:40]})" if r.error else ""
        lines.append(
            f"| {r.paper_name} | {r.tier} | {r.exit_code}{err} "
            f"| {r.duration_seconds:.1f} | {r.findings_count} | {case} |"
        )

    lines.append("")
    path = output_dir / "summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_manifest(batch: BatchResult, output_dir: Path) -> None:
    """Write paper → case_id × tier mapping to ``manifest.json``."""
    manifest: dict[str, dict[str, str]] = {}
    for r in batch.runs:
        paper_entry = manifest.setdefault(r.paper_name, {})
        if r.case_id:
            paper_entry[r.tier] = r.case_id

    path = output_dir / "manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_batch(
    papers: list[str],
    tiers: list[str],
    *,
    output_dir: str = "outputs/benchmark",
    max_workers: int = 4,
    progress: Any | None = None,
) -> BatchResult:
    """Execute papers × tiers in parallel and return aggregated results.

    Parameters
    ----------
    papers:
        List of paper directory paths (one per entry).
    tiers:
        List of tier names to run for each paper.
    output_dir:
        Root output directory.  Each paper × tier writes to
        ``{output_dir}/papers/{paper_name}/{tier}/``.
    max_workers:
        Maximum parallel pipeline runs.  MinerU has API rate limits;
        keep this conservative (default 4).
    progress:
        Optional progress callback forwarded to each pipeline run.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    batch = BatchResult(
        output_dir=str(out),
        papers_count=len(papers),
        tiers_run=list(tiers),
    )

    tasks = [(p, t) for p in papers for t in tiers]
    total = len(tasks)
    logger.info("Batch run: %d papers × %d tiers = %d tasks", len(papers), len(tiers), total)

    t0 = time.monotonic()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_run_single, paper, tier, out, progress): (paper, tier)
            for paper, tier in tasks
        }
        for future in as_completed(futures):
            paper, tier = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = BatchRunResult(
                    paper_dir=paper,
                    paper_name=Path(paper).name,
                    tier=tier,
                    error=str(exc),
                )
            batch.runs.append(result)
            done = len(batch.runs)
            status = "OK" if result.exit_code == 0 else f"FAIL({result.exit_code})"
            logger.info(
                "[%d/%d] %s × %s → %s (%.1fs)",
                done, total, result.paper_name, tier, status, result.duration_seconds,
            )

    batch.total_duration_seconds = time.monotonic() - t0

    # Sort runs deterministically: by paper_name then tier order
    tier_order = {t: i for i, t in enumerate(tiers)}
    batch.runs.sort(key=lambda r: (r.paper_name, tier_order.get(r.tier, 99)))

    # Write summaries
    _write_summary_json(batch, out)
    _write_summary_md(batch, out)
    _write_manifest(batch, out)

    logger.info(
        "Batch complete: %d/%d succeeded in %.1fs.  Output: %s",
        sum(1 for r in batch.runs if r.exit_code == 0),
        total,
        batch.total_duration_seconds,
        out,
    )

    return batch
