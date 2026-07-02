"""PostgreSQL schema contract tests for the web database."""

from __future__ import annotations

from sqlalchemy import text

from web.backend.veritas_web.case_store import CaseStore
from web.backend.veritas_web.database import create_db_engine, get_database_url
from web.backend.veritas_web.models import (
    ArtifactModel,
    FindingModel,
    RunDiagnosticsSummaryModel,
)


def _scalar_set(query: str) -> set[str]:
    engine = create_db_engine(get_database_url())
    try:
        with engine.connect() as conn:
            return {str(row[0]) for row in conn.execute(text(query)).fetchall()}
    finally:
        engine.dispose()


def test_schema_has_agent_friendly_metadata_tables() -> None:
    tables = _scalar_set(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )

    assert {
        "artifacts",
        "findings",
        "run_diagnostics_summary",
    }.issubset(tables)


def test_schema_uses_postgres_native_jsonb_and_timestamptz() -> None:
    engine = create_db_engine(get_database_url())
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT table_name, column_name, data_type, udt_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND (
                        (table_name, column_name) IN (
                          ('runs', 'created_at'),
                          ('runs', 'summary'),
                          ('run_events', 'payload'),
                          ('artifacts', 'metadata'),
                          ('findings', 'metadata'),
                          ('run_diagnostics_summary', 'summary')
                        )
                      )
                    """
                )
            ).fetchall()
    finally:
        engine.dispose()

    observed = {
        (row.table_name, row.column_name): (row.data_type, row.udt_name)
        for row in rows
    }
    assert observed[("runs", "created_at")] == (
        "timestamp with time zone",
        "timestamptz",
    )
    assert observed[("runs", "summary")][1] == "jsonb"
    assert observed[("run_events", "payload")][1] == "jsonb"
    assert observed[("artifacts", "metadata")][1] == "jsonb"
    assert observed[("findings", "metadata")][1] == "jsonb"
    assert observed[("run_diagnostics_summary", "summary")][1] == "jsonb"


def test_schema_has_core_indexes_and_constraints() -> None:
    indexes = _scalar_set(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
    )
    constraints = _scalar_set(
        """
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
        """
    )

    assert {
        "ix_cases_owner_created_at",
        "ix_runs_case_created_at",
        "ix_runs_case_status",
        "ix_run_events_run_id_id",
        "ix_run_events_run_event_id",
        "ix_review_decisions_case_status",
        "ix_findings_case_status",
        "ix_artifacts_run_type",
    }.issubset(indexes)
    assert {
        "ck_cases_status",
        "ck_cases_technical_risk",
        "ck_runs_status",
        "ck_review_decisions_status",
        "ck_findings_risk_level",
        "fk_cases_latest_run_id",
    }.issubset(constraints)


def test_case_delete_cascades_database_metadata(tmp_path) -> None:
    store = CaseStore(root=tmp_path / "web_data")
    case = store.create_case(case_id="schema-case", paper_title="Schema")
    run = store.create_run(case.case_id)
    store.append_event(case.case_id, run.run_id, {"event": "progress", "value": 1})

    session = store._session()
    try:
        session.add(
            ArtifactModel(
                case_id=case.case_id,
                run_id=run.run_id,
                artifact_type="run_diagnostics",
                path="diagnostics/latest.json",
                size_bytes=12,
            )
        )
        session.add(
            FindingModel(
                case_id=case.case_id,
                run_id=run.run_id,
                finding_id="F-001",
                category="source_data",
                risk_level="high",
            )
        )
        session.add(
            RunDiagnosticsSummaryModel(
                run_id=run.run_id,
                status="completed_with_warnings",
                quality_flags_count=2,
                latest_path="diagnostics/latest.json",
            )
        )
        session.commit()
    finally:
        session.close()

    assert store.delete_case(case.case_id)

    engine = create_db_engine(get_database_url())
    try:
        with engine.connect() as conn:
            counts = {
                table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in (
                    "cases",
                    "runs",
                    "run_events",
                    "artifacts",
                    "findings",
                    "run_diagnostics_summary",
                )
            }
    finally:
        engine.dispose()

    assert counts == {
        "cases": 0,
        "runs": 0,
        "run_events": 0,
        "artifacts": 0,
        "findings": 0,
        "run_diagnostics_summary": 0,
    }
