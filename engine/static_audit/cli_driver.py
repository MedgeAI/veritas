#!/usr/bin/env python3
"""CLI entry point and argument parsing for the Veritas static audit pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT_PATH = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

from engine.env import load_project_env
from engine.exceptions import AmbiguousPaperPdfError, InvalidPaperPdfError
from engine.llm.config import DEFAULT_LLM_MODEL
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
        "--paper-pdf",
        default=None,
        help="Paper PDF relative path inside paper_dir. Required when multiple PDFs exist.",
    )
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
        choices=["plan", "review", "full"],
        default="full",
        help="opencode Agent mode: plan only tunes deterministic steps, review only interprets artifacts, full does both.",
    )
    parser.add_argument(
        "--agent-model",
        default=DEFAULT_LLM_MODEL,
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


@dataclass(frozen=True, slots=True)
class PdfCandidate:
    path: Path
    relative_path: str
    name: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.relative_path,
            "name": self.name,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class PaperPdfSelection:
    path: Path
    relative_path: str
    source: str
    candidates: list[PdfCandidate]

    def candidate_dicts(self) -> list[dict[str, Any]]:
        return [candidate.to_dict() for candidate in self.candidates]


def pdf_candidates(paper_dir: Path) -> list[PdfCandidate]:
    """扫描 paper_dir 内所有 PDF 文件，按路径排序返回候选列表。

    拒绝逃逸 inputs 目录的 symlink（resolve 后不在 paper_dir 内）。
    """
    paper_dir = paper_dir.resolve()
    candidates: list[PdfCandidate] = []
    for path in sorted(item for item in paper_dir.rglob("*.pdf") if item.is_file()):
        resolved = path.resolve()
        if not resolved.is_relative_to(paper_dir):
            raise InvalidPaperPdfError(f"PDF path escapes input directory: {path}")
        relative_path = resolved.relative_to(paper_dir).as_posix()
        candidates.append(
            PdfCandidate(
                path=resolved,
                relative_path=relative_path,
                name=resolved.name,
                size_bytes=resolved.stat().st_size,
            )
        )
    return candidates


def validate_declared_pdf(paper_dir: Path, declared: str | Path) -> Path:
    """校验 paper_pdf 声明是 paper_dir 内安全、有效的 PDF 相对路径。

    拒绝：绝对路径、..穿越、空路径、非 .pdf 后缀、resolve 后逃逸 paper_dir、文件不存在。
    返回 resolve 后的绝对路径。
    """
    raw = Path(declared)
    raw_text = raw.as_posix().strip()
    if raw.is_absolute() or not raw_text or any(part == ".." for part in raw.parts):
        raise InvalidPaperPdfError(
            f"paper_pdf must be a relative path inside inputs: {declared}"
        )
    if raw.suffix.lower() != ".pdf":
        raise InvalidPaperPdfError(f"paper_pdf must point to a .pdf file: {declared}")

    root = paper_dir.resolve()
    resolved = (root / raw).resolve()
    if not resolved.is_relative_to(root):
        raise InvalidPaperPdfError(f"paper_pdf escapes inputs directory: {declared}")
    if not resolved.is_file():
        raise FileNotFoundError(f"Specified paper PDF does not exist: {declared}")
    return resolved


def _selection(
    paper_dir: Path,
    path: Path,
    source: str,
    candidates: list[PdfCandidate],
) -> PaperPdfSelection:
    root = paper_dir.resolve()
    resolved = path.resolve()
    return PaperPdfSelection(
        path=resolved,
        relative_path=resolved.relative_to(root).as_posix(),
        source=source,
        candidates=candidates,
    )


def discover_pdf(
    paper_dir: Path,
    explicit_pdf: str | Path | None = None,
    explicit_source: str | None = None,
) -> PaperPdfSelection:
    """选择论文正文 PDF。

    返回 PaperPdfSelection（不是 Path），包含选中文件、来源标记和所有候选列表。
    调用方应通过 selection.path 获取绝对路径，通过 selection.source 获取来源。

    决策链（按优先级）：
    1. explicit_pdf 不为 None → source = explicit_source 或 "explicit"
    2. paper_dir/manifest.json 含 paper_pdf 字段 → source = "manifest"
    3. 目录内唯一 PDF → source = "single_pdf"
    4. 多个 PDF → 抛出 AmbiguousPaperPdfError

    Args:
        paper_dir: 输入材料目录（inputs/）
        explicit_pdf: 显式指定的 PDF 相对路径（来自 CLI --paper-pdf 或 Web 端）
        explicit_source: 显式来源标记，默认 "explicit"

    Returns:
        PaperPdfSelection dataclass，包含 path、relative_path、source、candidates

    Raises:
        AmbiguousPaperPdfError: 多个 PDF 且未显式指定
        InvalidPaperPdfError: 声明的路径不安全（绝对路径、..穿越、非 .pdf）
        FileNotFoundError: 无 PDF 或声明的 PDF 不存在
    """
    paper_dir = paper_dir.resolve()
    candidates = pdf_candidates(paper_dir)

    if explicit_pdf is not None:
        return _selection(
            paper_dir,
            validate_declared_pdf(paper_dir, explicit_pdf),
            explicit_source or "explicit",
            candidates,
        )

    manifest_path = paper_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise InvalidPaperPdfError(f"Invalid manifest.json: {exc}") from exc
        declared = manifest.get("paper_pdf")
        if declared:
            return _selection(
                paper_dir,
                validate_declared_pdf(paper_dir, declared),
                "manifest",
                candidates,
            )

    if not candidates:
        raise FileNotFoundError(f"No PDF found in {paper_dir}")
    if len(candidates) == 1:
        only = candidates[0]
        return _selection(paper_dir, only.path, "single_pdf", candidates)

    lines = [
        f"  - {candidate.relative_path} ({candidate.size_bytes // 1024} KB)"
        for candidate in candidates
    ]
    raise AmbiguousPaperPdfError(
        f"Found {len(candidates)} PDF files and cannot determine the paper PDF:\n"
        + "\n".join(lines)
        + "\n\nFix by selecting the paper PDF in the Web UI, passing "
        "--paper-pdf, or adding inputs/manifest.json with paper_pdf."
    )


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
