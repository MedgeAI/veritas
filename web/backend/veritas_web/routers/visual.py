"""Visual forensics artifact endpoints (figures, panels, relationships, findings, images)."""

from __future__ import annotations

import json
import mimetypes
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..dependencies import AppDependencies, get_app_dependencies, require_case_access
from ..models import CaseRecord

router = APIRouter(tags=["visual"])

_ARTIFACT_MAP = {
    "figures": "visual_evidence",
    "panels": "panel_evidence",
    "relationships": "image_relationships",
    "findings": "visual_findings",
}


@router.get("/cases/{case_id}/visual/{artifact_type}")
async def get_visual_artifact(
    case_id: str,
    artifact_type: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    artifact_id = _ARTIFACT_MAP.get(artifact_type)
    if not artifact_id:
        raise HTTPException(status_code=404, detail=f"unknown visual artifact type: {artifact_type}")
    path = deps.artifacts.artifact_path(case_id, artifact_id)
    if not path:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "detail": f"visual artifact not found: {artifact_type}"},
        )
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/cases/{case_id}/visual/images/{image_path:path}")
async def get_visual_image(
    case_id: str,
    image_path: str,
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> Response:
    path = deps.artifacts.visual_image_path(case_id, image_path)
    if not path:
        raise HTTPException(status_code=404, detail=f"image not found: {image_path}")
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return Response(content=path.read_bytes(), media_type=content_type)
