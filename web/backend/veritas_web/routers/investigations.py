"""Investigation list and execution endpoints."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends

from ..dependencies import AppDependencies, get_app_dependencies, require_case_access
from ..models import CaseRecord, InvestigationRunRequest

router = APIRouter(tags=["investigations"])


@router.get("/cases/{case_id}/investigations")
def list_investigations(
    case_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    return deps.investigations.list_investigations(case_id)


@router.post("/cases/{case_id}/investigations", status_code=HTTPStatus.CREATED)
def run_investigation(
    case_id: str,
    payload: InvestigationRunRequest,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    return deps.investigations.run_investigation(case_id, payload.model_dump())
