"""Runtime path normalization for web-visible audit artifacts."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def configured_output_root(output_root: str | Path | None = None) -> Path:
    """Return the configured output root as an absolute path."""
    raw = Path(str(output_root or os.environ.get("VERITAS_OUTPUT_ROOT", "outputs")))
    if raw.is_absolute():
        return raw
    return (PROJECT_ROOT / raw).resolve()


def normalize_workdir_path(
    value: str | Path,
    *,
    output_root: str | Path | None = None,
) -> Path:
    """Map persisted workdir paths from older runtimes to this runtime.

    Historical runs may have stored absolute paths from Docker or earlier dev
    wrappers such as ``/app/outputs/...`` or ``/workspace/outputs/...``.  The
    durable part of those paths is the suffix under ``outputs``; the current
    root comes from configuration.
    """
    raw = Path(str(value))
    if not raw.is_absolute():
        return (PROJECT_ROOT / raw).resolve()
    if raw.exists():
        return raw

    candidates = tuple(
        _output_root_candidates(raw, configured_output_root(output_root))
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else raw


def _output_root_candidates(raw: Path, current_output_root: Path) -> tuple[Path, ...]:
    parts = raw.parts
    indexes = [index for index, part in enumerate(parts) if part == "outputs"]
    candidates: list[Path] = []
    for index in reversed(indexes):
        suffix = parts[index + 1 :]
        if suffix:
            candidates.append(current_output_root.joinpath(*suffix))
    return tuple(candidates)
