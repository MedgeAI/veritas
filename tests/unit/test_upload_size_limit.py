"""Tests for 200MB upload size limit on the input upload endpoint.

Verifies that:
- Multipart uploads exceeding the limit are rejected with HTTP 413.
- Base64 (JSON) uploads whose decoded size exceeds the limit are rejected with HTTP 413.
- Plain content (JSON) uploads exceeding the limit are rejected with HTTP 413.
- Uploads at or below the limit succeed.

To avoid allocating 200MB in tests, the limit is monkey-patched to a small
value via the MAX_UPLOAD_SIZE_BYTES module attribute.
"""

from __future__ import annotations

import base64

import pytest

from tests.helpers.asgi_client import LocalASGITestClient as TestClient
from web.backend.veritas_web.app import create_app
from web.backend.veritas_web.routers import cases as cases_router


@pytest.fixture
def app_and_client(tmp_path, monkeypatch):
    """Create app + client with a patched upload limit for testable size checks."""
    # Patch the limit to 100 bytes so we can test rejection without allocating 200MB.
    monkeypatch.setattr(cases_router, "MAX_UPLOAD_SIZE_BYTES", 100)
    app = create_app(
        data_root=tmp_path / "web_data", output_root=tmp_path / "outputs"
    )
    client = TestClient(app, raise_server_exceptions=False)
    # Create a case to upload into.
    resp = client.post(
        "/api/cases", json={"case_id": "size-case", "paper_title": "Size"}
    )
    assert resp.status_code == 201
    return app, client


# -- Multipart upload size limit -----------------------------------------------


def test_multipart_upload_rejects_oversized_file(app_and_client):
    """Multipart upload exceeding the limit returns HTTP 413."""
    _, client = app_and_client
    oversized = b"x" * 101  # 101 bytes > patched limit of 100
    resp = client.post(
        "/api/cases/size-case/inputs",
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )
    assert resp.status_code == 413
    assert "200MB" in resp.json()["detail"]


def test_multipart_upload_accepts_file_at_limit(app_and_client):
    """Multipart upload exactly at the limit succeeds."""
    _, client = app_and_client
    at_limit = b"y" * 100  # exactly 100 bytes = patched limit
    resp = client.post(
        "/api/cases/size-case/inputs",
        files={"file": ("ok.pdf", at_limit, "application/pdf")},
    )
    assert resp.status_code == 200


def test_multipart_upload_accepts_small_file(app_and_client):
    """Multipart upload well below the limit succeeds."""
    _, client = app_and_client
    resp = client.post(
        "/api/cases/size-case/inputs",
        files={"file": ("small.pdf", b"small", "application/pdf")},
    )
    assert resp.status_code == 200


# -- Base64 (JSON) upload size limit -------------------------------------------


def test_base64_upload_rejects_oversized_content(app_and_client):
    """Base64 upload whose decoded size exceeds the limit returns HTTP 413."""
    _, client = app_and_client
    # Create bytes that will exceed the 100-byte patched limit after decoding.
    raw = b"z" * 101
    b64 = base64.b64encode(raw).decode("ascii")
    resp = client.post(
        "/api/cases/size-case/inputs",
        json={"filename": "big.pdf", "content_base64": b64},
    )
    assert resp.status_code == 413
    assert "200MB" in resp.json()["detail"]


def test_base64_upload_accepts_content_at_limit(app_and_client):
    """Base64 upload whose estimated decoded size is at the limit succeeds.

    The size estimate ``len(b64) * 3 // 4`` is exact when the raw byte count
    is a multiple of 3 (no base64 padding).  75 bytes → 100 base64 chars →
    estimate = 100 * 3 // 4 = 75, which equals the patched limit.
    """
    _, client = app_and_client
    raw = b"w" * 75
    b64 = base64.b64encode(raw).decode("ascii")
    assert len(b64) * 3 // 4 == 75  # estimate == patched limit
    resp = client.post(
        "/api/cases/size-case/inputs",
        json={"filename": "ok.pdf", "content_base64": b64},
    )
    assert resp.status_code == 200


def test_base64_upload_accepts_small_content(app_and_client):
    """Base64 upload well below the limit succeeds."""
    _, client = app_and_client
    b64 = base64.b64encode(b"small").decode("ascii")
    resp = client.post(
        "/api/cases/size-case/inputs",
        json={"filename": "small.pdf", "content_base64": b64},
    )
    assert resp.status_code == 200


# -- Plain content (JSON) upload size limit ------------------------------------


def test_plain_content_upload_rejects_oversized_content(app_and_client):
    """Plain text content upload exceeding the limit returns HTTP 413."""
    _, client = app_and_client
    oversized = "x" * 101  # 101 ASCII chars = 101 bytes UTF-8 > patched limit
    resp = client.post(
        "/api/cases/size-case/inputs",
        json={"filename": "big.txt", "content": oversized},
    )
    assert resp.status_code == 413
    assert "200MB" in resp.json()["detail"]


def test_plain_content_upload_accepts_at_limit(app_and_client):
    """Plain text content upload exactly at the limit succeeds."""
    _, client = app_and_client
    at_limit = "y" * 100
    resp = client.post(
        "/api/cases/size-case/inputs",
        json={"filename": "ok.txt", "content": at_limit},
    )
    assert resp.status_code == 200
