#!/usr/bin/env python3
"""CLI entry point and argument parsing for the Veritas static audit pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

from engine.env import load_project_env
from engine.static_audit._shared import PROJECT_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Veritas paper audit from a local paper directory."
    )
    parser.add_argument(
        "paper_dir", help="Directory containing paper PDF and optional Source Data."
    )
    parser.add_argument("--case-id", help="Case id used under outputs/<case-id>.")
    parser.add_argument(
        "--output-root", default="outputs", help="Output root directory."
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Remove the case audit workdir before running; guarantees previous MinerU outputs are not reused.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run steps even if expected outputs already exist.",
    )
    parser.add_argument(
        "--no-env-file",
        action="store_true",
        help="Do not load local .env into subprocess environment.",
    )
    parser.add_argument(
        "--agent-mode",
        choices=["off", "plan", "review", "full"],
        default="full",
        help="opencode Agent mode: off disables Agent, plan only tunes deterministic steps, review only interprets artifacts, full does both.",
    )
    parser.add_argument(
        "--agent-model",
        default="dashscope/qwen3.7-plus",
        help="opencode model id used for Agent plan/review.",
    )
    parser.add_argument(
        "--opencode-bin",
        default="opencode",
        help="opencode executable path.",
    )
    parser.add_argument(
        "--agent-timeout-seconds",
        type=int,
        default=300,
        help="Timeout for each opencode Agent call.",
    )
    parser.add_argument(
        "--agent-max-retries",
        type=int,
        default=1,
        help="Retries after invalid Agent JSON output.",
    )
    parser.add_argument(
        "--skip-unavailable-tools",
        action="store_true",
        help="Allow pipeline to continue when tools fail due to missing environment prerequisites (GPU, Docker). "
        "Without this flag, environment failures abort the pipeline.",
    )
    return parser.parse_args()


def safe_remove_workdir(workdir: Path, output_root: Path) -> None:
    if not workdir.exists():
        return
    resolved_workdir = workdir.resolve()
    resolved_output_root = output_root.resolve()
    if resolved_workdir == resolved_output_root:
        raise ValueError(f"Refusing to remove output root: {resolved_workdir}")
    if resolved_workdir.name != "research-integrity-audit":
        raise ValueError(f"Refusing to remove unexpected workdir: {resolved_workdir}")
    if not resolved_workdir.is_relative_to(resolved_output_root):
        raise ValueError(
            f"Refusing to remove path outside output root: {resolved_workdir}"
        )
    shutil.rmtree(resolved_workdir)


def load_env(include_env_file: bool) -> dict[str, str]:
    return load_project_env(PROJECT_ROOT, include_env_file=include_env_file)


def discover_pdf(paper_dir: Path) -> Path:
    pdfs = sorted(path for path in paper_dir.glob("*.pdf") if path.is_file())
    if not pdfs:
        raise FileNotFoundError(f"No PDF found in {paper_dir}")
    # Deterministic choice for the MVP; future manifest should remove ambiguity.
    return pdfs[0]


def exists_all(paths: list[Path]) -> bool:
    return all(path.exists() for path in paths)


def text_tail(value: str, limit: int = 1000) -> str:
    value = value.strip()
    if not value:
        return ""
    return value[-limit:]


def main() -> int:
    # Local import to avoid circular dependency at module load time.
    from engine.static_audit.pipeline import _run_static_audit_from_args

    summary = _run_static_audit_from_args(parse_args())
    exit_code = int(summary.pop("exit_code"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
