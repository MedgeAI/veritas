from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from engine.static_audit.paths import existing_artifact_path

from .case_store import CaseStore
from .models import ArtifactRef
from .path_mapping import normalize_workdir_path


KNOWN_ARTIFACTS = (
    ("run_manifest", "json", "Audit Run Manifest", "audit_run_manifest.json"),
    ("static_audit_bundle", "json", "Static Audit Bundle", "static_audit_bundle.json"),
    (
        "investigation_rounds",
        "jsonl",
        "Investigation Rounds",
        "investigation_rounds.jsonl",
    ),
    (
        "final_markdown_report",
        "markdown",
        "Final Markdown Report",
        "final_audit_report.md",
    ),
    (
        "final_html_report",
        "html_report",
        "Final HTML Report",
        "final_audit_report.html",
    ),
    ("visual_evidence", "json", "Visual Evidence (Figures)", "visual_evidence.json"),
    ("panel_evidence", "json", "Panel Evidence", "panel_evidence.json"),
    ("image_relationships", "json", "Image Relationships", "image_relationships.json"),
    ("visual_findings", "json", "Visual Findings", "visual_findings.json"),
    (
        "visual_copy_move_dense",
        "json",
        "SILA Dense Copy-Move",
        "visual_copy_move_dense.json",
    ),
    ("visual_overlap_reuse", "json", "Visual Overlap/Reuse", "overlap_reuse.json"),
    ("provenance_graph", "json", "Provenance Graph (MST)", "provenance_graph.json"),
)


class ArtifactService:
    def __init__(
        self, store: CaseStore, *, output_root: str | Path | None = None
    ) -> None:
        self.store = store
        self.output_root = output_root

    def list_artifacts(self, case_id: str) -> list[ArtifactRef]:
        workdir = self.latest_workdir(case_id)
        refs = []
        for artifact_id, kind, label, filename in KNOWN_ARTIFACTS:
            path = artifact_file_path(workdir, filename) if workdir else Path(filename)
            size_bytes, updated_at = (
                file_metadata(path) if path and path.exists() else (None, None)
            )
            refs.append(
                ArtifactRef(
                    artifact_id=artifact_id,
                    kind=kind,
                    label=label,
                    path=str(path or Path(filename)),
                    url=self.artifact_url(case_id, artifact_id),
                    exists=bool(path and path.exists()),
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
                return artifact_file_path(workdir, filename)
        return None

    def report_html_path(self, case_id: str) -> Path | None:
        return self.artifact_path(case_id, "final_html_report")

    def visual_image_path(self, case_id: str, relative_path: str) -> Path | None:
        """Resolve a visual image path within the case workdir.

        Prevents path traversal by ensuring resolved path is under workdir.
        """
        workdir = self.latest_workdir(case_id)
        if not workdir:
            return None
        # Normalize the relative path to prevent traversal
        candidate = (workdir / relative_path).resolve()
        workdir_resolved = workdir.resolve()
        if workdir_resolved not in candidate.parents and candidate != workdir_resolved:
            return None
        return candidate if candidate.exists() and candidate.is_file() else None

    def latest_workdir(self, case_id: str) -> Path | None:
        case = self.store.get_case(case_id)
        if not case.latest_run_id:
            return None
        run = self.store.get_run(case_id, case.latest_run_id)
        if run.workdir:
            return normalize_workdir_path(run.workdir, output_root=self.output_root)
        if run.summary and run.summary.get("workdir"):
            return normalize_workdir_path(
                str(run.summary["workdir"]), output_root=self.output_root
            )
        return None

    @staticmethod
    def artifact_url(case_id: str, artifact_id: str) -> str:
        if artifact_id == "final_html_report":
            return f"/api/cases/{case_id}/report/html"
        return f"/api/cases/{case_id}/artifacts/{artifact_id}"


def file_metadata(path: Path) -> tuple[int, str]:
    stat = path.stat()
    updated_at = (
        datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return stat.st_size, updated_at


def artifact_file_path(workdir: Path, filename: str) -> Path | None:
    return existing_artifact_path(workdir, filename)
