"""Cases, runs, events, and input upload endpoints."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import AppDependencies, get_app_dependencies, get_auth_context, require_case_access
from ..auth import AuthContext
from ..models import CaseCreate, CaseRecord, InputUpload, RunCreate

router = APIRouter(tags=["cases"])


@router.get("/cases")
def list_cases(
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    cases = deps.store.list_cases(user_id=auth.user_id)
    return {"cases": [c.to_dict() for c in cases]}


@router.post("/cases", status_code=HTTPStatus.CREATED)
def create_case(
    payload: CaseCreate,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    case = deps.store.create_case(
        user_id=auth.user_id,
        paper_title=payload.paper_title,
        case_id=payload.case_id,
    )
    return case.to_dict()


@router.get("/cases/{case_id}")
def get_case(case: CaseRecord = Depends(require_case_access)) -> dict[str, Any]:
    return case.to_dict()


@router.post("/cases/{case_id}/inputs")
def upload_input(
    case_id: str,
    payload: InputUpload,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    if payload.content_base64 is not None:
        path = deps.store.write_input_base64(
            case_id,
            payload.filename,
            payload.content_base64,
        )
    elif payload.content is not None:
        path = deps.store.write_input(
            case_id,
            payload.filename,
            payload.content.encode("utf-8"),
        )
    else:
        raise HTTPException(status_code=400, detail="input upload requires content_base64 or content")
    updated_case = deps.store.get_case(case_id, user_id=case.owner)
    return {"path": str(path), "case": updated_case.to_dict()}


@router.post("/cases/{case_id}/runs", status_code=HTTPStatus.ACCEPTED)
def start_run(
    case_id: str,
    payload: RunCreate,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    run = deps.runner.start(case_id, payload.model_dump())
    return run.to_dict()


@router.get("/cases/{case_id}/runs/{run_id}")
def get_run(
    case_id: str,
    run_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    run = deps.store.get_run(case_id, run_id)
    return run.to_dict()


@router.get("/cases/{case_id}/runs/{run_id}/events")
def list_events(
    case_id: str,
    run_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    return {"events": deps.store.list_events(case_id, run_id)}
