from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine._logging import configure_logging
from cli.commands import audit_paper, precheck, report, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veritas",
        description="CLI demo for computational research verification.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Run verification from a manifest file."
    )
    run_parser.add_argument("manifest", help="Path to veritas manifest JSON.")
    run_parser.add_argument(
        "--output-dir",
        default="outputs/local_runs/latest",
        help="Directory for generated report artifacts.",
    )
    run_parser.add_argument(
        "--role",
        choices=["author", "reviewer"],
        default="author",
        help="Role view to encode in the generated report.",
    )

    precheck_parser = subparsers.add_parser(
        "precheck", help="Run non-executing readiness checks."
    )
    precheck_parser.add_argument("manifest", help="Path to veritas manifest JSON.")
    precheck_parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional directory for generated precheck artifacts.",
    )

    report_parser = subparsers.add_parser(
        "report", help="Render markdown/html from an existing report.json."
    )
    report_parser.add_argument("report_json", help="Path to report.json.")
    report_parser.add_argument(
        "--output-dir",
        default="outputs/rendered_report",
        help="Directory for rendered markdown/html files.",
    )

    audit_parser = subparsers.add_parser(
        "audit-paper",
        help="Run first-stage paper audit from a local paper directory.",
    )
    audit_parser.add_argument(
        "paper_dir", help="Directory containing paper PDF and optional Source Data."
    )
    audit_parser.add_argument("--case-id", help="Case id used under outputs/<case-id>.")
    audit_parser.add_argument(
        "--output-root", default="outputs", help="Output root directory."
    )
    audit_parser.add_argument(
        "--fresh",
        action="store_true",
        help="Remove the case audit workdir before running; prevents reuse of existing MinerU outputs.",
    )
    audit_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run steps even if expected outputs already exist.",
    )
    audit_parser.add_argument(
        "--no-env-file",
        action="store_true",
        help="Do not load local .env into subprocess environment.",
    )
    audit_parser.add_argument(
        "--agent-mode",
        choices=["off", "plan", "review", "full"],
        default="full",
        help="opencode Agent mode for audit planning/review.",
    )
    audit_parser.add_argument(
        "--agent-model",
        default="dashscope/qwen3.7-plus",
        help="opencode model id used for Agent plan/review.",
    )
    audit_parser.add_argument(
        "--opencode-bin",
        default="opencode",
        help="opencode executable path.",
    )
    audit_parser.add_argument(
        "--agent-timeout-seconds",
        type=int,
        default=300,
        help="Timeout for each opencode Agent call.",
    )
    audit_parser.add_argument(
        "--agent-max-retries",
        type=int,
        default=1,
        help="Retries after invalid Agent JSON output.",
    )
    audit_parser.add_argument(
        "--skip-unavailable-tools",
        action="store_true",
        help="Allow pipeline to continue when tools fail due to missing environment prerequisites (GPU, Docker). "
        "Without this flag, environment failures abort the pipeline.",
    )
    audit_parser.add_argument(
        "--progress",
        choices=["auto", "plain", "jsonl", "off"],
        default="auto",
        help="Progress output mode. Progress is written to stderr; final summary JSON stays on stdout.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return run.handle(args.manifest, args.output_dir, args.role)
    if args.command == "precheck":
        return precheck.handle(args.manifest, args.output_dir)
    if args.command == "report":
        return report.handle(args.report_json, args.output_dir)
    if args.command == "audit-paper":
        return audit_paper.handle(
            args.paper_dir,
            args.case_id,
            args.output_root,
            args.force,
            args.fresh,
            args.no_env_file,
            args.agent_mode,
            args.agent_model,
            args.opencode_bin,
            args.agent_timeout_seconds,
            args.agent_max_retries,
            args.skip_unavailable_tools,
            args.progress,
        )
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
