"""Migrate web_data/ JSON files to PostgreSQL.

Usage::

    make db-migrate
    # or directly:
    python scripts/migrate_web_data_to_postgres.py

Reads the legacy ``web_data/cases/*/`` JSON layout and inserts all
cases, runs, events, and users into the PostgreSQL database.
Also imports ``investigation_rounds.jsonl`` from ``outputs/``.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def migrate_cases(web_data_root: Path, session: Any) -> int:
    """Migrate cases, runs, and events from JSON files to DB."""
    from web.backend.veritas_web.models import CaseModel, RunEventModel, RunModel

    cases_root = web_data_root / "cases"
    if not cases_root.exists():
        print(f"  No cases directory found at {cases_root}")
        return 0

    count = 0
    for case_dir in sorted(cases_root.iterdir()):
        if not case_dir.is_dir():
            continue
        case_json = read_json(case_dir / "case.json")
        if not case_json:
            continue

        # Insert or update case
        existing = session.get(CaseModel, case_json["case_id"])
        if existing:
            for key, value in case_json.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
        else:
            session.add(CaseModel(**case_json))
        count += 1

        # Migrate runs
        runs_dir = case_dir / "runs"
        if not runs_dir.exists():
            continue
        for run_dir in sorted(runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            run_json = read_json(run_dir / "run.json")
            if not run_json:
                continue

            existing_run = session.get(RunModel, run_json["run_id"])
            if existing_run:
                for key, value in run_json.items():
                    if hasattr(existing_run, key):
                        setattr(existing_run, key, value)
            else:
                session.add(RunModel(**run_json))

            # Migrate events
            events_path = run_dir / "events.jsonl"
            for event in read_jsonl(events_path):
                session.add(
                    RunEventModel(
                        run_id=run_json["run_id"],
                        event_type=event.get("event", "progress"),
                        payload={k: v for k, v in event.items() if k != "event"},
                    )
                )

    session.commit()
    return count


def migrate_investigation_records(outputs_root: Path, session: Any) -> int:
    """Migrate investigation_rounds.jsonl from outputs/ to DB."""
    from web.backend.veritas_web.models import CaseModel, InvestigationRecordModel

    if not outputs_root.exists():
        return 0

    count = 0
    for case_dir in sorted(outputs_root.iterdir()):
        if not case_dir.is_dir():
            continue
        case_id = case_dir.name

        # Check case exists in DB
        if not session.get(CaseModel, case_id):
            continue

        rounds_path = (
            case_dir
            / "research-integrity-audit"
            / "investigation"
            / "investigation_rounds.jsonl"
        )
        if not rounds_path.exists():
            # Try legacy flat path
            rounds_path = (
                case_dir / "research-integrity-audit" / "investigation_rounds.jsonl"
            )
        if not rounds_path.exists():
            continue

        for record in read_jsonl(rounds_path):
            session.add(
                InvestigationRecordModel(
                    case_id=case_id,
                    round_id=record.get("round_id"),
                    action_id=record.get("action_id"),
                    tool_id=record.get("tool_id", ""),
                    status=record.get("status", "completed"),
                    validation_status=record.get("validation_status", "not_validated"),
                    hypothesis=record.get("hypothesis", ""),
                    expected_evidence_type=record.get("expected_evidence_type", ""),
                    params=record.get("params", {}),
                    depends_on_artifacts=record.get("depends_on_artifacts", []),
                    output_artifacts=record.get("output_artifacts", []),
                    detail=record.get("detail", ""),
                    metadata_=record.get("metadata", {}),
                )
            )
            count += 1

    session.commit()
    return count


def migrate_users(users_db_path: Path, session: Any) -> int:
    """Migrate users from SQLite to PostgreSQL."""
    from web.backend.veritas_web.models import UserModel

    if not users_db_path.exists():
        return 0

    conn = sqlite3.connect(str(users_db_path))
    conn.row_factory = sqlite3.Row
    count = 0
    try:
        for row in conn.execute(
            "SELECT username, password_hash, email, roles, created_at FROM users"
        ):
            existing = session.get(UserModel, row["username"])
            if existing:
                existing.password_hash = row["password_hash"]
                existing.email = row["email"] or ""
                existing.roles = row["roles"] or "operator"
            else:
                session.add(
                    UserModel(
                        username=row["username"],
                        password_hash=row["password_hash"],
                        email=row["email"] or "",
                        roles=row["roles"] or "operator",
                        created_at=row["created_at"] or "",
                    )
                )
            count += 1
        session.commit()
    finally:
        conn.close()
    return count


def main() -> int:
    from web.backend.veritas_web.database import (
        create_db_engine,
        create_session_factory,
        check_connection,
    )

    engine = create_db_engine()
    if not check_connection(engine):
        print(
            "ERROR: cannot connect to PostgreSQL. Run `make db-up` first.",
            file=sys.stderr,
        )
        return 1

    factory = create_session_factory(engine)
    session = factory()

    web_data_root = Path("web_data")
    outputs_root = Path("outputs")
    users_db = Path("web_data/users.db")

    try:
        print("Migrating cases, runs, and events...")
        case_count = migrate_cases(web_data_root, session)
        print(f"  {case_count} cases migrated")

        print("Migrating investigation records...")
        inv_count = migrate_investigation_records(outputs_root, session)
        print(f"  {inv_count} investigation records migrated")

        print("Migrating users...")
        user_count = migrate_users(users_db, session)
        print(f"  {user_count} users migrated")

        print("\nMigration complete.")
        return 0
    except Exception as exc:
        session.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
