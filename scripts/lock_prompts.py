#!/usr/bin/env python3
"""Lock prompt files to their current content hashes.

Computes sha256 and file size for each prompt file tracked by Veritas,
then writes the results to configs/opencode/prompts.lock (YAML format).

Usage:
    python scripts/lock_prompts.py           # regenerate lock file
    python scripts/lock_prompts.py --check   # verify no drift, exit 1 if changed
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Canonical prompt files to lock (paths relative to project root).
PROMPT_FILES = [
    ".opencode/skills/research-integrity-auditor/SKILL.md",
    "configs/opencode/veritas-agent.md",
    "configs/opencode/biomed-research-audit-methodology.md",
    "configs/methodology/general.md",
    "configs/methodology/source-data.md",
    "configs/methodology/biomed-wetlab.md",
    "configs/methodology/bioinfo.md",
    "configs/methodology/visual-forensics.md",
]

LOCK_FILE = Path("configs/opencode/prompts.lock")
SCHEMA_VERSION = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_file(rel_path: str, abs_path: Path) -> dict:
    stat = abs_path.stat()
    return {
        "path": rel_path,
        "sha256": sha256(abs_path),
        "size": stat.st_size,
    }


def load_existing_lock() -> dict | None:
    if not LOCK_FILE.exists():
        return None
    with LOCK_FILE.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None
    return data


def build_diff_summary(
    old_entries: list[dict], new_entries: list[dict]
) -> list[str]:
    old_map = {entry["path"]: entry for entry in old_entries}
    new_map = {entry["path"]: entry for entry in new_entries}

    lines: list[str] = []
    all_paths = sorted(set(new_map.keys()) | set(old_map.keys()))
    for path_str in all_paths:
        old = old_map.get(path_str)
        new = new_map.get(path_str)
        if old is None and new is not None:
            lines.append(
                f"  + {path_str}  (new, sha256={new['sha256'][:16]}, size={new['size']})"
            )
        elif new is None and old is not None:
            lines.append(
                f"  - {path_str}  (removed, old sha256={old['sha256'][:16]})"
            )
        elif old is not None and new is not None and (
            old["sha256"] != new["sha256"] or old["size"] != new["size"]
        ):
            size_delta = new["size"] - old["size"]
            lines.append(
                f"  ~ {path_str}  sha256 {old['sha256'][:16]} -> {new['sha256'][:16]}"
                f"  size {old['size']} -> {new['size']} (delta={size_delta:+d})"
            )
    return lines


def collect_current_entries(root: Path) -> list[dict]:
    entries: list[dict] = []
    for rel_path in PROMPT_FILES:
        full_path = root / rel_path
        if not full_path.exists():
            print(f"ERROR: prompt file not found: {rel_path}", file=sys.stderr)
            raise FileNotFoundError(rel_path)
        entries.append(scan_file(rel_path, full_path))
    return entries


def run_check(root: Path) -> int:
    existing = load_existing_lock()
    if existing is None:
        print(f"Lock file not found: {LOCK_FILE}", file=sys.stderr)
        print("Run 'make lock-prompts' to generate it.", file=sys.stderr)
        return 1

    try:
        new_entries = collect_current_entries(root)
    except FileNotFoundError:
        return 1

    old_entries = existing.get("entries", [])
    diff_lines = build_diff_summary(old_entries, new_entries)
    if diff_lines:
        print(f"Prompt files have changed since {LOCK_FILE}:", file=sys.stderr)
        for line in diff_lines:
            print(line, file=sys.stderr)
        print(
            f"\nRun 'make lock-prompts' to update the lock file.",
            file=sys.stderr,
        )
        return 1

    print(f"All {len(new_entries)} prompt files match locked hashes.")
    return 0


def run_lock(root: Path) -> int:
    existing = load_existing_lock()

    try:
        new_entries = collect_current_entries(root)
    except FileNotFoundError:
        return 1

    # Print diff summary if there is an existing lock.
    if existing is not None:
        old_entries = existing.get("entries", [])
        diff_lines = build_diff_summary(old_entries, new_entries)
        if diff_lines:
            print(f"Prompt changes ({LOCK_FILE}):")
            for line in diff_lines:
                print(line)
            print()
        else:
            print("No prompt changes detected.")
            return 0

    # Write the new lock file.
    lock_data = {
        "schema_version": SCHEMA_VERSION,
        "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": new_entries,
    }
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w", encoding="utf-8") as handle:
        handle.write("# AUTO-GENERATED by scripts/lock_prompts.py — do not edit manually\n")
        yaml.dump(
            lock_data,
            handle,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

    print(f"Locked {len(new_entries)} prompt files -> {LOCK_FILE}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lock prompt files to their current content hashes."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify prompt files match locked hashes; exit 1 if drifted.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent

    if args.check:
        return run_check(root)
    return run_lock(root)


if __name__ == "__main__":
    sys.exit(main())
