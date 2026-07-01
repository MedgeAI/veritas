"""SQL-backed case store for PostgreSQL-compatible Web state.

There is no JSON file fallback.  All case/run/event CRUD goes through
SQLAlchemy.  Directory creation and file I/O (input uploads) still
happen on disk alongside the DB — the filesystem stores large binary
blobs (PDFs, images), the database stores structured metadata.
"""

from __future__ import annotations

import base64
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, text

from .models import AuditRunRecord, CaseRecord, utc_now


def _safe_id(value: str) -> str:
    """Sanitise *value* for use as a filesystem-safe identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return cleaned[:120] or uuid4().hex


# Re-export for backward compat (other modules import safe_id from here)
safe_id = _safe_id


class CaseStore:
    """SQL-only case store.

    *database_url* defaults to ``VERITAS_DATABASE_URL``. Local development
    uses Docker PostgreSQL (``make db-up``). There is no implicit SQLite
    fallback for Web case/run state.
    """

    def __init__(
        self,
        root: str | Path = "web_data",
        *,
        database_url: str | None = None,
        engine: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.cases_root = self.root / "cases"
        self.cases_root.mkdir(parents=True, exist_ok=True)

        from .database import get_database_url

        self._db_url = database_url or get_database_url()
        self._init_sql(self._db_url, engine=engine)

    # ------------------------------------------------------------------
    # SQL initialisation
    # ------------------------------------------------------------------

    def _init_sql(self, database_url: str, *, engine: Any | None = None) -> None:
        from sqlalchemy.orm import sessionmaker

        from .database import create_db_engine

        if engine is not None:
            self._engine = engine
        else:
            self._engine = create_db_engine(database_url)
        self._session_factory = sessionmaker(bind=self._engine, autoflush=False)

        from .database import Base

        Base.metadata.create_all(bind=self._engine)

        # Ensure owner column is wide enough for email addresses (RFC 5321: up to 320).
        # This is a no-op on PostgreSQL when the column is already VARCHAR(320)+.
        try:
            with self._engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE cases ALTER COLUMN owner TYPE VARCHAR(320)")
                )
                conn.commit()
        except Exception:
            pass  # column already correct type - safe to ignore

    def _session(self):
        return self._session_factory()

    @property
    def sql_mode(self) -> bool:
        return True  # always SQL now

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_owner(self, record: CaseRecord, user_id: str | None) -> None:
        if user_id is not None and record.owner != user_id:
            raise PermissionError(
                f"user '{user_id}' is not the owner of case '{record.case_id}'"
            )

    def _to_case_record(self, model: Any) -> CaseRecord:
        return CaseRecord.from_model(model)

    def _to_run_record(self, model: Any) -> AuditRunRecord:
        return AuditRunRecord.from_model(model)

    # ------------------------------------------------------------------
    # Case CRUD
    # ------------------------------------------------------------------

    def list_cases(
        self,
        user_id: str | None = None,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[CaseRecord]:
        from .models import CaseModel

        session = self._session()
        try:
            query = session.query(CaseModel)
            if user_id is not None:
                query = query.filter(CaseModel.owner == user_id)
            query = query.order_by(CaseModel.created_at)
            if limit is not None:
                query = query.limit(limit)
            if offset is not None:
                query = query.offset(offset)
            return [
                self._to_case_record(m)
                for m in query.all()
            ]
        finally:
            session.close()

    def count_cases(self, user_id: str | None = None) -> int:
        """Return the number of cases, optionally filtered by owner."""
        from .models import CaseModel

        session = self._session()
        try:
            query = session.query(CaseModel)
            if user_id is not None:
                query = query.filter(CaseModel.owner == user_id)
            return query.count()
        finally:
            session.close()

    def list_cases_with_latest_run(
        self,
        user_id: str | None = None,
        *,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[tuple[Any, Any | None]]:
        """Return cases with their latest run loaded in one JOIN query.

        Eliminates the N+1 pattern where list_cases() is followed by a
        get_run() call for each case's latest_run_id.
        """
        from .models import CaseModel, RunModel

        session = self._session()
        try:
            query = (
                session.query(CaseModel, RunModel)
                .outerjoin(
                    RunModel,
                    (RunModel.case_id == CaseModel.case_id)
                    & (RunModel.run_id == CaseModel.latest_run_id),
                )
            )
            if user_id is not None:
                query = query.filter(CaseModel.owner == user_id)
            query = query.order_by(CaseModel.created_at)
            if limit is not None:
                query = query.limit(limit)
            if offset is not None:
                query = query.offset(offset)
            results = []
            for case_model, run_model in query.all():
                case_record = self._to_case_record(case_model)
                run_record = self._to_run_record(run_model) if run_model else None
                results.append((case_record, run_record))
            return results
        finally:
            session.close()

    def get_case(self, case_id: str, user_id: str | None = None) -> CaseRecord:
        from .models import CaseModel

        session = self._session()
        try:
            model = session.get(CaseModel, case_id)
            if model is None:
                raise FileNotFoundError(f"case not found: {case_id}")
            record = self._to_case_record(model)
            self._check_owner(record, user_id)
            return record
        finally:
            session.close()

    def create_case(
        self,
        case: CaseRecord | None = None,
        user_id: str = "operator",
        *,
        paper_title: str | None = None,
        case_id: str | None = None,
        reproducibility_tier: str = "full",
    ) -> CaseRecord:
        from .models import CaseModel

        if case is None:
            case = CaseRecord(
                case_id=safe_id(
                    case_id
                    or f"case-{utc_now().replace(':', '').replace('-', '')}-{uuid4().hex[:8]}"
                ),
                paper_title=paper_title or "Unknown until parsed",
                reproducibility_tier=reproducibility_tier,
            )
        case.owner = user_id

        # Directory structure for file storage (PDFs, source data)
        case_dir = self.case_dir(case.case_id)
        if case_dir.exists():
            raise FileExistsError(f"case already exists: {case.case_id}")
        (case_dir / "inputs").mkdir(parents=True)
        (case_dir / "runs").mkdir(parents=True)

        session = self._session()
        try:
            session.add(CaseModel(**case.to_dict()))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return case

    def update_case(
        self,
        case_id: str,
        updates: dict[str, Any],
        user_id: str | None = None,
    ) -> CaseRecord:
        record = self.get_case(case_id, user_id=user_id)
        for key, value in updates.items():
            if key in {"case_id"}:
                continue
            if hasattr(record, key):
                setattr(record, key, value)
        self._save_case(record)
        return record

    def delete_case(self, case_id: str, user_id: str | None = None) -> bool:
        from .models import (
            CaseModel,
            InvestigationRecordModel,
            ReviewDecisionModel,
            RunEventModel,
            RunModel,
        )

        self.get_case(case_id, user_id=user_id)  # ownership check

        session = self._session()
        try:
            run_ids = [
                r.run_id
                for r in session.query(RunModel.run_id)
                .filter(RunModel.case_id == case_id)
                .all()
            ]
            if run_ids:
                session.query(RunEventModel).filter(
                    RunEventModel.run_id.in_(run_ids)
                ).delete(synchronize_session=False)
            session.query(RunModel).filter(RunModel.case_id == case_id).delete(
                synchronize_session=False
            )
            session.query(InvestigationRecordModel).filter(
                InvestigationRecordModel.case_id == case_id
            ).delete(synchronize_session=False)
            session.query(ReviewDecisionModel).filter(
                ReviewDecisionModel.case_id == case_id
            ).delete(synchronize_session=False)
            session.query(CaseModel).filter(CaseModel.case_id == case_id).delete(
                synchronize_session=False
            )
            session.flush()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        case_dir = self.case_dir(case_id)
        if case_dir.exists():
            shutil.rmtree(case_dir)
        return True

    def save_case(self, record: CaseRecord) -> None:
        self._save_case(record)

    def _save_case(self, record: CaseRecord) -> None:
        from .models import CaseModel

        record.updated_at = utc_now()
        session = self._session()
        try:
            existing = session.get(CaseModel, record.case_id)
            if existing:
                for key, value in record.to_dict().items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
            else:
                session.add(CaseModel(**record.to_dict()))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Directory helpers (filesystem for binary/large files)
    # ------------------------------------------------------------------

    def case_dir(self, case_id: str) -> Path:
        return self.cases_root / safe_id(case_id)

    def inputs_dir(self, case_id: str) -> Path:
        path = self.case_dir(case_id) / "inputs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def runs_dir(self, case_id: str) -> Path:
        path = self.case_dir(case_id) / "runs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def run_dir(self, case_id: str, run_id: str) -> Path:
        path = self.runs_dir(case_id) / safe_id(run_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Input file operations (binary files on disk, metadata in DB)
    # ------------------------------------------------------------------

    def write_input(
        self,
        case_id: str,
        filename: str,
        content: bytes,
        relative_path: str | None = None,
    ) -> Path:
        target = self.prepare_input_target(case_id, filename, relative_path)
        target.write_bytes(content)
        self.record_input_uploaded(case_id)
        return target

    def prepare_input_target(
        self,
        case_id: str,
        filename: str,
        relative_path: str | None = None,
    ) -> Path:
        """Return the safe on-disk target path for an uploaded input file."""
        self.get_case(case_id)
        target = self.inputs_dir(case_id) / self._safe_input_relative_path(
            relative_path or filename, filename
        )
        if not target.name:
            raise ValueError("input filename is required")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def record_input_uploaded(self, case_id: str) -> None:
        """Update case metadata after an input file has been written."""
        case_record = self.get_case(case_id)
        case_record.input_count = (case_record.input_count or 0) + 1
        if case_record.status == "Draft":
            case_record.status = "Uploaded"
        self._save_case(case_record)

    def write_input_base64(
        self, case_id: str, filename: str, content_base64: str
    ) -> Path:
        return self.write_input(case_id, filename, base64.b64decode(content_base64))

    @staticmethod
    def _safe_input_relative_path(value: str, fallback_filename: str) -> Path:
        raw_path = Path(value)
        if raw_path.is_absolute() or any(part == ".." for part in raw_path.parts):
            raw_path = Path(fallback_filename)
        parts = [safe_id(part) for part in raw_path.parts if part not in {"", "."}]
        parts = [part for part in parts if part]
        if not parts:
            parts = [safe_id(Path(fallback_filename).name)]
        return Path(*parts)

    def copy_input_path(self, case_id: str, source_path: str | Path) -> Path:
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"input source path not found: {source}")
        target = self.inputs_dir(case_id) / safe_id(source.name)
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        case_record = self.get_case(case_id)
        case_record.input_count = len(list(self.inputs_dir(case_id).iterdir()))
        if case_record.status == "Draft":
            case_record.status = "Uploaded"
        self._save_case(case_record)
        return target

    # ------------------------------------------------------------------
    # Run CRUD
    # ------------------------------------------------------------------

    def create_run(self, case_id: str, agent_mode: str = "review") -> AuditRunRecord:
        from .models import CaseModel, RunModel

        self.get_case(case_id)  # ensures case exists
        run_id = f"run-{utc_now().replace(':', '').replace('-', '')}-{uuid4().hex[:8]}"
        record = AuditRunRecord(run_id=run_id, case_id=case_id, agent_mode=agent_mode)

        session = self._session()
        try:
            session.add(RunModel(**record.to_dict()))
            case_model = session.get(CaseModel, case_id)
            if case_model:
                case_model.latest_run_id = run_id
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        return record

    def try_start_run(
        self, case_id: str, agent_mode: str, max_concurrent: int
    ) -> AuditRunRecord:
        """Create a run only if active run count is below max_concurrent.

        Uses a PostgreSQL advisory lock (key=0xAUD17) held for the
        duration of the check+insert transaction to prevent concurrent
        over-subscription (TOCTOU race).

        Raises:
            RuntimeError: if active run count is already at the limit.
        """
        from .models import CaseModel, RunModel

        session = self._session()
        try:
            # Acquire session-level advisory lock - held until commit/rollback.
            # Key 10493207 (0xA01D17) is a mnemonic for "AUDIT" lock.
            session.execute(text("SELECT pg_advisory_xact_lock(10493207)"))
            active_count = (
                session.query(RunModel)
                .filter(RunModel.status == "running")
                .count()
            )
            if active_count >= max_concurrent:
                raise RuntimeError(
                    f"Too many concurrent audits (active={active_count}, max={max_concurrent})"
                )
            run_id = f"run-{utc_now().replace(':', '').replace('-', '')}-{uuid4().hex[:8]}"
            record = AuditRunRecord(run_id=run_id, case_id=case_id, agent_mode=agent_mode)
            session.add(RunModel(**record.to_dict()))
            case_model = session.get(CaseModel, case_id)
            if case_model:
                case_model.latest_run_id = run_id
            session.commit()
            return record
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_run(self, case_id: str, run_id: str) -> AuditRunRecord:
        from .models import RunModel

        session = self._session()
        try:
            model = session.get(RunModel, run_id)
            if model is None or model.case_id != case_id:
                raise FileNotFoundError(f"run not found: {case_id}/{run_id}")
            return self._to_run_record(model)
        finally:
            session.close()

    def list_runs(self, case_id: str) -> list[AuditRunRecord]:
        from .models import RunModel

        session = self._session()
        try:
            models = (
                session.query(RunModel)
                .filter(RunModel.case_id == case_id)
                .order_by(RunModel.created_at)
                .all()
            )
            return [self._to_run_record(m) for m in models]
        finally:
            session.close()

    def list_all_runs(self, user_id: str | None = None) -> list[AuditRunRecord]:
        from .models import CaseModel, RunModel

        session = self._session()
        try:
            query = session.query(RunModel)
            if user_id is not None:
                case_ids = [
                    c.case_id
                    for c in session.query(CaseModel.case_id)
                    .filter(CaseModel.owner == user_id)
                    .all()
                ]
                query = query.filter(RunModel.case_id.in_(case_ids))
            return [
                self._to_run_record(m)
                for m in query.order_by(RunModel.created_at).all()
            ]
        finally:
            session.close()

    def save_run(self, record: AuditRunRecord) -> None:
        from .models import RunModel

        session = self._session()
        try:
            existing = session.get(RunModel, record.run_id)
            if existing:
                for key, value in record.to_dict().items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
            else:
                session.add(RunModel(**record.to_dict()))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Event operations
    # ------------------------------------------------------------------

    def append_event(self, case_id: str, run_id: str, event: dict[str, Any]) -> None:
        from .models import RunEventModel

        session = self._session()
        try:
            session.add(
                RunEventModel(
                    run_id=run_id,
                    event_type=event.get("event", "progress"),
                    payload={k: v for k, v in event.items() if k != "event"},
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_events(self, case_id: str, run_id: str) -> list[dict[str, Any]]:
        from .models import RunEventModel, RunModel

        session = self._session()
        try:
            run = session.get(RunModel, run_id)
            if run is None or run.case_id != case_id:
                raise FileNotFoundError(f"run not found: {case_id}/{run_id}")
            models = (
                session.query(RunEventModel)
                .filter(RunEventModel.run_id == run_id)
                .order_by(RunEventModel.id)
                .all()
            )
            return [m.to_dict() for m in models]
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Async audit job helpers
    # ------------------------------------------------------------------

    def get_active_runs_by_case(self, case_id: str) -> list[AuditRunRecord]:
        """Return runs in ``queued`` or ``running`` status for *case_id*."""
        from .models import RunModel

        session = self._session()
        try:
            models = (
                session.query(RunModel)
                .filter(
                    RunModel.case_id == case_id,
                    RunModel.status.in_(["queued", "running"]),
                )
                .all()
            )
            return [self._to_run_record(m) for m in models]
        finally:
            session.close()

    def count_active_runs(self) -> int:
        """Count all runs across all cases with status ``queued`` or ``running``."""
        from .models import RunModel

        session = self._session()
        try:
            return (
                session.query(RunModel)
                .filter(RunModel.status.in_(["queued", "running"]))
                .count()
            )
        finally:
            session.close()

    def count_running_runs(self) -> int:
        """Count all runs across all cases with status ``running``."""
        from .models import RunModel

        session = self._session()
        try:
            return (
                session.query(RunModel)
                .filter(RunModel.status == "running")
                .count()
            )
        finally:
            session.close()

    def count_queued_runs(self) -> int:
        """Count all runs across all cases with status ``queued``."""
        from .models import RunModel

        session = self._session()
        try:
            return (
                session.query(RunModel)
                .filter(RunModel.status == "queued")
                .count()
            )
        finally:
            session.close()

    def metrics_summary(self) -> dict[str, Any]:
        """Return aggregate case/run metrics without materializing all rows."""
        from .models import CaseModel, RunModel

        session = self._session()
        try:
            case_status_rows = (
                session.query(CaseModel.status, func.count(CaseModel.case_id))
                .group_by(CaseModel.status)
                .all()
            )
            run_status_rows = (
                session.query(RunModel.status, func.count(RunModel.run_id))
                .group_by(RunModel.status)
                .all()
            )
            cases_by_status = {
                str(status or ""): int(count) for status, count in case_status_rows
            }
            runs_by_status = {
                str(status or ""): int(count) for status, count in run_status_rows
            }
            return {
                "cases_total": sum(cases_by_status.values()),
                "cases_by_status": cases_by_status,
                "runs_total": sum(runs_by_status.values()),
                "runs_active": runs_by_status.get("running", 0),
                "runs_completed": runs_by_status.get("completed", 0),
                "runs_failed": runs_by_status.get("failed", 0),
                "runs_interrupted": runs_by_status.get("interrupted", 0),
            }
        finally:
            session.close()

    def update_run_stage(
        self,
        run_id: str,
        stage: str,
        progress: float | None = None,
    ) -> None:
        """Update ``current_stage`` and optionally ``stages`` progress on a run.

        *stage* is the ID of the currently executing stage (e.g. ``pdf_parse``).
        *progress* (0.0–1.0) is written into the matching entry of the
        ``stages`` JSON array if present.
        """
        from .models import RunModel

        session = self._session()
        try:
            run = session.get(RunModel, run_id)
            if run is None:
                raise FileNotFoundError(f"run not found: {run_id}")
            run.current_stage = stage
            if progress is not None and isinstance(run.stages, list):
                for s in run.stages:
                    if isinstance(s, dict) and s.get("id") == stage:
                        s["progress"] = progress
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def set_run_celery_task_id(self, run_id: str, celery_task_id: str) -> None:
        """Persist the Celery task ID on the run row (bypasses AuditRunRecord)."""
        from .models import RunModel

        session = self._session()
        try:
            run = session.get(RunModel, run_id)
            if run is None:
                raise FileNotFoundError(f"run not found: {run_id}")
            run.celery_task_id = celery_task_id
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_run_celery_task_id(self, run_id: str) -> str | None:
        """Return the ``celery_task_id`` stored on the run row, or ``None``."""
        from .models import RunModel

        session = self._session()
        try:
            run = session.get(RunModel, run_id)
            if run is None:
                return None
            return run.celery_task_id  # type: ignore[assignment,operator]
        finally:
            session.close()
