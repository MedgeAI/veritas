"""CLI commands for Veritas-Auditor reproduction / benchmark workflow.

Provides three subcommands under the ``reproduce`` namespace:

* ``reproduce run``       -- end-to-end audit (stub, not yet connected)
* ``reproduce benchmark`` -- run a VeritasBench evaluation suite
* ``reproduce mock``      -- generate synthetic mock claims

The module exposes both:

* a Click command group (``reproduce``) for callers that prefer Click, and
* an ``add_subparsers(subparsers)`` helper that registers the same commands
  with an ``argparse`` parent parser -- used by ``cli/main.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Click interface
# ---------------------------------------------------------------------------

try:
    import click

    @click.group("reproduce", help="Veritas-Auditor reproduction & benchmark commands.")
    def reproduce() -> None:
        """Veritas-Auditor reproduction & benchmark commands."""

    @reproduce.command("run", help="Run end-to-end Veritas-Auditor audit.")
    @click.option("--paper", type=click.Path(), required=True, help="Path to paper PDF.")
    @click.option("--code", type=click.Path(), default=None, help="Path to code repository.")
    @click.option(
        "--output-dir",
        type=click.Path(),
        default="outputs/reproduce/latest",
        help="Directory for generated artifacts.",
    )
    @click.option(
        "--far-alpha",
        type=float,
        default=0.05,
        show_default=True,
        help="False-accusation-rate threshold.",
    )
    def _click_run(
        paper: str, code: str | None, output_dir: str, far_alpha: float
    ) -> None:
        rc = handle_run(paper=paper, code=code, output_dir=output_dir, far_alpha=far_alpha)
        sys.exit(rc)

    @reproduce.command("benchmark", help="Run a VeritasBench evaluation suite.")
    @click.option(
        "--suite",
        type=str,
        default="smoke_test",
        show_default=True,
        help="Benchmark suite name.",
    )
    @click.option(
        "--output-dir",
        type=click.Path(),
        default=None,
        help="Optional directory for JSON results.",
    )
    @click.option(
        "--far-alpha",
        type=float,
        default=0.05,
        show_default=True,
        help="False-accusation-rate threshold.",
    )
    def _click_benchmark(suite: str, output_dir: str | None, far_alpha: float) -> None:
        rc = handle_benchmark(suite=suite, output_dir=output_dir, far_alpha=far_alpha)
        sys.exit(rc)

    @reproduce.command("experiment-plan", help="Prepare a reproducible VeritasBench experiment plan.")
    @click.option(
        "--config",
        "config_path",
        type=click.Path(),
        default="configs/experiments/veritasbench_b1_b5.yaml",
        show_default=True,
        help="Experiment YAML contract.",
    )
    @click.option("--base-path", default="benchmarks/veritasbench", show_default=True)
    @click.option(
        "--output-dir",
        default="outputs/experiments/veritasbench",
        show_default=True,
    )
    @click.option(
        "--allow-partial",
        is_flag=True,
        help="Allow a non-empty pilot subset; never use for final results.",
    )
    def _click_experiment_plan(
        config_path: str,
        base_path: str,
        output_dir: str,
        allow_partial: bool,
    ) -> None:
        rc = handle_experiment_plan(
            config_path=config_path,
            base_path=base_path,
            output_dir=output_dir,
            allow_partial=allow_partial,
        )
        sys.exit(rc)

    @reproduce.command("mock", help="Generate mock claims for development.")
    @click.option(
        "--num-claims",
        type=int,
        default=50,
        show_default=True,
        help="Number of mock claims to generate.",
    )
    @click.option(
        "--output-dir",
        type=click.Path(),
        default="outputs/mock_claims",
        show_default=True,
        help="Directory to write mock claim JSON.",
    )
    def _click_mock(num_claims: int, output_dir: str) -> None:
        rc = handle_mock(num_claims=num_claims, output_dir=output_dir)
        sys.exit(rc)

    _HAVE_CLICK = True
except ImportError:  # pragma: no cover -- click is optional for this module
    _HAVE_CLICK = False


# ---------------------------------------------------------------------------
# Handler implementations (framework-agnostic)
# ---------------------------------------------------------------------------


def handle_run(
    *,
    paper: str,
    code: str | None = None,
    output_dir: str = "outputs/reproduce/latest",
    far_alpha: float = 0.05,
) -> int:
    """End-to-end audit entry point.

    Currently a stub -- the real pipeline wiring is not yet connected.
    """
    print("=" * 60)
    print("Veritas-Auditor run")
    print("=" * 60)
    print(f"  paper:      {paper}")
    print(f"  code:       {code or '(not provided)'}")
    print(f"  output-dir: {output_dir}")
    print(f"  far-alpha:  {far_alpha}")
    print()
    print("Veritas-Auditor run not yet connected to real pipeline.")
    print("This command is a placeholder for the upcoming pipeline integration.")
    return 0


def handle_benchmark(
    *,
    suite: str = "smoke_test",
    output_dir: str | None = None,
    far_alpha: float = 0.05,
) -> int:
    """Run a VeritasBench evaluation suite and print metrics."""
    from engine.reproduction.benchmark.case_loader import BenchmarkCaseLoader
    from engine.reproduction.benchmark.runner import BenchmarkRunner

    case_loader = BenchmarkCaseLoader()
    runner = BenchmarkRunner(case_loader=case_loader)
    result = runner.run(suite_name=suite, far_alpha=far_alpha)

    # Print human-readable summary
    print("=" * 60)
    print(f"VeritasBench  suite={result.suite_name}")
    print("=" * 60)
    print(f"  cases:     {result.num_cases}")
    print(f"  claims:    {result.num_claims}")
    print(f"  relations: {result.num_relations}")
    print()
    print("Metrics:")
    for metric_name, metric_value in result.metrics.items():
        print(f"  {metric_name:<24s} {metric_value:.4f}")

    if output_dir is not None:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        results_file = out_path / f"benchmark_{result.suite_name}.json"
        results_file.write_text(
            _serialize_benchmark_result(result), encoding="utf-8"
        )
        print(f"\nResults written to: {results_file}")

    return 0


def handle_experiment_plan(
    *,
    config_path: str = "configs/experiments/veritasbench_b1_b5.yaml",
    base_path: str = "benchmarks/veritasbench",
    output_dir: str = "outputs/experiments/veritasbench",
    allow_partial: bool = False,
) -> int:
    """Validate the frozen dataset and write the deterministic run plan."""
    from engine.reproduction.benchmark.experiment_runner import (
        ExperimentExecutionError,
        ExperimentLedger,
    )

    try:
        prepared = ExperimentLedger(
            config_path,
            base_path=base_path,
            output_dir=output_dir,
            allow_partial=allow_partial,
        ).prepare()
    except (ExperimentExecutionError, FileNotFoundError, ValueError) as exc:
        print(f"Experiment plan failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "experiment_id": prepared.spec.experiment_id,
                "config_digest": prepared.spec.config_digest,
                "plan_digest": prepared.plan["plan_digest"],
                "cases": len(prepared.cases),
                "runs": len(prepared.plan["runs"]),
                "partial": prepared.plan["partial"],
                "output_dir": str(prepared.output_dir),
                "status": "ready",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def handle_mock(
    *,
    num_claims: int = 50,
    output_dir: str = "outputs/mock_claims",
) -> int:
    """Generate mock claims and write to *output_dir*."""
    from engine.reproduction.mock_data import generate_mock_claims

    claims = generate_mock_claims(num_claims=num_claims)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    output_file = out_path / f"mock_claims_{num_claims}.json"
    output_file.write_text(
        json.dumps(claims, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )

    print(f"Generated {len(claims)} mock claims.")
    print(f"Written to: {output_file}")
    return 0


# ---------------------------------------------------------------------------
# argparse integration (used by cli/main.py)
# ---------------------------------------------------------------------------


def add_subparsers(subparsers: Any) -> None:
    """Register ``reproduce`` sub-command tree on an argparse *subparsers* group."""
    reproduce_parser = subparsers.add_parser(
        "reproduce",
        help="Veritas-Auditor reproduction & benchmark commands.",
    )
    sub = reproduce_parser.add_subparsers(dest="reproduce_command", required=True)

    # -- reproduce run -----------------------------------------------------
    run_parser = sub.add_parser("run", help="Run end-to-end Veritas-Auditor audit.")
    run_parser.add_argument("--paper", required=True, help="Path to paper PDF.")
    run_parser.add_argument("--code", default=None, help="Path to code repository.")
    run_parser.add_argument(
        "--output-dir",
        default="outputs/reproduce/latest",
        help="Directory for generated artifacts.",
    )
    run_parser.add_argument(
        "--far-alpha",
        type=float,
        default=0.05,
        help="False-accusation-rate threshold (default: 0.05).",
    )

    # -- reproduce benchmark -----------------------------------------------
    bench_parser = sub.add_parser("benchmark", help="Run a VeritasBench evaluation suite.")
    bench_parser.add_argument(
        "--suite", default="smoke_test", help="Benchmark suite name."
    )
    bench_parser.add_argument(
        "--output-dir", default=None, help="Optional directory for JSON results."
    )
    bench_parser.add_argument(
        "--far-alpha",
        type=float,
        default=0.05,
        help="False-accusation-rate threshold (default: 0.05).",
    )

    # -- reproduce experiment-plan ----------------------------------------
    plan_parser = sub.add_parser(
        "experiment-plan",
        help="Validate VeritasBench and write the deterministic B1-B5 run plan.",
    )
    plan_parser.add_argument(
        "--config",
        dest="config_path",
        default="configs/experiments/veritasbench_b1_b5.yaml",
        help="Experiment YAML contract.",
    )
    plan_parser.add_argument(
        "--base-path",
        default="benchmarks/veritasbench",
        help="VeritasBench root directory.",
    )
    plan_parser.add_argument(
        "--output-dir",
        default="outputs/experiments/veritasbench",
        help="Experiment ledger output directory.",
    )
    plan_parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow a non-empty pilot subset; never use for final results.",
    )

    # -- reproduce mock ----------------------------------------------------
    mock_parser = sub.add_parser("mock", help="Generate mock claims for development.")
    mock_parser.add_argument(
        "--num-claims",
        type=int,
        default=50,
        help="Number of mock claims to generate (default: 50).",
    )
    mock_parser.add_argument(
        "--output-dir",
        default="outputs/mock_claims",
        help="Directory to write mock claim JSON.",
    )


def dispatch(args: Any) -> int:
    """Route a parsed ``reproduce`` argparse invocation to the right handler."""
    cmd = args.reproduce_command
    if cmd == "run":
        return handle_run(
            paper=args.paper,
            code=args.code,
            output_dir=args.output_dir,
            far_alpha=args.far_alpha,
        )
    if cmd == "benchmark":
        return handle_benchmark(
            suite=args.suite,
            output_dir=args.output_dir,
            far_alpha=args.far_alpha,
        )
    if cmd == "experiment-plan":
        return handle_experiment_plan(
            config_path=args.config_path,
            base_path=args.base_path,
            output_dir=args.output_dir,
            allow_partial=args.allow_partial,
        )
    if cmd == "mock":
        return handle_mock(
            num_claims=args.num_claims,
            output_dir=args.output_dir,
        )
    raise ValueError(f"Unknown reproduce subcommand: {cmd}")


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    """Best-effort JSON serialiser for dataclass-shaped objects."""
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(obj)
    return str(obj)


def _serialize_benchmark_result(result: Any) -> str:
    """Serialize a BenchmarkResult to a JSON string."""
    payload = {
        "suite_name": result.suite_name,
        "num_cases": result.num_cases,
        "num_claims": result.num_claims,
        "num_relations": result.num_relations,
        "metrics": result.metrics,
        "claim_verdicts": [
            {
                "claim_id": v.claim_id,
                "verdict": v.verdict,
                "confidence": v.confidence,
                "far_risk": v.far_risk,
            }
            for v in result.claim_verdicts
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
