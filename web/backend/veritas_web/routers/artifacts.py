"""Artifact listing, single artifact retrieval, and HTML report serving."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..dependencies import AppDependencies, get_app_dependencies, require_case_access
from ..models import CaseRecord

router = APIRouter(tags=["artifacts"])


@router.get("/cases/{case_id}/artifacts")
def list_artifacts(
    case_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    refs = deps.artifacts.list_artifacts(case_id)
    return {"artifacts": [ref.to_dict() for ref in refs]}


@router.get("/cases/{case_id}/artifacts/{artifact_id}")
def get_artifact(
    case_id: str,
    artifact_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> Response:
    path = deps.artifacts.artifact_path(case_id, artifact_id)
    if not path:
        raise HTTPException(status_code=404, detail=f"artifact not found: {artifact_id}")
    content_type = "application/json"
    if path.suffix == ".jsonl":
        content_type = "application/x-ndjson"
    elif path.suffix == ".md":
        content_type = "text/markdown; charset=utf-8"
    return Response(content=path.read_bytes(), media_type=content_type)


@router.get("/cases/{case_id}/report/html")
def get_report_html(
    case_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> Response:
    path = deps.artifacts.report_html_path(case_id)
    if not path:
        raise HTTPException(status_code=404, detail="final HTML report not found")
    return Response(content=path.read_bytes(), media_type="text/html; charset=utf-8")
