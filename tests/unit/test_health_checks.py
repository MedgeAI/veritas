from __future__ import annotations

from pathlib import Path

from web.backend.veritas_web.app import _http_service_health, _opencode_data_dir_health


def test_opencode_data_dir_health_accepts_writable_target(tmp_path: Path) -> None:
    target = tmp_path / "web_data" / ".opencode" / "data"
    target.mkdir(parents=True)
    opencode_dir = tmp_path / ".opencode"
    opencode_dir.mkdir()
    (opencode_dir / "data").symlink_to(target, target_is_directory=True)

    ok, check = _opencode_data_dir_health(tmp_path)

    assert ok is True
    assert check["ok"] is True
    assert check["detail"] == "ok"
    assert check["resolved_path"] == str(target)


def test_opencode_data_dir_health_reports_broken_symlink(tmp_path: Path) -> None:
    target = tmp_path / "web_data" / ".opencode" / "data"
    opencode_dir = tmp_path / ".opencode"
    opencode_dir.mkdir()
    (opencode_dir / "data").symlink_to(target, target_is_directory=True)

    ok, check = _opencode_data_dir_health(tmp_path)

    assert ok is False
    assert check["ok"] is False
    assert check["resolved_path"] == str(target)
    assert "missing symlink target" in check["detail"]


def test_http_service_health_accepts_healthy_response(monkeypatch) -> None:
    import httpx

    class FakeClient:
        def __init__(self, *, timeout: float, trust_env: bool) -> None:
            assert timeout == 3.0
            assert trust_env is False

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, endpoint: str):
            assert endpoint == "http://sila-dense:8770/health"
            return type("Response", (), {"status_code": 200})()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    ok, check = _http_service_health("SILA dense service", "http://sila-dense:8770")

    assert ok is True
    assert check["ok"] is True
    assert check["detail"] == "ok"


def test_http_service_health_reports_unhealthy_response(monkeypatch) -> None:
    import httpx

    class FakeClient:
        def __init__(self, *, timeout: float, trust_env: bool) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, endpoint: str):
            return type("Response", (), {"status_code": 503})()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    ok, check = _http_service_health("ELIS forensic service", "http://elis-forensic:8771")

    assert ok is False
    assert check["ok"] is False
    assert check["status_code"] == 503
