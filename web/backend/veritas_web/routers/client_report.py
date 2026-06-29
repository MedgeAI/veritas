"""Client Report BFF endpoint — aggregated view for customer-facing report."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..client_report_service import build_client_report
from ..dependencies import AppDependencies, get_app_dependencies, require_case_access
from ..models import CaseRecord

router = APIRouter(tags=["client-report"])


@router.get("/cases/{case_id}/client-report")
async def get_client_report(
    case: CaseRecord = Depends(require_case_access),
    deps: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    """Return the aggregated ClientReportView for a case.

    Combines certification grade, risk summary, certainty layers,
    review items, and verification metadata into a single response.
    """
    return build_client_report(deps, case.case_id)
