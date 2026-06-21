"""Material completeness check endpoint.

Scans the case directory for PDF, source data, code, and environment files.
Returns per-category status, dynamic detail (file count + human-readable size),
and an overall completeness score.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from ..dependencies import AppDependencies, get_app_dependencies, require_case_access
from ..models import CaseRecord

router = APIRouter(tags=["materials"])

_PDF_EXTS = {".pdf"}
_DATA_EXTS = {
    ".csv",
    ".csv.gz",
    ".dta",
    ".feather",
    ".gct",
    ".h5",
    ".hdf5",
    ".json",
    ".loom",
    ".mtx",
    ".mtx.gz",
    ".parquet",
    ".rdata",
    ".rds",
    ".sav",
    ".tsv",
    ".tsv.gz",
    ".txt",
    ".txt.gz",
    ".xls",
    ".xlsx",
}
_CODE_EXTS = {".py", ".r", ".rmd", ".ipynb"}
_ENV_FILENAMES = {
    "conda.yml",
    "environment.yaml",
    "environment.yml",
    "packages.txt",
    "pyproject.toml",
    "renv.lock",
    "requirements.txt",
}


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _count_files(
    directory: Path, extensions: set[str] | None = None
) -> tuple[int, int]:
    """Return (file_count, total_bytes) for files under *directory*.

    *extensions* filters by suffix (lower-cased).  ``None`` means all files.
    Returns ``(0, 0)`` if the directory does not exist.
    """
    if not directory.is_dir():
        return 0, 0
    files = [
        f
        for f in directory.rglob("*")
        if f.is_file() and _matches_extension(f, extensions)
    ]
    total_size = sum(f.stat().st_size for f in files)
    return len(files), total_size


def _matches_extension(path: Path, extensions: set[str] | None) -> bool:
    if extensions is None:
        return True
    name = path.name.lower()
    return any(name.endswith(extension) for extension in extensions)


def _find_named_files(directories: list[Path], names: set[str]) -> list[Path]:
    found: dict[Path, Path] = {}
    lowered = {name.lower() for name in names}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.name.lower() in lowered:
                found[path.resolve()] = path
    return sorted(found.values(), key=lambda item: str(item))


@router.get("/cases/{case_id}/materials")
async def check_materials(
    case_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    case_dir = deps.store.case_dir(case_id)
    inputs_dir = case_dir / "inputs"

    # --- PDF -----------------------------------------------------------
    pdf_count, pdf_size = _count_files(inputs_dir, _PDF_EXTS)
    pdf_status = "ok" if pdf_count > 0 else "missing"
    pdf_detail = (
        f"{pdf_count} 个 PDF 文件 ({_format_size(pdf_size)})"
        if pdf_count > 0
        else "未找到 PDF 文件"
    )

    # --- Source Data ---------------------------------------------------
    # Scan both inputs/ (flat uploads) and source_data/ (organised dirs).
    sd_count_in, sd_size_in = _count_files(inputs_dir, _DATA_EXTS)
    sd_count_sd, sd_size_sd = _count_files(case_dir / "source_data", _DATA_EXTS)
    sd_count = sd_count_in + sd_count_sd
    sd_size = sd_size_in + sd_size_sd
    sd_status = "ok" if sd_count > 0 else "missing"
    sd_detail = (
        f"{sd_count} 个数据文件 ({_format_size(sd_size)})"
        if sd_count > 0
        else "未找到 Source Data"
    )

    # --- Code ----------------------------------------------------------
    code_count, code_size = _count_files(case_dir / "code", _CODE_EXTS)
    # Also check code files uploaded to inputs/
    code_count_in, code_size_in = _count_files(inputs_dir, _CODE_EXTS)
    code_count += code_count_in
    code_size += code_size_in
    code_status = "provided" if code_count > 0 else "missing"
    code_detail = (
        f"{code_count} 个脚本文件 ({_format_size(code_size)})"
        if code_count > 0
        else "未提供代码"
    )

    # --- Environment ---------------------------------------------------
    env_paths = _find_named_files(
        [inputs_dir, case_dir / "source_data", case_dir / "code"], _ENV_FILENAMES
    )
    for name in sorted(_ENV_FILENAMES):
        root_file = case_dir / name
        if root_file.is_file():
            env_paths.append(root_file)
    env_files = []
    seen_env_files: set[str] = set()
    for path in sorted({p.resolve(): p for p in env_paths}.values(), key=str):
        try:
            label = str(path.relative_to(case_dir))
        except ValueError:
            label = path.name
        if label not in seen_env_files:
            env_files.append(label)
            seen_env_files.add(label)
    env_status = "provided" if env_files else "missing"
    env_detail = ", ".join(env_files) if env_files else "未提供环境文件"

    # --- Completeness score --------------------------------------------
    completeness_score = sum(
        [
            30 if pdf_status == "ok" else 0,
            30 if sd_status == "ok" else 0,
            20 if code_status == "provided" else 0,
            20 if env_status == "provided" else 0,
        ]
    )

    return {
        "pdf": {
            "status": pdf_status,
            "detail": pdf_detail,
            "count": pdf_count,
            "size_bytes": pdf_size,
        },
        "source_data": {
            "status": sd_status,
            "detail": sd_detail,
            "count": sd_count,
            "size_bytes": sd_size,
        },
        "code": {
            "status": code_status,
            "detail": code_detail,
            "count": code_count,
            "size_bytes": code_size,
        },
        "environment": {
            "status": env_status,
            "detail": env_detail,
            "files": env_files,
        },
        "completeness_score": completeness_score,
    }
