"""Core orchestration for public source data acquisition.

Given a query (DOI / title / URL), run all applicable providers, download
matched files, compute sha256, and produce a :class:`SourceAcquisitionManifest`.

All HTTP I/O goes through ``runtime.http_fetch`` — this module never imports
``urllib`` or ``requests`` directly.
"""
from __future__ import annotations

import logging
from pathlib import Path

from engine.static_audit.source_acquisition.manifest import (
    AcquisitionQuery,
    DownloadedFile,
    MatchedSource,
    SourceAcquisitionManifest,
)
from engine.static_audit.source_acquisition.providers import (
    ALL_PROVIDERS,
    BaseProvider,
    FetchClient,
)
from runtime.http_fetch import FetchResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runtime FetchClient implementation
# ---------------------------------------------------------------------------


class RuntimeFetchClient:
    """Production FetchClient backed by ``runtime.http_fetch``."""

    def __init__(self, *, timeout: int = 30) -> None:
        self._timeout = timeout

    def fetch_json(self, url: str) -> FetchResult:
        from runtime.http_fetch import fetch_json
        return fetch_json(url, timeout=self._timeout)

    def fetch_text(self, url: str) -> FetchResult:
        from runtime.http_fetch import fetch_text
        return fetch_text(url, timeout=self._timeout)

    def download(self, url: str, dest: str | Path) -> FetchResult:
        from runtime.http_fetch import fetch_to_file
        return fetch_to_file(url, Path(dest), timeout=self._timeout)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def fetch_public_source_data(
    *,
    query: AcquisitionQuery,
    output_dir: Path,
    client: FetchClient | None = None,
    providers: list[BaseProvider] | None = None,
) -> SourceAcquisitionManifest:
    """Run public source data acquisition and return a manifest.

    Parameters
    ----------
    query:
        What to look for (DOI, title, URL).
    output_dir:
        Where to write downloaded files and the manifest.
    client:
        HTTP client.  Defaults to :class:`RuntimeFetchClient`.
    providers:
        Provider list.  Defaults to :data:`ALL_PROVIDERS`.
    """
    if client is None:
        client = RuntimeFetchClient()
    if providers is None:
        providers = list(ALL_PROVIDERS)

    manifest = SourceAcquisitionManifest(query=query)
    download_dir = output_dir / "source_data"
    download_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: search across providers
    all_matches: list[MatchedSource] = []
    for provider in providers:
        try:
            result = provider.search(query, client)
            all_matches.extend(result.matches)
            manifest.fetch_errors.extend(result.errors)
        except Exception as exc:
            manifest.fetch_errors.append(f"{provider.source_name}: unhandled error: {exc}")

    manifest.matched_sources = all_matches

    if not all_matches:
        manifest.status = "no_data_found"
        manifest.no_data_found_reason = _build_no_data_reason(query, manifest.fetch_errors)
        manifest.write(output_dir / "source_acquisition_manifest.json")
        return manifest

    # Phase 2: download auto-downloadable files
    downloaded: list[DownloadedFile] = []
    needs_confirmation: list[MatchedSource] = []
    for match in all_matches:
        if match.manual_confirmation_required:
            needs_confirmation.append(match)
            continue
        if not match.auto_downloaded:
            continue
        try:
            fname = _safe_filename(match.url, match.source)
            dest = download_dir / fname
            resp = client.download(match.url, dest)
            if resp.ok and resp.dest_path and resp.sha256 and resp.size_bytes is not None:
                downloaded.append(
                    DownloadedFile(
                        path=str(dest.relative_to(output_dir)),
                        sha256=resp.sha256,
                        size_bytes=resp.size_bytes,
                        source_url=match.url,
                        source=match.source,
                    )
                )
            else:
                manifest.fetch_errors.append(
                    f"download failed for {match.url}: {resp.error or 'unknown'}"
                )
        except Exception as exc:
            manifest.fetch_errors.append(f"download error for {match.url}: {exc}")

    manifest.downloaded_files = downloaded

    # Phase 3: determine status
    if downloaded:
        if needs_confirmation:
            manifest.status = "downloaded"  # partial success
        else:
            manifest.status = "downloaded"
    elif needs_confirmation:
        manifest.status = "needs_confirmation"
    else:
        manifest.status = "no_data_found"
        manifest.no_data_found_reason = _build_no_data_reason(
            query, manifest.fetch_errors
        )

    manifest.write(output_dir / "source_acquisition_manifest.json")
    return manifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_filename(url: str, source: str) -> str:
    """Derive a filesystem-safe filename from a URL."""
    import re
    from urllib.parse import urlparse, unquote

    parsed = urlparse(url)
    name = unquote(parsed.path.rsplit("/", 1)[-1])
    # Strip query/fragment leftovers, sanitize
    name = re.sub(r"[^\w.\-]", "_", name)
    if not name or name == "_":
        name = f"{source}_file"
    return name


def _build_no_data_reason(
    query: AcquisitionQuery, errors: list[str]
) -> str:
    """Build a human-readable reason for why no data was found."""
    parts: list[str] = []
    key = query.primary_key()
    parts.append(f"Public source data not found for {key}.")

    if errors:
        parts.append("Provider errors:")
        for err in errors[:5]:
            parts.append(f"  - {err}")
    else:
        parts.append("No provider returned any matching source.")

    parts.append(
        "This does NOT mean the paper is clean — data may exist behind "
        "access controls, require author request, or be hosted on an "
        "unsupported platform."
    )
    return "\n".join(parts)
