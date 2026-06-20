#!/usr/bin/env python3
"""Migration: set owner = 'operator' for all existing cases without an owner field.

Loads every case.json from web_data/cases/, ensures the owner field is set to
'operator' (the legacy default), and saves the file back.

Usage:
    python scripts/migrate_cases_to_operator.py [--data-root web_data] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the project root is on sys.path so local imports work when invoked directly.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

DEFAULT_DATA_ROOT = "web_data"
DEFAULT_OWNER = "operator"


def migrate_cases(data_root: Path, dry_run: bool = False) -> int:
    """Set owner = DEFAULT_OWNER for every case under data_root/cases/.

    Returns the count of cases migrated (i.e. cases whose owner was changed).
    """
    cases_root = data_root / "cases"
    if not cases_root.exists():
        print(f"no cases directory found at {cases_root}")
        return 0

    migrated = 0
    for case_file in sorted(cases_root.glob("*/case.json")):
        data = json.loads(case_file.read_text(encoding="utf-8"))
        current_owner = data.get("owner")
        if current_owner == DEFAULT_OWNER:
            # Already has the expected owner; nothing to do.
            continue
        data["owner"] = DEFAULT_OWNER
        if not dry_run:
            case_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        migrated += 1
        print(
            f"{'[dry-run] ' if dry_run else ''}migrated {case_file}: owner {current_owner!r} -> {DEFAULT_OWNER!r}"
        )

    return migrated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(DEFAULT_DATA_ROOT),
        help=f"Root directory containing cases/ (default: {DEFAULT_DATA_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without writing to disk",
    )
    args = parser.parse_args(argv)

    migrated = migrate_cases(args.data_root, dry_run=args.dry_run)
    print(f"migrated {migrated} case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
