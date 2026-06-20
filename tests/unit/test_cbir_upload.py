"""Tests for CBIR image upload search endpoint."""

from __future__ import annotations

import io


from tests.helpers.asgi_client import LocalASGITestClient as TestClient
from web.backend.veritas_web.app import create_app


def _make_test_image(color: str = "red") -> io.BytesIO:
    """Create a simple test image."""
    from PIL import Image

    img = Image.new("RGB", (100, 100), color=color)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return img_bytes


def test_upload_search_invalid_file_type() -> None:
    """Test that invalid file types are rejected."""
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/cbir/search/upload",
        files={"file": ("test.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 400
    data = response.json()
    assert "invalid_file_type" in str(data)


def test_upload_search_missing_file() -> None:
    """Test that missing file parameter returns 422."""
    app = create_app()
    client = TestClient(app)

    response = client.post("/api/cbir/search/upload")

    assert response.status_code == 422


def test_upload_search_endpoint_exists() -> None:
    """Test that the upload endpoint exists and accepts valid image files."""
    app = create_app()
    client = TestClient(app)

    img_bytes = _make_test_image("red")
    response = client.post(
        "/api/cbir/search/upload",
        files={"file": ("test.png", img_bytes.getvalue(), "image/png")},
    )

    # Should return either 200 (success) or 503 (SSCD model not available)
    # Both are valid responses indicating the endpoint exists
    assert response.status_code in {200, 503}

    if response.status_code == 200:
        data = response.json()
        assert data["query_panel_id"] == "uploaded_image"
        assert "similar_panels" in data
