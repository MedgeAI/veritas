from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .case_store import CaseStore
from .models import ArtifactRef


KNOWN_ARTIFACTS = (
    ("run_manifest", "json", "Audit Run Manifest", "audit_run_manifest.json"),
    ("static_audit_bundle", "json", "Static Audit Bundle", "static_audit_bundle.json"),
    ("investigation_rounds", "jsonl", "Investigation Rounds", "investigation_rounds.jsonl"),
    ("final_markdown_report", "markdown", "Final Markdown Report", "final_audit_report.md"),
    ("final_html_report", "html_report", "Final HTML Report", "final_audit_report.html"),
)


class ArtifactService:
    def __init__(self, store: CaseStore) -> None:
        self.store = store

    def list_artifacts(self, case_id: str) -> list[ArtifactRef]:
        workdir = self.latest_workdir(case_id)
        refs = []
        for artifact_id, kind, label, filename in KNOWN_ARTIFACTS:
            path = workdir / filename if workdir else Path(filename)
            size_bytes, updated_at = file_metadata(path) if workdir and path.exists() else (None, None)
            refs.append(
                ArtifactRef(
                    artifact_id=artifact_id,
                    kind=kind,
                    label=label,
                    path=str(path),
                    url=self.artifact_url(case_id, artifact_id),
                    exists=bool(workdir and path.exists()),
                    size_bytes=size_bytes,
                    updated_at=updated_at,
                )
            )
        return refs

    def artifact_path(self, case_id: str, artifact_id: str) -> Path | None:
        workdir = self.latest_workdir(case_id)
        if not workdir:
            return None
        for known_id, _kind, _label, filename in KNOWN_ARTIFACTS:
            if known_id == artifact_id:
                path = workdir / filename
                return path if path.exists() else None
        return None

    def report_html_path(self, case_id: str) -> Path | None:
        return self.artifact_path(case_id, "final_html_report")

    def latest_workdir(self, case_id: str) -> Path | None:
        case = self.store.get_case(case_id)
        if not case.latest_run_id:
            return None
        run = self.store.get_run(case_id, case.latest_run_id)
        if run.workdir:
            return Path(run.workdir)
        if run.summary and run.summary.get("workdir"):
            return Path(str(run.summary["workdir"]))
        return None

    @staticmethod
    def artifact_url(case_id: str, artifact_id: str) -> str:
        if artifact_id == "final_html_report":
            return f"/api/cases/{case_id}/report/html"
        return f"/api/cases/{case_id}/artifacts/{artifact_id}"


def file_metadata(path: Path) -> tuple[int, str]:
    stat = path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return stat.st_size, updated_at
