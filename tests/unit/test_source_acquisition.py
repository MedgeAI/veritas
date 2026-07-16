"""Tests for public source data acquisition (WP5).

Covers:
- Manifest data model serialisation round-trip
- Each provider with mock HTTP responses (no real network)
- Fetcher orchestration: search, download, sha256, status transitions
- Weak match -> manual_confirmation_required enforcement
- no_data_found -> no_data_found_reason (never silent)
- Tool Registry registration
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from engine.static_audit.source_acquisition.manifest import (
    AcquisitionQuery,
    DownloadedFile,
    MatchedSource,
    SourceAcquisitionManifest,
    WEAK_MATCH_THRESHOLD,
)
from engine.static_audit.source_acquisition.providers import (
    DirectURLProvider,
    DryadProvider,
    EuropePMCProvider,
    FigshareProvider,
    NatureESMProvider,
    ZenodoProvider,
)
from engine.static_audit.source_acquisition.fetcher import (
    fetch_public_source_data,
)
from runtime.http_fetch import FetchResult

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "source_acquisition"


# ---------------------------------------------------------------------------
# Mock FetchClient — replaces runtime.http_fetch with fixture-backed stubs
# ---------------------------------------------------------------------------


class MockFetchClient:
    """In-memory FetchClient for testing.

    Maps URL patterns to fixture files or pre-built FetchResult objects.
    """

    def __init__(self) -> None:
        self._json_responses: dict[str, str] = {}
        self._text_responses: dict[str, str] = {}
        self._download_responses: dict[str, bytes] = {}
        self.downloads: list[tuple[str, Path]] = []

    def register_json(self, url_pattern: str, body: str) -> None:
        self._json_responses[url_pattern] = body

    def register_text(self, url_pattern: str, body: str) -> None:
        self._text_responses[url_pattern] = body

    def register_download(self, url_pattern: str, content: bytes) -> None:
        self._download_responses[url_pattern] = content

    def _find(self, url: str, store: dict[str, Any]) -> Any | None:
        for pattern, value in store.items():
            if pattern in url:
                return value
        return None

    def fetch_json(self, url: str) -> FetchResult:
        body = self._find(url, self._json_responses)
        if body is None:
            return FetchResult(url=url, status_code=404, content_type=None, error="HTTP 404: not found in mock")
        return FetchResult(
            url=url, status_code=200, content_type="application/json",
            sha256="mock_sha256", size_bytes=len(body), text_body=body,
        )

    def fetch_text(self, url: str) -> FetchResult:
        body = self._find(url, self._text_responses)
        if body is None:
            # Fallback to JSON responses (many APIs return JSON as text)
            body = self._find(url, self._json_responses)
        if body is None:
            return FetchResult(url=url, status_code=404, content_type=None, error="HTTP 404: not found in mock")
        return FetchResult(
            url=url, status_code=200, content_type="text/html",
            sha256="mock_sha256", size_bytes=len(body), text_body=body,
        )

    def download(self, url: str, dest: str | Path) -> FetchResult:
        dest = Path(dest)
        self.downloads.append((url, dest))
        content = self._find(url, self._download_responses)
        if content is None:
            # Generate dummy content
            content = b"mock_file_content_" + url.encode()[:50]
        import hashlib
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return FetchResult(
            url=url, status_code=200, content_type="application/octet-stream",
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content), dest_path=dest,
        )


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


# ===================================================================
# Manifest model tests
# ===================================================================


class TestAcquisitionQuery:
    def test_primary_key_doi(self):
        q = AcquisitionQuery(doi="10.5281/zenodo.123")
        assert q.primary_key() == "doi:10.5281/zenodo.123"

    def test_primary_key_url(self):
        q = AcquisitionQuery(url="https://example.com/data.xlsx")
        assert q.primary_key() == "url:https://example.com/data.xlsx"

    def test_primary_key_title(self):
        q = AcquisitionQuery(title="Some Paper")
        assert q.primary_key() == "title:Some Paper"

    def test_primary_key_empty(self):
        q = AcquisitionQuery()
        assert q.primary_key() == "empty"

    def test_doi_takes_priority_over_url(self):
        q = AcquisitionQuery(doi="10.1234/test", url="https://example.com")
        assert q.primary_key() == "doi:10.1234/test"


class TestMatchedSource:
    def test_weak_match_forces_manual_confirmation(self):
        m = MatchedSource(
            source="zenodo",
            url="https://example.com/file.xlsx",
            match_confidence=0.5,
            match_basis=("title_fuzzy",),
            auto_downloaded=False,
        )
        assert m.manual_confirmation_required is True

    def test_strong_match_no_manual_confirmation(self):
        m = MatchedSource(
            source="zenodo",
            url="https://example.com/file.xlsx",
            match_confidence=0.95,
            match_basis=("doi_exact",),
            auto_downloaded=True,
        )
        assert m.manual_confirmation_required is False

    def test_confidence_clamped_to_0_1(self):
        m = MatchedSource(
            source="zenodo",
            url="https://example.com",
            match_confidence=1.5,
            match_basis=("test",),
            auto_downloaded=True,
        )
        assert m.match_confidence == 1.0

    def test_explicit_manual_confirmation_preserved(self):
        m = MatchedSource(
            source="zenodo",
            url="https://example.com",
            match_confidence=0.95,
            match_basis=("test",),
            auto_downloaded=True,
            manual_confirmation_required=True,
        )
        assert m.manual_confirmation_required is True


class TestSourceAcquisitionManifest:
    def test_round_trip_serialisation(self, tmp_path):
        manifest = SourceAcquisitionManifest(
            query=AcquisitionQuery(doi="10.5281/zenodo.123"),
            status="downloaded",
            matched_sources=[
                MatchedSource(
                    source="zenodo",
                    url="https://zenodo.org/api/files/abc/test.xlsx",
                    match_confidence=1.0,
                    match_basis=("doi_exact",),
                    auto_downloaded=True,
                ),
            ],
            downloaded_files=[
                DownloadedFile(
                    path="source_data/test.xlsx",
                    sha256="abcdef1234567890",
                    size_bytes=1234,
                    source_url="https://zenodo.org/api/files/abc/test.xlsx",
                    source="zenodo",
                ),
            ],
        )
        path = tmp_path / "manifest.json"
        manifest.write(path)

        loaded = SourceAcquisitionManifest.read(path)
        assert loaded.status == "downloaded"
        assert len(loaded.matched_sources) == 1
        assert loaded.matched_sources[0].source == "zenodo"
        assert len(loaded.downloaded_files) == 1
        assert loaded.downloaded_files[0].sha256 == "abcdef1234567890"

    def test_no_data_found_has_reason(self):
        manifest = SourceAcquisitionManifest(
            query=AcquisitionQuery(doi="10.1234/nothing"),
            status="no_data_found",
            no_data_found_reason="Public source data not found for doi:10.1234/nothing.",
        )
        assert manifest.no_data_found_reason is not None
        assert "not" in manifest.no_data_found_reason.lower()

    def test_note_always_present(self):
        m = SourceAcquisitionManifest()
        assert "does NOT mean the paper is clean" in m.note


# ===================================================================
# Provider tests — all use MockFetchClient, no real HTTP
# ===================================================================


class TestZenodoProvider:
    def test_doi_match_returns_files(self):
        client = MockFetchClient()
        client.register_json("zenodo.org/api/records/1234567", _load_fixture("zenodo_record.json"))

        provider = ZenodoProvider()
        result = provider.search(
            AcquisitionQuery(doi="10.5281/zenodo.1234567"), client
        )
        assert len(result.matches) == 2
        assert result.matches[0].source == "zenodo"
        assert result.matches[0].match_confidence == 1.0
        assert result.matches[0].auto_downloaded is True
        assert result.matches[0].file_type_hint == "xlsx"

    def test_non_zenodo_doi_returns_empty(self):
        client = MockFetchClient()
        provider = ZenodoProvider()
        result = provider.search(AcquisitionQuery(doi="10.1038/something"), client)
        assert len(result.matches) == 0

    def test_no_doi_returns_empty(self):
        client = MockFetchClient()
        provider = ZenodoProvider()
        result = provider.search(AcquisitionQuery(title="something"), client)
        assert len(result.matches) == 0

    def test_api_error_recorded(self):
        client = MockFetchClient()
        # No fixture registered — will return 404
        provider = ZenodoProvider()
        result = provider.search(
            AcquisitionQuery(doi="10.5281/zenodo.9999999"), client
        )
        assert len(result.matches) == 0
        assert len(result.errors) > 0


class TestFigshareProvider:
    def test_figshare_doi_returns_files(self):
        client = MockFetchClient()
        client.register_json("api.figshare.com/v2/articles/9876543", _load_fixture("figshare_article.json"))

        provider = FigshareProvider()
        result = provider.search(
            AcquisitionQuery(doi="10.6084/m9.figshare.9876543"), client
        )
        assert len(result.matches) == 1
        assert result.matches[0].source == "figshare"
        assert result.matches[0].file_type_hint == "xlsx"

    def test_non_figshare_doi_skipped(self):
        client = MockFetchClient()
        provider = FigshareProvider()
        result = provider.search(AcquisitionQuery(doi="10.1038/test"), client)
        assert len(result.matches) == 0


class TestDryadProvider:
    def test_dryad_doi_returns_files(self):
        client = MockFetchClient()
        client.register_json("datadryad.org/api/v2/datasets", _load_fixture("dryad_dataset.json"))

        provider = DryadProvider()
        result = provider.search(
            AcquisitionQuery(doi="10.5061/dryad.abc123"), client
        )
        assert len(result.matches) == 1
        assert result.matches[0].source == "dryad"

    def test_non_dryad_doi_skipped(self):
        client = MockFetchClient()
        provider = DryadProvider()
        result = provider.search(AcquisitionQuery(doi="10.5281/zenodo.123"), client)
        assert len(result.matches) == 0


class TestNatureESMProvider:
    def test_nature_doi_extracts_esm_links(self):
        client = MockFetchClient()
        client.register_text("nature.com/articles/s41558", _load_fixture("nature_article.html"))
        # Also need to handle doi.org redirect
        client.register_text("doi.org/10.1038", _load_fixture("nature_article.html"))

        provider = NatureESMProvider()
        result = provider.search(
            AcquisitionQuery(doi="10.1038/s41558-024-01234-x"), client
        )
        assert len(result.matches) >= 1
        esm_matches = [m for m in result.matches if "esm" in m.url.lower() or "supplementary" in m.url.lower()]
        assert len(esm_matches) >= 1

    def test_non_nature_doi_skipped(self):
        client = MockFetchClient()
        provider = NatureESMProvider()
        result = provider.search(AcquisitionQuery(doi="10.5281/zenodo.123"), client)
        assert len(result.matches) == 0


class TestEuropePMCProvider:
    def test_pmcid_found_returns_match(self):
        client = MockFetchClient()
        client.register_json("ebi.ac.uk/europepmc/webservices/rest/search", _load_fixture("europe_pmc_search.json"))
        # Supplementary files endpoint
        client.register_text("supplementaryFiles", "file1.xlsx\nfile2.csv")

        provider = EuropePMCProvider()
        result = provider.search(
            AcquisitionQuery(doi="10.1038/s41558-024-01234-x"), client
        )
        assert len(result.matches) >= 1
        assert result.matches[0].source == "europe_pmc"

    def test_no_pmcid_returns_error(self):
        client = MockFetchClient()
        no_pmcid_resp = json.dumps({"resultList": {"result": [{"pmid": "123", "doi": "10.1234/test"}]}})
        client.register_json("ebi.ac.uk/europepmc/webservices/rest/search", no_pmcid_resp)

        provider = EuropePMCProvider()
        result = provider.search(AcquisitionQuery(doi="10.1234/test"), client)
        assert len(result.matches) == 0
        assert any("PMCID" in e for e in result.errors)


class TestDirectURLProvider:
    def test_direct_url_returns_match(self):
        client = MockFetchClient()
        client.register_text("example.com/data.xlsx", "fake xlsx content")

        provider = DirectURLProvider()
        result = provider.search(
            AcquisitionQuery(url="https://example.com/data.xlsx"), client
        )
        assert len(result.matches) == 1
        assert result.matches[0].source == "direct_url"
        assert result.matches[0].match_confidence == 1.0

    def test_no_url_skipped(self):
        client = MockFetchClient()
        provider = DirectURLProvider()
        result = provider.search(AcquisitionQuery(doi="10.1234/test"), client)
        assert len(result.matches) == 0


# ===================================================================
# Fetcher orchestration tests
# ===================================================================


class TestFetcherOrchestration:
    def test_zenodo_download_produces_manifest(self, tmp_path):
        """Full round-trip: Zenodo DOI -> search -> download -> manifest."""
        client = MockFetchClient()
        client.register_json("zenodo.org/api/records/1234567", _load_fixture("zenodo_record.json"))
        client.register_download("zenodo.org/api/files", b"fake xlsx bytes")

        manifest = fetch_public_source_data(
            query=AcquisitionQuery(doi="10.5281/zenodo.1234567"),
            output_dir=tmp_path,
            client=client,
            providers=[ZenodoProvider()],
        )
        assert manifest.status == "downloaded"
        assert len(manifest.downloaded_files) == 2
        assert all(f.sha256 for f in manifest.downloaded_files)
        assert all(f.size_bytes > 0 for f in manifest.downloaded_files)
        # Manifest file written
        assert (tmp_path / "source_acquisition_manifest.json").exists()

    def test_no_data_found_sets_reason(self, tmp_path):
        """When no provider finds anything, no_data_found_reason must be set."""
        client = MockFetchClient()
        # All providers will get 404
        manifest = fetch_public_source_data(
            query=AcquisitionQuery(doi="10.9999/nonexistent"),
            output_dir=tmp_path,
            client=client,
            providers=[ZenodoProvider(), FigshareProvider()],
        )
        assert manifest.status == "no_data_found"
        assert manifest.no_data_found_reason is not None
        assert "not found" in manifest.no_data_found_reason.lower() or "not" in manifest.no_data_found_reason.lower()

    def test_weak_match_not_auto_downloaded(self, tmp_path):
        """Weak matches require manual confirmation and are not downloaded."""
        client = MockFetchClient()
        # Create a provider that returns a weak match
        from engine.static_audit.source_acquisition.providers import BaseProvider, ProviderResult

        class WeakMatchProvider(BaseProvider):
            source_name = "test_weak"

            def search(self, query, client):
                return ProviderResult(
                    "test_weak",
                    [MatchedSource(
                        source="test_weak",
                        url="https://example.com/weak_match.xlsx",
                        match_confidence=0.3,
                        match_basis=("title_fuzzy",),
                        auto_downloaded=False,
                        manual_confirmation_required=True,
                    )],
                    [],
                )

        manifest = fetch_public_source_data(
            query=AcquisitionQuery(title="vague title"),
            output_dir=tmp_path,
            client=client,
            providers=[WeakMatchProvider()],
        )
        assert manifest.status == "needs_confirmation"
        assert len(manifest.downloaded_files) == 0
        assert len(manifest.matched_sources) == 1
        assert manifest.matched_sources[0].manual_confirmation_required is True

    def test_fetch_errors_recorded_not_silent(self, tmp_path):
        """Provider errors are recorded in fetch_errors, never silent."""
        client = MockFetchClient()
        # No fixtures registered — all calls will fail
        manifest = fetch_public_source_data(
            query=AcquisitionQuery(doi="10.5281/zenodo.0000000"),
            output_dir=tmp_path,
            client=client,
            providers=[ZenodoProvider()],
        )
        assert len(manifest.fetch_errors) > 0
        assert manifest.status == "no_data_found"
        assert manifest.no_data_found_reason is not None

    def test_download_failure_recorded(self, tmp_path):
        """If download fails, the error is in fetch_errors."""
        client = MockFetchClient()
        client.register_json("zenodo.org/api/records/1234567", _load_fixture("zenodo_record.json"))
        # Make download fail by not registering a download response AND
        # making the client return an error for download
        original_download = client.download

        def failing_download(url, dest):
            return FetchResult(url=url, status_code=500, content_type=None, error="HTTP 500: server error")

        client.download = failing_download

        manifest = fetch_public_source_data(
            query=AcquisitionQuery(doi="10.5281/zenodo.1234567"),
            output_dir=tmp_path,
            client=client,
            providers=[ZenodoProvider()],
        )
        assert len(manifest.fetch_errors) > 0
        assert any("download failed" in e for e in manifest.fetch_errors)

    def test_mixed_providers(self, tmp_path):
        """Multiple providers can contribute matches."""
        client = MockFetchClient()
        client.register_json("zenodo.org/api/records/1234567", _load_fixture("zenodo_record.json"))
        client.register_json("api.figshare.com/v2/articles/9876543", _load_fixture("figshare_article.json"))
        client.register_download("zenodo.org", b"zenodo_bytes")
        client.register_download("figshare", b"figshare_bytes")

        manifest = fetch_public_source_data(
            query=AcquisitionQuery(doi="10.5281/zenodo.1234567"),
            output_dir=tmp_path,
            client=client,
            providers=[ZenodoProvider(), FigshareProvider()],
        )
        # Zenodo should find matches; Figshare won't (wrong DOI pattern)
        assert manifest.status == "downloaded"
        assert len(manifest.matched_sources) >= 2

    def test_manifest_written_to_disk(self, tmp_path):
        """Manifest is always written, even on failure."""
        client = MockFetchClient()
        fetch_public_source_data(
            query=AcquisitionQuery(doi="10.9999/nothing"),
            output_dir=tmp_path,
            client=client,
            providers=[ZenodoProvider()],
        )
        manifest_path = tmp_path / "source_acquisition_manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["schema_version"] == "1.0"
        assert data["status"] == "no_data_found"


# ===================================================================
# Tool Registry tests
# ===================================================================


class TestToolRegistry:
    def test_fetch_public_registered(self):
        from engine.tools.registry import TOOLS, SOURCE_DATA_FETCH_PUBLIC_TOOL_ID
        assert SOURCE_DATA_FETCH_PUBLIC_TOOL_ID in TOOLS
        tool = TOOLS[SOURCE_DATA_FETCH_PUBLIC_TOOL_ID]
        assert tool.tool_id == "source_data.fetch_public"
        assert tool.step_key == "source_data_fetch_public"

    def test_fetch_public_has_param_schema(self):
        from engine.tools.registry import TOOLS, SOURCE_DATA_FETCH_PUBLIC_TOOL_ID
        tool = TOOLS[SOURCE_DATA_FETCH_PUBLIC_TOOL_ID]
        assert "doi" in tool.param_schema
        assert "title" in tool.param_schema
        assert "url" in tool.param_schema

    def test_fetch_public_output_artifact(self):
        from engine.tools.registry import TOOLS, SOURCE_DATA_FETCH_PUBLIC_TOOL_ID
        tool = TOOLS[SOURCE_DATA_FETCH_PUBLIC_TOOL_ID]
        assert "source_acquisition_manifest.json" in tool.output_artifacts


# ===================================================================
# Runtime http_fetch tests (with mocked urllib)
# ===================================================================


class TestRuntimeHttpFetch:
    def test_fetch_result_ok(self):
        r = FetchResult(url="https://example.com", status_code=200, content_type="text/plain")
        assert r.ok is True

    def test_fetch_result_not_ok_404(self):
        r = FetchResult(url="https://example.com", status_code=404, content_type=None, error="Not found")
        assert r.ok is False

    def test_fetch_result_not_ok_no_status(self):
        r = FetchResult(url="https://example.com", status_code=None, content_type=None, error="Connection refused")
        assert r.ok is False

    def test_fetch_text_mocked(self):
        """Test fetch_text with mocked urllib.request.urlopen."""
        from io import BytesIO
        from unittest.mock import MagicMock
        from runtime.http_fetch import fetch_text

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_response.read.return_value = b"<html>test</html>"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("runtime.http_fetch.urllib.request.urlopen", return_value=mock_response):
            result = fetch_text("https://example.com")

        assert result.ok
        assert result.text_body == "<html>test</html>"
        assert result.sha256 is not None

    def test_fetch_to_file_mocked(self, tmp_path):
        """Test fetch_to_file with mocked urllib."""
        from unittest.mock import MagicMock
        from runtime.http_fetch import fetch_to_file

        content = b"file content here"
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {"Content-Type": "application/octet-stream"}
        # Simulate chunked reading
        read_calls = [content, b""]
        mock_response.read.side_effect = read_calls
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        dest = tmp_path / "test_file.xlsx"
        with patch("runtime.http_fetch.urllib.request.urlopen", return_value=mock_response):
            result = fetch_to_file("https://example.com/file.xlsx", dest)

        assert result.ok
        assert result.dest_path == dest
        assert result.sha256 is not None
        assert result.size_bytes == len(content)
        assert dest.exists()
        assert dest.read_bytes() == content

    def test_fetch_to_file_http_error(self, tmp_path):
        """HTTP errors are captured, not raised."""
        import urllib.error
        from runtime.http_fetch import fetch_to_file

        dest = tmp_path / "test.xlsx"
        error = urllib.error.HTTPError(
            "https://example.com", 404, "Not Found", {}, None
        )
        with patch("runtime.http_fetch.urllib.request.urlopen", side_effect=error):
            result = fetch_to_file("https://example.com/file.xlsx", dest)

        assert not result.ok
        assert result.status_code == 404
        assert "404" in (result.error or "")
        assert not dest.exists()

    def test_fetch_to_file_connection_error(self, tmp_path):
        """Connection errors are captured, not raised."""
        import urllib.error
        from runtime.http_fetch import fetch_to_file

        dest = tmp_path / "test.xlsx"
        error = urllib.error.URLError("Connection refused")
        with patch("runtime.http_fetch.urllib.request.urlopen", side_effect=error):
            result = fetch_to_file("https://example.com/file.xlsx", dest)

        assert not result.ok
        assert result.status_code is None
        assert not dest.exists()


# ===================================================================
# Integration: tool entry point
# ===================================================================


class TestSourceDataFetchTool:
    def test_tool_entry_point_exists(self):
        from engine.tools.source_data_fetch import run_source_data_fetch
        assert callable(run_source_data_fetch)
