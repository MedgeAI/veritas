"""Public verification router — no auth required.

Provides endpoints for external parties (journal editors, etc.) to verify
the authenticity of a Veritas certification by report ID.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from engine.static_audit.report_id import validate_report_id
from engine.static_audit.verify_store import load_verification_summary

router = APIRouter(prefix="/api/verify", tags=["verify"])


class VerificationResponse(BaseModel):
    """Response model for verification lookup."""

    verified: bool
    report_id: str | None = None
    case_id: str | None = None
    paper_title: str | None = None
    grade: str | None = None
    grade_label: str | None = None
    dimensions: list[dict] | None = None
    summary: str | None = None
    total_findings: int | None = None
    created_at: str | None = None
    version: str | None = None
    error: str | None = None


@router.get("/{report_id}")
async def verify_by_id(report_id: str):
    """Look up a verification summary by report ID.

    Returns 404 with {"verified": false} if not found.
    Returns 200 with {"verified": true, ...summary} if found.
    """
    # Validate format
    if not validate_report_id(report_id):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid report ID format: {report_id}. Expected format: VRT-YYYYMM-XXXXXX",
        )

    # Load from store
    summary = load_verification_summary(report_id)
    if summary is None:
        return JSONResponse(
            status_code=404,
            content={
                "verified": False,
                "report_id": report_id,
                "error": "Report not found",
            },
        )

    # Return verified response
    return {
        "verified": True,
        "report_id": summary.get("report_id"),
        "case_id": summary.get("case_id"),
        "paper_title": summary.get("paper_title"),
        "grade": summary.get("grade"),
        "grade_label": summary.get("grade_label"),
        "dimensions": summary.get("dimensions"),
        "summary": summary.get("summary"),
        "total_findings": summary.get("total_findings"),
        "created_at": summary.get("created_at"),
        "version": summary.get("version"),
    }


@router.get("")
async def verify_by_query(q: str):
    """Search for a verification by report ID (query parameter).

    This is the endpoint for the input form on the verify page.
    Returns 400 for invalid format, 200 with verified=True/False.
    """
    # Validate format
    if not validate_report_id(q):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid report ID format: {q}. Expected format: VRT-YYYYMM-XXXXXX",
        )

    # Load from store
    summary = load_verification_summary(q)
    if summary is None:
        return {
            "verified": False,
            "report_id": q,
            "error": "Report not found",
        }

    # Return verified response
    return {
        "verified": True,
        "report_id": summary.get("report_id"),
        "case_id": summary.get("case_id"),
        "paper_title": summary.get("paper_title"),
        "grade": summary.get("grade"),
        "grade_label": summary.get("grade_label"),
        "dimensions": summary.get("dimensions"),
        "summary": summary.get("summary"),
        "total_findings": summary.get("total_findings"),
        "created_at": summary.get("created_at"),
        "version": summary.get("version"),
    }
