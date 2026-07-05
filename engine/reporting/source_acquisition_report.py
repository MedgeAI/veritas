"""Source Acquisition Provenance Report (WP10).

Reports on how source data was acquired for the audit: user-uploaded,
publicly fetched, or manually imported.  This ensures that
``no_data_found`` is never misinterpreted as "the paper is clean".

This module consumes the source acquisition manifest artifact and
produces a structured summary for the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AcquiredFile:
    """A single acquired source data file.

    Attributes:
        path: Relative path within the audit workdir.
        sha256: SHA-256 hash of the file.
        size_bytes: File size in bytes.
        source_url: URL from which the file was downloaded.
        origin: One of "user_uploaded", "public_fetched", "manual_imported".
    """

    path: str = ""
    sha256: str = ""
    size_bytes: int = 0
    source_url: str = ""
    origin: str = "user_uploaded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source_url": self.source_url,
            "origin": self.origin,
        }


@dataclass(frozen=True)
class SourceAcquisitionReport:
    """Summary of source data acquisition provenance.

    Attributes:
        status: Overall acquisition status — "downloaded", "partial",
            "no_data_found", "user_only", "not_attempted".
        query: The original query (DOI/title/URL) if public fetch was attempted.
        matched_sources: Number of sources matched during public fetch.
        max_match_confidence: Highest match confidence among matched sources.
        downloaded_files: List of acquired files.
        fetch_errors: List of fetch error descriptions.
        no_data_found_reason: Why no data was found (if applicable).
        manual_confirmation_required: Whether any matched source requires
            manual confirmation before use.
        has_user_uploaded: Whether any file was user-uploaded.
        has_public_fetched: Whether any file was publicly fetched.
        has_manual_imported: Whether any file was manually imported.
        total_files: Total number of acquired files.
        total_size_bytes: Total size of all acquired files.
    """

    status: str = "not_attempted"
    query: dict[str, str] = field(default_factory=dict)
    matched_sources: int = 0
    max_match_confidence: float = 0.0
    downloaded_files: list[AcquiredFile] = field(default_factory=list)
    fetch_errors: list[str] = field(default_factory=list)
    no_data_found_reason: str = ""
    manual_confirmation_required: bool = False
    has_user_uploaded: bool = False
    has_public_fetched: bool = False
    has_manual_imported: bool = False
    total_files: int = 0
    total_size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "query": dict(self.query),
            "matched_sources": self.matched_sources,
            "max_match_confidence": self.max_match_confidence,
            "downloaded_files": [f.to_dict() for f in self.downloaded_files],
            "fetch_errors": list(self.fetch_errors),
            "no_data_found_reason": self.no_data_found_reason,
            "manual_confirmation_required": self.manual_confirmation_required,
            "has_user_uploaded": self.has_user_uploaded,
            "has_public_fetched": self.has_public_fetched,
            "has_manual_imported": self.has_manual_imported,
            "total_files": self.total_files,
            "total_size_bytes": self.total_size_bytes,
        }


def build_source_acquisition_report(
    manifest: dict[str, Any] | None = None,
) -> SourceAcquisitionReport:
    """Build a SourceAcquisitionReport from a source acquisition manifest.

    Args:
        manifest: The source acquisition manifest dict, as produced by
            the source_data.fetch_public tool or user upload pipeline.

    Returns:
        A SourceAcquisitionReport summarizing the acquisition provenance.
    """
    if not manifest:
        return SourceAcquisitionReport()

    status = str(manifest.get("status", "not_attempted"))
    query_raw = manifest.get("query", {})
    query = dict(query_raw) if isinstance(query_raw, dict) else {}

    matched_sources_list = manifest.get("matched_sources", [])
    matched_sources = len(matched_sources_list) if isinstance(matched_sources_list, list) else 0

    # Max match confidence
    max_confidence = 0.0
    if isinstance(matched_sources_list, list):
        for src in matched_sources_list:
            conf = src.get("match_confidence", 0.0) if isinstance(src, dict) else 0.0
            if isinstance(conf, (int, float)) and conf > max_confidence:
                max_confidence = float(conf)

    # Downloaded files
    files_raw = manifest.get("downloaded_files", [])
    files: list[AcquiredFile] = []
    has_user = has_fetched = has_manual = False

    if isinstance(files_raw, list):
        for f in files_raw:
            if not isinstance(f, dict):
                continue
            origin = str(f.get("origin", "user_uploaded"))
            if origin == "user_uploaded":
                has_user = True
            elif origin == "public_fetched":
                has_fetched = True
            elif origin == "manual_imported":
                has_manual = True
            files.append(
                AcquiredFile(
                    path=str(f.get("path", "")),
                    sha256=str(f.get("sha256", "")),
                    size_bytes=int(f.get("size_bytes", 0)),
                    source_url=str(f.get("source_url", "")),
                    origin=origin,
                )
            )

    # Fetch errors
    errors_raw = manifest.get("fetch_errors", [])
    fetch_errors: list[str] = []
    if isinstance(errors_raw, list):
        fetch_errors = [str(e) for e in errors_raw]

    # Manual confirmation required
    manual_confirm = any(
        src.get("manual_confirmation_required", False)
        for src in (matched_sources_list if isinstance(matched_sources_list, list) else [])
        if isinstance(src, dict)
    )

    total_size = sum(f.size_bytes for f in files)

    return SourceAcquisitionReport(
        status=status,
        query=query,
        matched_sources=matched_sources,
        max_match_confidence=max_confidence,
        downloaded_files=files,
        fetch_errors=fetch_errors,
        no_data_found_reason=str(manifest.get("no_data_found_reason", "")),
        manual_confirmation_required=manual_confirm,
        has_user_uploaded=has_user,
        has_public_fetched=has_fetched,
        has_manual_imported=has_manual,
        total_files=len(files),
        total_size_bytes=total_size,
    )
