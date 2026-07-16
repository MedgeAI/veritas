from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from engine.exceptions import InvalidPaperPdfError
from engine.static_audit.cli_driver import pdf_candidates, validate_declared_pdf


def pdf_candidate_payloads(inputs_dir: Path) -> list[dict[str, Any]]:
    try:
        return [candidate.to_dict() for candidate in pdf_candidates(inputs_dir)]
    except InvalidPaperPdfError as exc:
        raise invalid_paper_pdf_error(str(exc)) from exc


def ambiguous_paper_pdf_error(inputs_dir: Path) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "AMBIGUOUS_PAPER_PDF",
            "message": "Multiple PDF files found; select the paper PDF explicitly.",
            "pdfs": pdf_candidate_payloads(inputs_dir),
        },
    )


def invalid_paper_pdf_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "INVALID_PAPER_PDF",
            "message": message,
        },
    )


def validate_paper_pdf_relative(inputs_dir: Path, paper_pdf: str) -> str:
    try:
        resolved = validate_declared_pdf(inputs_dir, paper_pdf)
    except (InvalidPaperPdfError, FileNotFoundError) as exc:
        raise invalid_paper_pdf_error(str(exc)) from exc
    return resolved.relative_to(inputs_dir.resolve()).as_posix()
