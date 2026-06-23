#!/usr/bin/env python3
"""Check that prompt files have not drifted from their locked state.

Reads ``configs/opencode/prompts.lock`` and verifies SHA-256 hashes and file
sizes for every listed prompt.  Also checks that
``configs/opencode/generated/tool_contract.md`` is up-to-date when the builder
script is available.

Exit codes::

    0  all files match
    1  drift detected, lock file missing, or listed file missing

Usage::

    uv run python scripts/check_prompts.py
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required.  Run: uv run pip install pyyaml")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = PROJECT_ROOT / "configs" / "opencode" / "prompts.lock"
TOOL_CONTRACT_PATH = (
    PROJECT_ROOT / "configs" / "opencode" / "generated" / "tool_contract.md"
)
BUILD_TOOL_CONTRACT = PROJECT_ROOT / "scripts" / "build_tool_contract.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sha256(path: Path) -> str:
    """Return hex SHA-256 digest of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock(lock_path: Path) -> dict:
    """Parse the YAML lock file and return its contents."""
    with lock_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def check_prompts(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Verify each entry against the file on disk.

    Returns ``(drifted, missing)`` where each element is a dict with details.
    """
    drifted: list[dict] = []
    missing: list[dict] = []

    for entry in entries:
        rel = entry["path"]
        expected_hash = entry["sha256"]
        expected_size = entry["size"]
        full = PROJECT_ROOT / rel

        if not full.exists():
            missing.append({"path": rel, "expected_sha256": expected_hash})
            continue

        actual_hash = sha256(full)
        actual_size = full.stat().st_size

        if actual_hash != expected_hash or actual_size != expected_size:
            drifted.append(
                {
                    "path": rel,
                    "old_sha256": expected_hash,
                    "new_sha256": actual_hash,
                    "old_size": expected_size,
                    "new_size": actual_size,
                }
            )

    return drifted, missing


def check_tool_contract() -> str | None:
    """Return a warning string if ``tool_contract.md`` is stale, else None."""
    if not TOOL_CONTRACT_PATH.exists():
        return (
            "WARNING: configs/opencode/generated/tool_contract.md is missing."
        )

    if not BUILD_TOOL_CONTRACT.exists():
        return None

    try:
        result = subprocess.run(
            [sys.executable, str(BUILD_TOOL_CONTRACT), "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"WARNING: could not run build_tool_contract.py: {exc}"

    if result.returncode != 0:
        return (
            "WARNING: build_tool_contract.py --dry-run failed:\n"
            f"  {result.stderr.strip()}"
        )

    # The builder prints "OUTDATED" to stdout when content differs.
    if "OUTDATED" in result.stdout:
        return (
            "WARNING: tool_contract.md may be outdated. "
            "Run: uv run python scripts/build_tool_contract.py"
        )

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if not LOCK_PATH.exists():
        print(
            f"ERROR: {LOCK_PATH.relative_to(PROJECT_ROOT)} not found. "
            "Run 'make lock-prompts' first."
        )
        return 1

    lock = load_lock(LOCK_PATH)
    entries = lock.get("entries") or []

    if not entries:
        print("WARNING: prompts.lock has no entries.")
        return 0

    drifted, missing = check_prompts(entries)
    rc = 0

    # Report missing files.
    if missing:
        rc = 1
        print("MISSING FILES:")
        for m in missing:
            print(f"  {m['path']}")
        print()

    # Report drift.
    if drifted:
        rc = 1
        print("DRIFT DETECTED:")
        for d in drifted:
            print(f"  {d['path']}")
            print(f"    sha256: {d['old_sha256']} -> {d['new_sha256']}")
            print(f"    size:   {d['old_size']} -> {d['new_size']}")
        print()
        total = len(entries)
        changed = len(drifted) + len(missing)
        print(
            f"DRIFT DETECTED: {changed}/{total} files changed. "
            "Run 'make lock-prompts' to update."
        )
    elif not missing:
        print(f"OK: {len(entries)} prompt files match prompts.lock")

    # Tool-contract freshness check (advisory).
    tc_warn = check_tool_contract()
    if tc_warn:
        print(tc_warn)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
