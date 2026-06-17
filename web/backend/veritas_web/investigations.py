from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from engine.static_audit.investigation import (
    InvestigationRecord,
    append_investigation_record,
    read_investigation_records,
)
from engine.static_audit.models import utc_now_iso
from engine.static_audit.paths import resolve_artifact_path
from engine.static_audit.tools.sila_dense import detect_sila_dense
from engine.tools.registry import TOOL_ID_SILA_DENSE, TOOLS, coerce_tool_params

from .artifacts import ArtifactService
from .case_store import CaseStore

logger = logging.getLogger(__name__)


class WebInvestigationService:
    """Run explicit Web-triggered visual investigations within Tool Registry bounds."""

    def __init__(self, store: CaseStore, artifacts: ArtifactService) -> None:
        self.store = store
        self.artifacts = artifacts

    def list_investigations(self, case_id: str) -> dict[str, Any]:
        workdir = self._require_workdir(case_id)

        # Read records from DB (primary) with JSONL fallback for CLI-written records
        records = self._read_records(case_id, workdir)

        results = []
        artifact_errors = []
        for record in records:
            for artifact in record.get("output_artifacts") or []:
                artifact_path = self._resolve_record_artifact(workdir, str(artifact))
                if not artifact_path:
                    error = {
                        "artifact": str(artifact),
                        "error": "artifact_missing",
                        "detail": f"artifact file missing: {artifact}",
                    }
                    record.setdefault("artifact_errors", []).append(error)
                    artifact_errors.append({"action_id": record.get("action_id"), **error})
                    continue
                try:
                    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                except OSError as exc:
                    error = {
                        "artifact": str(artifact),
                        "error": "artifact_unreadable",
                        "detail": str(exc),
                    }
                    record.setdefault("artifact_errors", []).append(error)
                    artifact_errors.append({"action_id": record.get("action_id"), **error})
                    continue
                except json.JSONDecodeError as exc:
                    error = {
                        "artifact": str(artifact),
                        "error": "artifact_invalid_json",
                        "detail": str(exc),
                    }
                    record.setdefault("artifact_errors", []).append(error)
                    artifact_errors.append({"action_id": record.get("action_id"), **error})
                    continue
                results.append(
                    {
                        "record": record,
                        "artifact": str(artifact_path.relative_to(workdir)),
                        "result": payload,
                    }
                )
        return {"records": records, "results": results, "artifact_errors": artifact_errors}

    def _read_records(self, case_id: str, workdir: Path) -> list[dict[str, Any]]:
        """Read investigation records from DB, merged with JSONL."""
        from .models import InvestigationRecordModel

        db_records: list[dict[str, Any]] = []
        if getattr(self.store, "_session_factory", None):
            session = self.store._session()
            try:
                models = (
                    session.query(InvestigationRecordModel)
                    .filter(InvestigationRecordModel.case_id == case_id)
                    .order_by(InvestigationRecordModel.id)
                    .all()
                )
                db_records = [m.to_dict() for m in models]
            finally:
                session.close()

        # Also read JSONL for backward compat with CLI orchestrator
        jsonl_records = read_investigation_records(workdir)

        # Merge: deduplicate by action_id (DB takes precedence)
        seen_actions: set[str] = set()
        merged: list[dict[str, Any]] = []
        for r in db_records:
            action_key = r.get("action_id") or r.get("tool_id", "")
            if action_key not in seen_actions:
                seen_actions.add(action_key)
                merged.append(r)
        for r in jsonl_records:
            action_key = r.get("action_id") or r.get("tool_id", "")
            if action_key not in seen_actions:
                seen_actions.add(action_key)
                merged.append(r)
        return merged

    def run_investigation(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        workdir = self._require_workdir(case_id)
        tool_id = str(payload.get("tool_id") or TOOL_ID_SILA_DENSE)
        self._validate_tool(tool_id)
        params = coerce_tool_params(tool_id, payload.get("params") if isinstance(payload.get("params"), dict) else {})
        selected_panel_ids = self._selected_panel_ids(payload)
        max_panels = int(params.get("max_panels", 20))
        if len(selected_panel_ids) > max_panels:
            selected_panel_ids = selected_panel_ids[:max_panels]

        panel_doc = self._read_required_json(workdir, "panel_evidence.json")
        visual_doc = self._read_optional_json(workdir, "visual_evidence.json")
        panels = self._select_panels(panel_doc.get("panels") or [], selected_panel_ids)
        action_id = self._safe_action_id(payload.get("action_id"))
        action_dir = resolve_artifact_path(workdir, "investigation") / "web" / action_id
        action_dir.mkdir(parents=True, exist_ok=True)

        result = detect_sila_dense(
            panels,
            visual_doc.get("figures") or [],
            workdir=workdir,
            output_base=action_dir / "sila_dense",
            min_score=float(params["min_score"]),
            max_relationships=int(params["max_relationships"]),
        )
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        result["metadata"] = {
            **metadata,
            "trigger": "web_manual",
            "selected_panel_ids": [str(panel.get("panel_id")) for panel in panels],
            "requested_panel_ids": selected_panel_ids,
            "max_panels": max_panels,
        }
        output_path = action_dir / "copy_move_dense.json"
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        relative_output = str(output_path.relative_to(workdir))
        record = InvestigationRecord(
            round_id=self._next_round_id(workdir),
            action_id=action_id,
            tool_id=tool_id,
            status=str(result.get("status") or "failed"),
            validation_status="validated",
            hypothesis=str(payload.get("hypothesis") or "Web-selected SILA dense copy-move review.")[:1000],
            expected_evidence_type="image_similarity",
            params=params,
            depends_on_artifacts=["visual/panel_evidence.json", "visual/evidence.json"],
            output_artifacts=[relative_output],
            detail=self._result_detail(result, len(panels)),
            metadata={
                "trigger": "web_manual",
                "selected_panel_count": len(panels),
                "failure_category": result.get("failure_category"),
            },
        )
        append_investigation_record(workdir, record)

        # Also write to DB for SQL-backed reads
        db_sync_error = None
        try:
            self._save_record_to_db(case_id, record)
        except RuntimeError as exc:
            db_sync_error = str(exc)

        return {
            "record": record.to_dict(),
            "artifact": relative_output,
            "result": result,
            "db_sync_error": db_sync_error,
        }

    def _save_record_to_db(self, case_id: str, record: InvestigationRecord) -> None:
        """Write an InvestigationRecord to the DB table."""
        if not getattr(self.store, "_session_factory", None):
            return
        from .models import InvestigationRecordModel
        session = self.store._session()
        try:
            d = record.to_dict()
            session.add(InvestigationRecordModel(
                case_id=case_id,
                round_id=d.get("round_id"),
                action_id=d.get("action_id"),
                tool_id=d["tool_id"],
                status=d.get("status"),
                validation_status=d.get("validation_status", "not_validated"),
                hypothesis=d.get("hypothesis", ""),
                expected_evidence_type=d.get("expected_evidence_type", ""),
                params=d.get("params", {}),
                depends_on_artifacts=d.get("depends_on_artifacts", []),
                output_artifacts=d.get("output_artifacts", []),
                detail=d.get("detail", ""),
                metadata_=d.get("metadata", {}),
            ))
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.exception("failed to persist investigation record for case %s action %s", case_id, record.action_id)
            raise RuntimeError(f"failed to persist investigation record: {exc}") from exc
        finally:
            session.close()

    def _require_workdir(self, case_id: str) -> Path:
        workdir = self.artifacts.latest_workdir(case_id)
        if not workdir:
            raise FileNotFoundError("case has no completed audit workdir")
        return workdir

    @staticmethod
    def _validate_tool(tool_id: str) -> None:
        tool = TOOLS.get(tool_id)
        if not tool or not tool.agent_selectable or not tool.deterministic:
            raise ValueError(f"unsupported investigation tool_id: {tool_id}")
        if tool_id != TOOL_ID_SILA_DENSE:
            raise ValueError(f"web visual investigations currently support only {TOOL_ID_SILA_DENSE}")

    @staticmethod
    def _selected_panel_ids(payload: dict[str, Any]) -> list[str]:
        raw_ids = payload.get("panel_ids") or payload.get("target_panel_ids") or []
        if not isinstance(raw_ids, list):
            raise ValueError("panel_ids must be a list")
        panel_ids: list[str] = []
        seen: set[str] = set()
        for raw_id in raw_ids:
            panel_id = str(raw_id).strip()
            if not panel_id or panel_id in seen:
                continue
            seen.add(panel_id)
            panel_ids.append(panel_id)
        if not panel_ids:
            raise ValueError("at least one panel_id is required")
        return panel_ids

    @staticmethod
    def _select_panels(panels: list[Any], panel_ids: list[str]) -> list[dict[str, Any]]:
        by_id = {
            str(panel.get("panel_id")): panel
            for panel in panels
            if isinstance(panel, dict) and panel.get("panel_id")
        }
        missing = [panel_id for panel_id in panel_ids if panel_id not in by_id]
        if missing:
            raise ValueError(f"unknown panel_id(s): {', '.join(missing[:5])}")
        return [by_id[panel_id] for panel_id in panel_ids]

    @staticmethod
    def _safe_action_id(value: Any) -> str:
        raw = str(value or f"web-copy-move-dense-{utc_now_iso()}-{uuid4().hex[:8]}")
        cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in raw).strip("-")
        return cleaned[:120] or f"web-copy-move-dense-{uuid4().hex[:8]}"

    @staticmethod
    def _next_round_id(workdir: Path) -> int:
        records = read_investigation_records(workdir)
        round_ids = [int(record.get("round_id") or 0) for record in records if isinstance(record, dict)]
        return max(round_ids, default=0) + 1

    @staticmethod
    def _result_detail(result: dict[str, Any], panel_count: int) -> str:
        status = result.get("status") or "failed"
        relationships = result.get("relationship_count", 0)
        detail = f"status={status} panels={panel_count} relationships={relationships}"
        if result.get("failure_category"):
            detail += f" failure_category={result['failure_category']}"
        return detail

    @staticmethod
    def _read_required_json(workdir: Path, artifact_name: str) -> dict[str, Any]:
        path = _artifact_path_with_legacy_fallback(workdir, artifact_name)
        if not path:
            raise FileNotFoundError(f"required artifact missing: {artifact_name}")
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _read_optional_json(workdir: Path, artifact_name: str) -> dict[str, Any]:
        path = _artifact_path_with_legacy_fallback(workdir, artifact_name)
        if not path:
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _resolve_record_artifact(workdir: Path, relative_path: str) -> Path | None:
        candidate = (workdir / relative_path).resolve()
        workdir_resolved = workdir.resolve()
        if candidate != workdir_resolved and workdir_resolved not in candidate.parents:
            return None
        return candidate if candidate.exists() and candidate.is_file() else None


def _artifact_path_with_legacy_fallback(workdir: Path, artifact_name: str) -> Path | None:
    mapped = resolve_artifact_path(workdir, artifact_name)
    if mapped.exists():
        return mapped
    legacy = workdir / artifact_name
    if legacy.exists():
        return legacy
    return None
