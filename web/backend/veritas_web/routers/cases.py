"""Cases, runs, events, and input upload endpoints."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..dependencies import (
    AppDependencies,
    get_app_dependencies,
    get_auth_context,
    require_case_access,
)
from ..auth import AuthContext
from ..permissions import require_admin
from ..models import CaseCreate, CaseRecord, InputUpload
from ..risk import summarize_findings

router = APIRouter(tags=["cases"])

# Maximum allowed upload size for input files (200 MB).
MAX_UPLOAD_SIZE_BYTES = 200 * 1024 * 1024

# Maximum upload size for the legacy JSON base64 path (50 MB).
LEGACY_JSON_UPLOAD_LIMIT_BYTES = 50 * 1024 * 1024


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


@router.get("/cases/stats")
async def get_case_stats(
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    cases = deps.store.list_cases(user_id=auth.user_id)
    return {
        "total_cases": len(cases),
        "total_findings": sum(c.review_needed_count for c in cases),
        "critical_count": sum(
            1 for c in cases if c.technical_risk in ("critical", "high")
        ),
        "running_count": sum(1 for c in cases if c.status == "Running"),
    }


@router.get("/cases/{case_id}")
async def get_case(case: CaseRecord = Depends(require_case_access)) -> dict[str, Any]:
    return case.to_dict()


@router.delete(
    "/cases/{case_id}",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_case(
    case_id: str,
    auth: AuthContext = Depends(get_auth_context),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> None:
    require_admin(auth)
    deps.store.delete_case(case_id)


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
            raise HTTPException(
                status_code=400, detail="multipart upload requires a 'file' field"
            )

        # Early rejection via Content-Length header (avoids reading the
        # entire body into memory when it clearly exceeds the limit).
        cl_header = request.headers.get("content-length")
        if cl_header and cl_header.isdigit():
            if int(cl_header) > MAX_UPLOAD_SIZE_BYTES * 2:
                raise HTTPException(
                    status_code=413, detail="File size exceeds 200MB limit"
                )

        # Stream the upload in chunks to bound peak memory usage.
        filename = getattr(upload, "filename", None) or "upload"
        total_size = 0
        chunks: list[bytes] = []
        chunk_size = 1024 * 1024  # 1 MB
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_UPLOAD_SIZE_BYTES:
                raise HTTPException(
                    status_code=413, detail="File size exceeds 200MB limit"
                )
            chunks.append(chunk)
        content = b"".join(chunks)

        relative_path = form.get("relative_path")
        path = deps.store.write_input(
            case_id,
            filename,
            content,
            relative_path=str(relative_path) if relative_path else None,
        )
    else:
        # Legacy JSON path (backward compatible, deprecated)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON payload")
        try:
            payload = InputUpload.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        filename = payload.filename
        if payload.content_base64 is not None:
            # Estimate decoded size: every 4 base64 chars → 3 bytes.
            estimated_size = len(payload.content_base64) * 3 // 4
            if estimated_size > LEGACY_JSON_UPLOAD_LIMIT_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "JSON upload exceeds 50MB limit. "
                        "Use multipart/form-data upload instead."
                    ),
                )
            path = deps.store.write_input_base64(
                case_id, payload.filename, payload.content_base64
            )
        elif payload.content is not None:
            content_bytes = payload.content.encode("utf-8")
            if len(content_bytes) > LEGACY_JSON_UPLOAD_LIMIT_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "JSON upload exceeds 50MB limit. "
                        "Use multipart/form-data upload instead."
                    ),
                )
            path = deps.store.write_input(
                case_id, payload.filename, content_bytes
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="input upload requires content_base64 or content",
            )

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


@router.get("/cases/{case_id}/risk-summary")
async def get_risk_summary(
    case_id: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Return risk summary with top findings and auto-generated follow-up questions.

    Reads findings from static_audit_bundle.json, computes overall risk level,
    selects top 5 findings (by risk_level, only medium+), and generates
    follow-up questions for each.
    """
    bundle_path = deps.artifacts.artifact_path(case_id, "static_audit_bundle")
    if bundle_path is None or not bundle_path.exists():
        return {
            "status": "unavailable",
            "overall_risk": "unknown",
            "risk_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
            "top_findings": [],
            "follow_ups": {},
            "total_findings": 0,
            "high_quality_count": 0,
            "message": "static_audit_bundle.json is not available for this case",
        }

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    findings = bundle.get("findings", [])
    summary = summarize_findings(findings if isinstance(findings, list) else [])
    top_findings = summary["top_findings"]

    # Auto-generate follow-up questions for each top finding
    from engine.follow_up.generator import create_follow_up_generator

    generator = create_follow_up_generator(deps)

    follow_ups: dict[str, list[str]] = {}
    for finding in top_findings:
        finding_id = finding.get("finding_id", "")
        try:
            questions = await generator.generate(finding)
            follow_ups[finding_id] = questions
        except Exception:
            follow_ups[finding_id] = []

    return {
        "status": summary["status"],
        "overall_risk": summary["overall_risk"],
        "risk_counts": summary["risk_counts"],
        "top_findings": top_findings,
        "follow_ups": follow_ups,
        "total_findings": summary["total_findings"],
        "high_quality_count": summary["high_quality_count"],
    }
