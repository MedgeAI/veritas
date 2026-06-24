"""Add async audit columns to the runs table.

Adds ``celery_task_id``, ``stages`` and ``current_stage`` columns, plus a
partial unique index that prevents a case from having more than one
active (queued / running) run at a time.

Idempotent: safe to run multiple times.

Usage::

    export DATABASE_URL=postgresql://user:pass@host/db
    python scripts/migrate_async_audit.py
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, inspect, text

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


COLUMNS = [
    ("celery_task_id", "VARCHAR(255)"),
    ("stages", "JSON"),
    ("current_stage", "VARCHAR(50)"),
]

INDEX_NAME = "idx_runs_active_case"
INDEX_DDL = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
    "ON runs (case_id) "
    "WHERE status IN ('queued', 'running')"
)


def migrate(database_url: str | None = None) -> None:
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required. "
            "Example: postgresql://user:pass@host/db"
        )

    engine = create_engine(url)
    insp = inspect(engine)
    existing_columns = {col["name"] for col in insp.get_columns("runs")}

    with engine.begin() as conn:
        for col_name, col_type in COLUMNS:
            if col_name in existing_columns:
                print(f"  Column {col_name!r} already exists, skipping.")
            else:
                conn.execute(
                    text(f"ALTER TABLE runs ADD COLUMN {col_name} {col_type}")
                )
                print(f"  Added column {col_name!r} ({col_type}).")

        conn.execute(text(INDEX_DDL))
        print(f"  Ensured partial unique index {INDEX_NAME!r}.")

    print("Migration complete.")


if __name__ == "__main__":
    migrate()
