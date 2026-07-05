"""Source-data provider implementations.

Each provider knows how to discover downloadable source-data files from a
specific public repository, given a DOI, title, or URL.

Providers do NOT import ``urllib`` or ``requests`` directly.  They receive a
:class:`FetchClient` callback that delegates to ``runtime.http_fetch``.  This
makes unit testing trivial: inject a mock client that returns fixture data.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote_plus

from engine.static_audit.source_acquisition.manifest import (
    AcquisitionQuery,
    MatchedSource,
    SOURCE_DIRECT_URL,
    SOURCE_DRYAD,
    SOURCE_EUROPE_PMC,
    SOURCE_FIGSHARE,
    SOURCE_NATURE_ESM,
    SOURCE_ZENODO,
    WEAK_MATCH_THRESHOLD,
)
from runtime.http_fetch import FetchResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fetch client protocol — the only way providers perform HTTP I/O
# ---------------------------------------------------------------------------


class FetchClient(Protocol):
    """Minimal interface providers use to fetch URLs.

    Satisfied by :class:`runtime.http_fetch` functions.  In tests, a dict- or
    list-backed stub is injected instead.
    """

    def fetch_json(self, url: str) -> FetchResult: ...
    def fetch_text(self, url: str) -> FetchResult: ...
    def download(self, url: str, dest: "str | Path") -> FetchResult: ...


from pathlib import Path  # noqa: E402  (used in protocol above)


# ---------------------------------------------------------------------------
# Provider base
# ---------------------------------------------------------------------------


@dataclass
class ProviderResult:
    """Outcome of a single provider's search."""

    source: str
    matches: list[MatchedSource]
    errors: list[str]


class BaseProvider:
    """Common scaffolding for all providers."""

    source_name: str = ""

    def search(self, query: AcquisitionQuery, client: FetchClient) -> ProviderResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Zenodo
# ---------------------------------------------------------------------------

# Zenodo records carry a DOI like 10.5281/zenodo.XXXXXXX
_ZENODO_DOI_RE = re.compile(r"^10\.5281/zenodo\.(\d+)", re.IGNORECASE)


class ZenodoProvider(BaseProvider):
    source_name = SOURCE_ZENODO

    def search(self, query: AcquisitionQuery, client: FetchClient) -> ProviderResult:
        matches: list[MatchedSource] = []
        errors: list[str] = []
        if not query.doi:
            return ProviderResult(self.source_name, matches, errors)

        zenodo_match = _ZENODO_DOI_RE.match(query.doi)
        if zenodo_match:
            record_id = zenodo_match.group(1)
            api_url = f"https://zenodo.org/api/records/{record_id}"
        else:
            # Try Zenodo search API with DOI
            api_url = f"https://zenodo.org/api/records?q=doi:%22{quote_plus(query.doi)}%22"

        resp = client.fetch_json(api_url)
        if not resp.ok:
            errors.append(f"zenodo: {resp.error or f'HTTP {resp.status_code}'}")
            return ProviderResult(self.source_name, matches, errors)

        if not resp.text_body:
            errors.append("zenodo: empty response body")
            return ProviderResult(self.source_name, matches, errors)

        try:
            data = json.loads(resp.text_body)
        except json.JSONDecodeError as exc:
            errors.append(f"zenodo: invalid JSON: {exc}")
            return ProviderResult(self.source_name, matches, errors)

        # Single record response
        files = data.get("files", [])
        if not files and "hits" in data:
            # Search response — take first hit
            hits = data["hits"].get("hits", [])
            if hits:
                files = hits[0].get("files", [])

        for f in files:
            file_url = f.get("links", {}).get("self", "")
            if not file_url:
                continue
            fname = f.get("key", f.get("filename", "unknown"))
            file_type = _guess_file_type(fname)
            matches.append(
                MatchedSource(
                    source=self.source_name,
                    url=file_url,
                    match_confidence=1.0 if zenodo_match else 0.8,
                    match_basis=("doi_exact",) if zenodo_match else ("doi_search",),
                    auto_downloaded=True,
                    file_type_hint=file_type,
                    description=f"Zenodo: {fname}",
                )
            )

        return ProviderResult(self.source_name, matches, errors)


# ---------------------------------------------------------------------------
# Figshare
# ---------------------------------------------------------------------------

# Figshare DOIs: 10.6084/m9.figshare.XXXXXXX
_FIGSHARE_DOI_RE = re.compile(
    r"^10\.6084/m9\.figshare\.(\d+)", re.IGNORECASE
)


