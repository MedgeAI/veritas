"""CLI entry point for ``benchmark-batch`` subcommand.

Usage::

    uv run python -m cli.main benchmark-batch papers.txt \
        --output-dir outputs/benchmark \
        --workers 4 \
        --tier all
"""

from __future__ import annotations

import json
import sys
from typing import Any

from engine.static_audit.batch_runner import ALL_TIERS, parse_papers_file, run_batch


def add_subparsers(subparsers: Any) -> None:
    """Register ``benchmark-batch`` on an argparse *subparsers* group."""
    parser = subparsers.add_parser(
        "benchmark-batch",
        help="Run benchmark ablation experiments across papers × tiers.",
    )
    parser.add_argument(
        "papers_file",
        help="Text file with one paper directory path per line. "
        "Lines starting with # are comments; blank lines are ignored.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/benchmark",
        help="Root output directory (default: outputs/benchmark).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Max parallel pipeline runs (default: 4).",
    )
    parser.add_argument(
        "--tier",
        choices=ALL_TIERS + ["all"],
        default="all",
        help="Which tier(s) to run. 'all' runs every tier (default).",
    )


def dispatch(args: Any) -> int:
    """Execute the benchmark-batch command."""
    papers_file = args.papers_file
    output_dir = args.output_dir
    workers = args.workers
    tier_arg = args.tier

    # Resolve tiers
    tiers = ALL_TIERS if tier_arg == "all" else [tier_arg]

    # Parse papers list
    try:
        papers = parse_papers_file(papers_file)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not papers:
        print("Error: papers file is empty (no valid entries).", file=sys.stderr)
        return 1

    print(
        f"Benchmark batch: {len(papers)} papers × {len(tiers)} tier(s) "
        f"= {len(papers) * len(tiers)} tasks, {workers} workers",
        file=sys.stderr,
    )

    result = run_batch(
        papers=papers,
        tiers=tiers,
        output_dir=output_dir,
        max_workers=workers,
    )

    # Print summary to stdout
    succeeded = sum(1 for r in result.runs if r.exit_code == 0)
    failed = sum(1 for r in result.runs if r.exit_code != 0)

    print(json.dumps({
        "papers": result.papers_count,
        "tiers": result.tiers_run,
        "total_tasks": len(result.runs),
        "succeeded": succeeded,
        "failed": failed,
        "total_duration_seconds": round(result.total_duration_seconds, 2),
        "output_dir": result.output_dir,
    }, ensure_ascii=False, indent=2))

    return 0 if failed == 0 else 1
