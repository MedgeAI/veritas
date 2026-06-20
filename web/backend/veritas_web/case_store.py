"""SQL-backed case store (PostgreSQL for production, SQLite for tests).

There is no JSON file fallback.  All case/run/event CRUD goes through
SQLAlchemy.  Directory creation and file I/O (input uploads) still
happen on disk alongside the DB — the filesystem stores large binary
blobs (PDFs, images), the database stores structured metadata.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import AuditRunRecord, CaseRecord, utc_now


def _safe_id(value: str) -> str:
    """Sanitise *value* for use as a filesystem-safe identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return cleaned[:120] or uuid4().hex


# Re-export for backward compat (other modules import safe_id from here)
safe_id = _safe_id


class CaseStore:
    """SQL-only case store.

    *database_url* defaults to ``VERITAS_DATABASE_URL`` env var, then to
    ``sqlite:///:memory:`` for test/dev convenience.  Production should
    always set ``VERITAS_DATABASE_URL`` to a PostgreSQL DSN.
    """

    def __init__(
        self,
        root: str | Path = "web_data",
        *,
        database_url: str | None = None,
    ) -> None:
        self.root = Path(root)
        self.cases_root = self.root / "cases"
        self.cases_root.mkdir(parents=True, exist_ok=True)

        self._db_url = database_url or os.environ.get("VERITAS_DATABASE_URL", "sqlite:///:memory:")
        self._init_sql(self._db_url)

    # ------------------------------------------------------------------
    # SQL initialisation
    # ------------------------------------------------------------------

    def _init_sql(self, database_url: str) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        kwargs: dict[str, Any] = {}
        if database_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in database_url or database_url == "sqlite://":
                from sqlalchemy.pool import StaticPool
                kwargs["poolclass"] = StaticPool
        else:
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 10
            kwargs["pool_pre_ping"] = True

        self._engine = create_engine(database_url, **kwargs)
        self._session_factory = sessionmaker(bind=self._engine, autoflush=False)

        from .database import Base
        Base.metadata.create_all(bind=self._engine)

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
            raise PermissionError(f"user '{user_id}' is not the owner of case '{record.case_id}'")

    def _to_case_record(self, model: Any) -> CaseRecord:
        return CaseRecord.from_model(model)

    def _to_run_record(self, model: Any) -> AuditRunRecord:
        return AuditRunRecord.from_model(model)

    # ------------------------------------------------------------------
    # Case CRUD
    # ------------------------------------------------------------------

    def list_cases(self, user_id: str | None = None) -> list[CaseRecord]:
        from .models import CaseModel
        session = self._session()
        try:
            query = session.query(CaseModel)
            if user_id is not None:
                query = query.filter(CaseModel.owner == user_id)
            return [self._to_case_record(m) for m in query.order_by(CaseModel.created_at).all()]
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
    ) -> CaseRecord:
        from .models import CaseModel
        if case is None:
            case = CaseRecord(
                case_id=safe_id(case_id or f"case-{utc_now().replace(':', '').replace('-', '')}-{uuid4().hex[:8]}"),
                paper_title=paper_title or "Unknown until parsed",
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
            EmbeddingIndexJobModel,
            ImageEmbeddingModel,
            InvestigationRecordModel,
            ReviewDecisionModel,
            RunEventModel,
            RunModel,
        )
        self.get_case(case_id, user_id=user_id)  # ownership check

        session = self._session()
        try:
            run_ids = [r.run_id for r in session.query(RunModel.run_id).filter(RunModel.case_id == case_id).all()]
            if run_ids:
                session.query(RunEventModel).filter(RunEventModel.run_id.in_(run_ids)).delete(synchronize_session=False)
            session.query(RunModel).filter(RunModel.case_id == case_id).delete(synchronize_session=False)
            session.query(InvestigationRecordModel).filter(InvestigationRecordModel.case_id == case_id).delete(synchronize_session=False)
            session.query(ReviewDecisionModel).filter(ReviewDecisionModel.case_id == case_id).delete(synchronize_session=False)
            session.query(ImageEmbeddingModel).filter(ImageEmbeddingModel.case_id == case_id).delete(synchronize_session=False)
            session.query(EmbeddingIndexJobModel).filter(EmbeddingIndexJobModel.case_id == case_id).delete(synchronize_session=False)
            session.query(CaseModel).filter(CaseModel.case_id == case_id).delete(synchronize_session=False)
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

    def write_input(self, case_id: str, filename: str, content: bytes, relative_path: str | None = None) -> Path:
        case_record = self.get_case(case_id)
        target = self.inputs_dir(case_id) / self._safe_input_relative_path(relative_path or filename, filename)
        if not target.name:
            raise ValueError("input filename is required")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        case_record.input_count = len([p for p in self.inputs_dir(case_id).rglob("*") if p.is_file()])
        if case_record.status == "Draft":
            case_record.status = "Uploaded"
        self._save_case(case_record)
        return target

    def write_input_base64(self, case_id: str, filename: str, content_base64: str) -> Path:
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
            models = session.query(RunModel).filter(RunModel.case_id == case_id).order_by(RunModel.created_at).all()
            return [self._to_run_record(m) for m in models]
        finally:
            session.close()

    def list_all_runs(self, user_id: str | None = None) -> list[AuditRunRecord]:
        from .models import CaseModel, RunModel
        session = self._session()
        try:
            query = session.query(RunModel)
            if user_id is not None:
                case_ids = [c.case_id for c in session.query(CaseModel.case_id).filter(CaseModel.owner == user_id).all()]
                query = query.filter(RunModel.case_id.in_(case_ids))
            return [self._to_run_record(m) for m in query.order_by(RunModel.created_at).all()]
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
            session.add(RunEventModel(
                run_id=run_id,
                event_type=event.get("event", "progress"),
                payload={k: v for k, v in event.items() if k != "event"},
            ))
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