class FigshareProvider(BaseProvider):
    source_name = SOURCE_FIGSHARE

    def search(self, query: AcquisitionQuery, client: FetchClient) -> ProviderResult:
        matches: list[MatchedSource] = []
        errors: list[str] = []
        if not query.doi:
            return ProviderResult(self.source_name, matches, errors)

        fig_match = _FIGSHARE_DOI_RE.match(query.doi)
        if fig_match:
            article_id = fig_match.group(1)
        else:
            errors.append("figshare: DOI does not match figshare pattern")
            return ProviderResult(self.source_name, matches, errors)

        api_url = f"https://api.figshare.com/v2/articles/{article_id}"
        resp = client.fetch_json(api_url)
        if not resp.ok:
            errors.append(f"figshare: {resp.error or f'HTTP {resp.status_code}'}")
            return ProviderResult(self.source_name, matches, errors)

        if not resp.text_body:
            errors.append("figshare: empty response body")
            return ProviderResult(self.source_name, matches, errors)

        try:
            data = json.loads(resp.text_body)
        except json.JSONDecodeError as exc:
            errors.append(f"figshare: invalid JSON: {exc}")
            return ProviderResult(self.source_name, matches, errors)

        for f in data.get("files", []):
            file_url = f.get("download_url", "")
            if not file_url:
                continue
            fname = f.get("name", "unknown")
            matches.append(
                MatchedSource(
                    source=self.source_name,
                    url=file_url,
                    match_confidence=1.0,
                    match_basis=("doi_exact",),
                    auto_downloaded=True,
                    file_type_hint=_guess_file_type(fname),
                    description=f"Figshare: {fname}",
                )
            )

        return ProviderResult(self.source_name, matches, errors)


# ---------------------------------------------------------------------------
# Dryad
# ---------------------------------------------------------------------------

# Dryad DOIs: 10.5061/dryad.XXXXXXX
_DRYAD_DOI_RE = re.compile(r"^10\.5061/dryad\.", re.IGNORECASE)


class DryadProvider(BaseProvider):
    source_name = SOURCE_DRYAD

    def search(self, query: AcquisitionQuery, client: FetchClient) -> ProviderResult:
        matches: list[MatchedSource] = []
        errors: list[str] = []
        if not query.doi:
            return ProviderResult(self.source_name, matches, errors)

        if not _DRYAD_DOI_RE.match(query.doi):
            return ProviderResult(self.source_name, matches, errors)

        # Dryad v2 API: search by DOI
        api_url = f"https://datadryad.org/api/v2/datasets/doi%3A{quote_plus(query.doi)}"
        resp = client.fetch_json(api_url)
        if not resp.ok:
            errors.append(f"dryad: {resp.error or f'HTTP {resp.status_code}'}")
            return ProviderResult(self.source_name, matches, errors)

        if not resp.text_body:
            errors.append("dryad: empty response body")
            return ProviderResult(self.source_name, matches, errors)

        try:
            data = json.loads(resp.text_body)
        except json.JSONDecodeError as exc:
            errors.append(f"dryad: invalid JSON: {exc}")
            return ProviderResult(self.source_name, matches, errors)

        # Dryad returns _embedded.processSteps with file info
        process_steps = data.get("_embedded", {}).get("processSteps", [])
        for step in process_steps:
            for f in step.get("files", []):
                file_url = f.get("downloadPath", "")
                if not file_url:
                    continue
                fname = f.get("fileName", "unknown")
                matches.append(
                    MatchedSource(
                        source=self.source_name,
                        url=file_url,
                        match_confidence=1.0,
                        match_basis=("doi_exact",),
                        auto_downloaded=True,
                        file_type_hint=_guess_file_type(fname),
                        description=f"Dryad: {fname}",
                    )
                )

        return ProviderResult(self.source_name, matches, errors)


# ---------------------------------------------------------------------------
# Nature ESM (and Springer Nature family)
# ---------------------------------------------------------------------------

# Nature articles carry a DOI like 10.1038/s41558-0XX-XXXX-X
_NATURE_DOI_RE = re.compile(r"^10\.1038/", re.IGNORECASE)


class NatureESMProvider(BaseProvider):
    source_name = SOURCE_NATURE_ESM

    def search(self, query: AcquisitionQuery, client: FetchClient) -> ProviderResult:
        matches: list[MatchedSource] = []
        errors: list[str] = []

        if not query.doi and not query.url:
            return ProviderResult(self.source_name, matches, errors)

        # Resolve DOI to article URL
        if query.doi and _NATURE_DOI_RE.match(query.doi):
            article_url = f"https://doi.org/{query.doi}"
        elif query.url and "nature.com" in query.url:
            article_url = query.url
        else:
            return ProviderResult(self.source_name, matches, errors)

        resp = client.fetch_text(article_url)
        if not resp.ok:
            errors.append(f"nature_esm: {resp.error or f'HTTP {resp.status_code}'}")
            return ProviderResult(self.source_name, matches, errors)

        if not resp.text_body:
            errors.append("nature_esm: empty response body")
            return ProviderResult(self.source_name, matches, errors)

        # Look for supplementary file links in the HTML.
        # Nature ESM articles typically link supplementary files at patterns
        # like /articles/s41558-XXXX/esm or via "Extended data" / "Supplementary
        # information" sections.
        esm_links = _extract_nature_esm_links(resp.text_body, article_url)
        for link_url, description in esm_links:
            confidence = 0.9 if "esm" in link_url.lower() or "supplementary" in link_url.lower() else 0.6
            matches.append(
                MatchedSource(
                    source=self.source_name,
                    url=link_url,
                    match_confidence=confidence,
                    match_basis=("doi_exact", "page_scrape"),
                    auto_downloaded=confidence >= WEAK_MATCH_THRESHOLD,
                    manual_confirmation_required=confidence < WEAK_MATCH_THRESHOLD,
                    file_type_hint=_guess_file_type(link_url),
                    description=description or "Nature ESM supplementary",
                )
            )

        return ProviderResult(self.source_name, matches, errors)


