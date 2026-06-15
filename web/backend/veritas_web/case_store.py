from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import AuditRunRecord, CaseRecord, utc_now


SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_id(value: str) -> str:
    cleaned = SAFE_NAME_RE.sub("-", value.strip()).strip(".-")
    return cleaned[:120] or uuid4().hex


class CaseStore:
    def __init__(self, root: str | Path = "web_data") -> None:
        self.root = Path(root)
        self.cases_root = self.root / "cases"
        self.cases_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers (no ownership check)
    # ------------------------------------------------------------------

    def _load_case(self, case_id: str) -> CaseRecord:
        """Load a case without ownership check (internal use)."""
        path = self.case_dir(case_id) / "case.json"
        if not path.exists():
            raise FileNotFoundError(f"case not found: {case_id}")
        return CaseRecord.from_dict(read_json(path))

    def _check_owner(self, record: CaseRecord, user_id: str | None) -> None:
        """Raise PermissionError if user_id is provided and does not match owner."""
        if user_id is not None and record.owner != user_id:
            raise PermissionError(f"user '{user_id}' is not the owner of case '{record.case_id}'")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_cases(self, user_id: str | None = None) -> list[CaseRecord]:
        """List cases visible to user_id.

        When user_id is provided only cases owned by that user are returned.
        When user_id is None (internal calls) all cases are returned.
        Future: support visibility == 'public' and shared_with.
        """
        records = []
        for path in sorted(self.cases_root.glob("*/case.json")):
            record = CaseRecord.from_dict(read_json(path))
            if user_id is None or record.owner == user_id:
                records.append(record)
        return records

    def get_case(self, case_id: str, user_id: str | None = None) -> CaseRecord:
        """Load a case. When user_id is provided, enforce ownership check."""
        record = self._load_case(case_id)
        self._check_owner(record, user_id)
        return record

    def create_case(
        self,
        case: CaseRecord | None = None,
        user_id: str = "operator",
        *,
        paper_title: str | None = None,
        case_id: str | None = None,
    ) -> CaseRecord:
        """Create a new case owned by user_id.

        Accepts either a fully-formed CaseRecord (preferred) or the legacy
        keyword arguments paper_title / case_id for convenience.
        """
        if case is None:
            case = CaseRecord(
                case_id=safe_id(case_id or f"case-{utc_now().replace(':', '').replace('-', '')}-{uuid4().hex[:8]}"),
                paper_title=paper_title or "Unknown until parsed",
            )
        case.owner = user_id
        case_dir = self.case_dir(case.case_id)
        if case_dir.exists():
            raise FileExistsError(f"case already exists: {case.case_id}")
        (case_dir / "inputs").mkdir(parents=True)
        (case_dir / "runs").mkdir(parents=True)
        self.save_case(case)
        return case

    def update_case(
        self,
        case_id: str,
        updates: dict[str, Any],
        user_id: str | None = None,
    ) -> CaseRecord:
        """Update a case. Only the owner may update."""
        record = self._load_case(case_id)
        self._check_owner(record, user_id)
        for key, value in updates.items():
            if key in {"case_id"}:
                continue  # case_id is immutable
            if hasattr(record, key):
                setattr(record, key, value)
        self.save_case(record)
        return record

    def delete_case(self, case_id: str, user_id: str | None = None) -> bool:
        """Delete a case and its directory. Only the owner may delete."""
        record = self._load_case(case_id)
        self._check_owner(record, user_id)
        case_dir = self.case_dir(case_id)
        if case_dir.exists():
            shutil.rmtree(case_dir)
            return True
        return False

    def save_case(self, record: CaseRecord) -> None:
        record.updated_at = utc_now()
        case_dir = self.case_dir(record.case_id)
        case_dir.mkdir(parents=True, exist_ok=True)
        write_json(case_dir / "case.json", record.to_dict())

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

    def write_input(self, case_id: str, filename: str, content: bytes) -> Path:
        case_record = self._load_case(case_id)
        target = self.inputs_dir(case_id) / safe_id(Path(filename).name)
        if not target.name:
            raise ValueError("input filename is required")
        target.write_bytes(content)
        case_record.input_count = len([path for path in self.inputs_dir(case_id).iterdir() if path.is_file()])
        if case_record.status == "Draft":
            case_record.status = "Uploaded"
        self.save_case(case_record)
        return target

    def write_input_base64(self, case_id: str, filename: str, content_base64: str) -> Path:
        return self.write_input(case_id, filename, base64.b64decode(content_base64))

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
        case_record = self._load_case(case_id)
        case_record.input_count = len(list(self.inputs_dir(case_id).iterdir()))
        if case_record.status == "Draft":
            case_record.status = "Uploaded"
        self.save_case(case_record)
        return target

    def create_run(self, case_id: str, agent_mode: str = "review") -> AuditRunRecord:
        self._load_case(case_id)
        run_id = f"run-{utc_now().replace(':', '').replace('-', '')}-{uuid4().hex[:8]}"
        record = AuditRunRecord(run_id=run_id, case_id=case_id, agent_mode=agent_mode)
        self.save_run(record)
        case_record = self._load_case(case_id)
        case_record.latest_run_id = run_id
        self.save_case(case_record)
        return record

    def get_run(self, case_id: str, run_id: str) -> AuditRunRecord:
        path = self.run_dir(case_id, run_id) / "run.json"
        if not path.exists():
            raise FileNotFoundError(f"run not found: {case_id}/{run_id}")
        return AuditRunRecord.from_dict(read_json(path))

    def list_runs(self, case_id: str) -> list[AuditRunRecord]:
        records = []
        for path in sorted((self.case_dir(case_id) / "runs").glob("*/run.json")):
            records.append(AuditRunRecord.from_dict(read_json(path)))
        return records

    def list_all_runs(self, user_id: str | None = None) -> list[AuditRunRecord]:
        records = []
        for case in self.list_cases(user_id=user_id):
            records.extend(self.list_runs(case.case_id))
        return records

    def save_run(self, record: AuditRunRecord) -> None:
        write_json(self.run_dir(record.case_id, record.run_id) / "run.json", record.to_dict())

    def append_event(self, case_id: str, run_id: str, event: dict[str, Any]) -> None:
        path = self.run_dir(case_id, run_id) / "events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def list_events(self, case_id: str, run_id: str) -> list[dict[str, Any]]:
        path = self.run_dir(case_id, run_id) / "events.jsonl"
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
