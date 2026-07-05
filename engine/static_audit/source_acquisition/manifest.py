"""Data model for source acquisition provenance.

Every public source data fetch produces a :class:`SourceAcquisitionManifest`
that records what was queried, what was matched, what was downloaded, and
— critically — why data was NOT found when that happens.

``no_data_found`` does NOT mean the paper is clean.  It means public source
data was not found or could not be accessed.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

MANIFEST_SCHEMA_VERSION = "1.0"

MatchStatus = Literal["downloaded", "needs_confirmation", "no_data_found", "error"]

SOURCE_NATURE_ESM = "nature_esm"
SOURCE_ZENODO = "zenodo"
SOURCE_FIGSHARE = "figshare"
SOURCE_DRYAD = "dryad"
SOURCE_EUROPE_PMC = "europe_pmc"
SOURCE_DIRECT_URL = "direct_url"

ALL_SOURCES = (
    SOURCE_NATURE_ESM,
    SOURCE_ZENODO,
    SOURCE_FIGSHARE,
    SOURCE_DRYAD,
    SOURCE_EUROPE_PMC,
    SOURCE_DIRECT_URL,
)

# Confidence threshold below which a match is considered "weak" and requires
# manual confirmation before auto-downloading.
WEAK_MATCH_THRESHOLD = 0.7


@dataclass(frozen=True)
class AcquisitionQuery:
    """What the user (or pipeline) asked to fetch."""

    doi: str | None = None
    title: str | None = None
    url: str | None = None

    def primary_key(self) -> str:
        """Return the most specific identifier available."""
        if self.doi:
            return f"doi:{self.doi}"
        if self.url:
            return f"url:{self.url}"
        if self.title:
            return f"title:{self.title}"
        return "empty"


@dataclass(frozen=True)
class MatchedSource:
    """A candidate source-data location found by a provider."""

    source: str  # one of ALL_SOURCES
    url: str
    match_confidence: float  # 0.0 – 1.0
    match_basis: tuple[str, ...]  # e.g. ("doi_exact",), ("title_fuzzy",)
    auto_downloaded: bool
    manual_confirmation_required: bool = False
    file_type_hint: str | None = None  # "xlsx", "csv", "zip", "pdf", etc.
    description: str | None = None

    def __post_init__(self) -> None:
        if self.match_confidence < 0 or self.match_confidence > 1:
            object.__setattr__(
                self, "match_confidence", max(0.0, min(1.0, self.match_confidence))
            )
        # Weak matches always require manual confirmation.
        if self.match_confidence < WEAK_MATCH_THRESHOLD and not self.manual_confirmation_required:
            object.__setattr__(self, "manual_confirmation_required", True)


@dataclass(frozen=True)
class DownloadedFile:
    """A file successfully written to disk."""

    path: str  # relative to the case output directory
    sha256: str
    size_bytes: int
    source_url: str
    source: str  # provider name
    license_or_terms_note: str | None = None


@dataclass
class SourceAcquisitionManifest:
    """Top-level provenance record for a public source data fetch.

    Mutable so the orchestrator can progressively populate it.
    """

    schema_version: str = MANIFEST_SCHEMA_VERSION
    query: AcquisitionQuery = field(default_factory=AcquisitionQuery)
    status: MatchStatus = "no_data_found"
    matched_sources: list[MatchedSource] = field(default_factory=list)
    downloaded_files: list[DownloadedFile] = field(default_factory=list)
    fetch_errors: list[str] = field(default_factory=list)
    no_data_found_reason: str | None = None
    note: str = (
        "no_data_found means public source data was not found or could not "
        "be accessed; it does NOT mean the paper is clean."
    )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceAcquisitionManifest:
        query_data = data.get("query", {})
        query = AcquisitionQuery(
            doi=query_data.get("doi"),
            title=query_data.get("title"),
            url=query_data.get("url"),
        )
        matched = [
            MatchedSource(
                source=m["source"],
                url=m["url"],
                match_confidence=m["match_confidence"],
                match_basis=tuple(m.get("match_basis", ())),
                auto_downloaded=m["auto_downloaded"],
                manual_confirmation_required=m.get("manual_confirmation_required", False),
                file_type_hint=m.get("file_type_hint"),
                description=m.get("description"),
            )
            for m in data.get("matched_sources", [])
        ]
        downloaded = [
            DownloadedFile(
                path=f["path"],
                sha256=f["sha256"],
                size_bytes=f["size_bytes"],
                source_url=f["source_url"],
                source=f["source"],
                license_or_terms_note=f.get("license_or_terms_note"),
            )
            for f in data.get("downloaded_files", [])
        ]
        return cls(
            schema_version=data.get("schema_version", MANIFEST_SCHEMA_VERSION),
            query=query,
            status=data.get("status", "no_data_found"),
            matched_sources=matched,
            downloaded_files=downloaded,
            fetch_errors=data.get("fetch_errors", []),
            no_data_found_reason=data.get("no_data_found_reason"),
        )

    @classmethod
    def read(cls, path: Path) -> SourceAcquisitionManifest:
        return cls.from_dict(json.loads(path.read_text()))
