"""Cases, runs, events, and input upload endpoints."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import AppDependencies, get_app_dependencies, get_auth_context, require_case_access
from ..auth import AuthContext
from ..models import CaseCreate, CaseRecord, InputUpload, RunCreate

router = APIRouter(tags=["cases"])


@router.get("/cases")
async def list_cases(
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    cases = deps.store.list_cases(user_id=auth.user_id)
    return {"cases": [c.to_dict() for c in cases]}


@router.post("/cases", status_code=HTTPStatus.CREATED)
async def create_case(
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
async def get_case(case: CaseRecord = Depends(require_case_access)) -> dict[str, Any]:
    return case.to_dict()


@router.post("/cases/{case_id}/inputs")
async def upload_input(
    case_id: str,
    request: Request,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=400, detail="multipart upload requires a 'file' field")
        content = await upload.read()
        filename = getattr(upload, "filename", None) or "upload"
        relative_path = form.get("relative_path")
        path = deps.store.write_input(
            case_id,
            filename,
            content,
            relative_path=str(relative_path) if relative_path else None,
        )
    else:
        # Legacy JSON path (backward compatible)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON payload")
        try:
            payload = InputUpload.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if payload.content_base64 is not None:
            path = deps.store.write_input_base64(case_id, payload.filename, payload.content_base64)
        elif payload.content is not None:
            path = deps.store.write_input(case_id, payload.filename, payload.content.encode("utf-8"))
        else:
            raise HTTPException(status_code=400, detail="input upload requires content_base64 or content")

    updated_case = deps.store.get_case(case_id, user_id=case.owner)

    # 自动提取 paper_title：如果是 PDF 文件且 title 为空或默认值，用文件名更新
    if filename.lower().endswith(".pdf"):
        current_title = updated_case.paper_title or ""
        if not current_title or current_title == "Unknown until parsed":
            # 用文件名（去掉 .pdf 后缀）作为 paper_title
            extracted_title = filename[:-4]  # 去掉 ".pdf"
            updated_case = deps.store.update_case(
                case_id,
                {"paper_title": extracted_title},
                user_id=case.owner,
            )

    return {"path": str(path), "case": updated_case.to_dict()}


@router.post("/cases/{case_id}/runs", status_code=HTTPStatus.ACCEPTED)
async def start_run(
    case_id: str,
    payload: RunCreate,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    run = deps.runner.start(case_id, payload.model_dump())
    return run.to_dict()


@router.get("/cases/{case_id}/runs/{run_id}")
async def get_run(
    case_id: str,
    run_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    run = deps.store.get_run(case_id, run_id)
    return run.to_dict()


@router.get("/cases/{case_id}/runs/{run_id}/events")
async def list_events(
    case_id: str,
    run_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    return {"events": deps.store.list_events(case_id, run_id)}