def _extract_nature_esm_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Extract supplementary / ESM file links from a Nature article page.

    This is intentionally a simple regex-based scan — not a full HTML parser.
    Returns ``(absolute_url, description)`` pairs.
    """
    results: list[tuple[str, str]] = []
    # Match href attributes pointing to supplementary / esm files
    pattern = re.compile(
        r'href="([^"]*(?:supplementary|esm|extended[- ]data)[^"]*\.(?:xlsx|csv|zip|pdf|docx?))"',
        re.IGNORECASE,
    )
    for m in pattern.finditer(html):
        url = m.group(1)
        if not url.startswith("http"):
            # Resolve relative URL
            from urllib.parse import urljoin
            url = urljoin(base_url, url)
        results.append((url, f"Nature supplementary: {url.rsplit('/', 1)[-1]}"))
    return results


# ---------------------------------------------------------------------------
# Europe PMC
# ---------------------------------------------------------------------------

class EuropePMCProvider(BaseProvider):
    source_name = SOURCE_EUROPE_PMC

    def search(self, query: AcquisitionQuery, client: FetchClient) -> ProviderResult:
        matches: list[MatchedSource] = []
        errors: list[str] = []

        if not query.doi:
            return ProviderResult(self.source_name, matches, errors)

        api_url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
            f"query=doi:{quote_plus(query.doi)}&format=json&resultType=core"
        )
        resp = client.fetch_json(api_url)
        if not resp.ok:
            errors.append(f"europe_pmc: {resp.error or f'HTTP {resp.status_code}'}")
            return ProviderResult(self.source_name, matches, errors)

        if not resp.text_body:
            errors.append("europe_pmc: empty response body")
            return ProviderResult(self.source_name, matches, errors)

        try:
            data = json.loads(resp.text_body)
        except json.JSONDecodeError as exc:
            errors.append(f"europe_pmc: invalid JSON: {exc}")
            return ProviderResult(self.source_name, matches, errors)

        result_list = data.get("resultList", {}).get("result", [])
        if not result_list:
            return ProviderResult(self.source_name, matches, errors)

        article = result_list[0]
        pmcid = article.get("pmcid")
        if not pmcid:
            errors.append("europe_pmc: no PMCID found (OA supplementary requires PMCID)")
            return ProviderResult(self.source_name, matches, errors)

        # Fetch supplementary files for this PMCID
        supp_url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles"
        )
        supp_resp = client.fetch_text(supp_url)
        if supp_resp.ok and supp_resp.text_body:
            # The supplementary files endpoint returns a listing — for now
            # record the endpoint URL as a candidate.
            matches.append(
                MatchedSource(
                    source=self.source_name,
                    url=supp_url,
                    match_confidence=0.85,
                    match_basis=("pmcid_from_doi",),
                    auto_downloaded=True,
                    file_type_hint="zip",
                    description=f"Europe PMC supplementary for {pmcid}",
                )
            )

        return ProviderResult(self.source_name, matches, errors)


# ---------------------------------------------------------------------------
# Direct URL
# ---------------------------------------------------------------------------

class DirectURLProvider(BaseProvider):
    source_name = SOURCE_DIRECT_URL

    def search(self, query: AcquisitionQuery, client: FetchClient) -> ProviderResult:
        matches: list[MatchedSource] = []
        errors: list[str] = []

        if not query.url:
            return ProviderResult(self.source_name, matches, errors)

        url = query.url
        # HEAD request to check content type
        resp = client.fetch_text(url)
        if not resp.ok:
            errors.append(f"direct_url: {resp.error or f'HTTP {resp.status_code}'}")
            return ProviderResult(self.source_name, matches, errors)

        matches.append(
            MatchedSource(
                source=self.source_name,
                url=url,
                match_confidence=1.0,
                match_basis=("explicit_url",),
                auto_downloaded=True,
                file_type_hint=_guess_file_type(url),
                description=f"Direct URL: {url.rsplit('/', 1)[-1]}",
            )
        )

        return ProviderResult(self.source_name, matches, errors)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXT_MAP = {
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".csv": "csv",
    ".tsv": "tsv",
    ".zip": "zip",
    ".gz": "zip",
    ".tar": "zip",
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "docx",
}


def _guess_file_type(url_or_name: str) -> str | None:
    """Guess file type from URL or filename extension."""
    lower = url_or_name.lower().split("?")[0].split("#")[0]
    for ext, ftype in _EXT_MAP.items():
        if lower.endswith(ext):
            return ftype
    return None


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

ALL_PROVIDERS: list[BaseProvider] = [
    ZenodoProvider(),
    FigshareProvider(),
    DryadProvider(),
    NatureESMProvider(),
    EuropePMCProvider(),
    DirectURLProvider(),
]
