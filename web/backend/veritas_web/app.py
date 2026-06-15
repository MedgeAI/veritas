from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .artifacts import ArtifactService
from .auth import AuthContext, AuthProvider, NoAuthProvider
from .case_store import CaseStore
from .config import AuthConfig, create_auth_provider
from .models import CaseRecord
from .runner import AuditRunner


class VeritasWebApp:
    def __init__(
        self,
        data_root: str | Path = "web_data",
        output_root: str | Path = "outputs",
        frontend_dist: str | Path | None = None,
    ) -> None:
        self.store = CaseStore(data_root)
        self.runner = AuditRunner(self.store, output_root=output_root)
        self.recovered_interrupted_runs = self.runner.recover_interrupted_runs()
        self.artifacts = ArtifactService(self.store)
        self.frontend_dist = Path(frontend_dist) if frontend_dist else Path(__file__).resolve().parents[2] / "frontend" / "dist"


class VeritasRequestHandler(BaseHTTPRequestHandler):
    server_version = "VeritasWeb/0.1"
    app: VeritasWebApp
    auth_provider: AuthProvider
    auth_context: AuthContext

    def _authenticate(self) -> bool:
        """Authenticate the current request.

        Populates ``self.auth_context`` on success.  Returns ``True`` when
        the request should proceed, ``False`` when a 401 has been sent.
        """
        if isinstance(self.auth_provider, NoAuthProvider):
            self.auth_context = AuthContext(
                user_id="operator",
                roles=frozenset({"admin"}),
            )
            return True

        ctx = self.auth_provider.authenticate(dict(self.headers))
        if ctx is None:
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self._send_cors_headers()
            challenge = getattr(self.auth_provider, "challenge_headers", None)
            if callable(challenge):
                for key, value in challenge().items():
                    self.send_header(key, value)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        self.auth_context = ctx
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            if not self._authenticate():
                return
            self._route_get()
        except Exception as exc:
            self._send_error(exc)

    def do_POST(self) -> None:  # noqa: N802
        try:
            if not self._authenticate():
                return
            self._route_post()
        except Exception as exc:
            self._send_error(exc)

    def _route_get(self) -> None:
        parts, _query = self._path_parts()
        if parts == ["api", "health"]:
            self._send_json(
                {
                    "status": "ok",
                    "runner_mode": "thread",
                    "recovered_interrupted_runs": self.app.recovered_interrupted_runs,
                }
            )
            return
        if parts == ["api", "cases"]:
            user_id = self.auth_context.user_id
            self._send_json({"cases": [case.to_dict() for case in self.app.store.list_cases(user_id=user_id)]})
            return
        if len(parts) == 3 and parts[:2] == ["api", "cases"]:
            self._send_json(self._require_case_access(parts[2]).to_dict())
            return
        if len(parts) == 5 and parts[:2] == ["api", "cases"] and parts[3] == "runs":
            self._require_case_access(parts[2])
            self._send_json(self.app.store.get_run(parts[2], parts[4]).to_dict())
            return
        if len(parts) == 6 and parts[:2] == ["api", "cases"] and parts[3] == "runs" and parts[5] == "events":
            self._require_case_access(parts[2])
            self._send_json({"events": self.app.store.list_events(parts[2], parts[4])})
            return
        if len(parts) == 4 and parts[:2] == ["api", "cases"] and parts[3] == "artifacts":
            self._require_case_access(parts[2])
            self._send_json({"artifacts": [ref.to_dict() for ref in self.app.artifacts.list_artifacts(parts[2])]})
            return
        if len(parts) == 5 and parts[:2] == ["api", "cases"] and parts[3] == "artifacts":
            self._send_artifact(parts[2], parts[4])
            return
        if len(parts) == 5 and parts[:2] == ["api", "cases"] and parts[3:] == ["report", "html"]:
            self._send_report_html(parts[2])
            return
        if parts and parts[0] == "api":
            raise FileNotFoundError("route not found")
        self._send_frontend_static(parts)
        return

    def _route_post(self) -> None:
        parts, _query = self._path_parts()
        payload = self._read_json()
        if parts == ["api", "cases"]:
            user_id = self.auth_context.user_id
            paper_title = payload.get("paper_title")
            raw_case_id = payload.get("case_id")
            case = self.app.store.create_case(
                user_id=user_id,
                paper_title=paper_title,
                case_id=str(raw_case_id) if raw_case_id else None,
            )
            self._send_json(case.to_dict(), status=HTTPStatus.CREATED)
            return
        if len(parts) == 4 and parts[:2] == ["api", "cases"] and parts[3] == "inputs":
            self._require_case_access(parts[2])
            if "content_base64" in payload:
                path = self.app.store.write_input_base64(parts[2], str(payload.get("filename", "paper.pdf")), str(payload["content_base64"]))
            elif "content" in payload:
                path = self.app.store.write_input(parts[2], str(payload.get("filename", "paper.pdf")), str(payload["content"]).encode("utf-8"))
            else:
                raise ValueError("input upload requires content_base64 or content")
            self._send_json({"path": str(path), "case": self._require_case_access(parts[2]).to_dict()})
            return
        if len(parts) == 4 and parts[:2] == ["api", "cases"] and parts[3] == "runs":
            self._require_case_access(parts[2])
            run = self.app.runner.start(parts[2], payload)
            self._send_json(run.to_dict(), status=HTTPStatus.ACCEPTED)
            return
        raise FileNotFoundError("route not found")

    def _require_case_access(self, case_id: str) -> CaseRecord:
        """Return the case if the authenticated user owns it."""
        return self.app.store.get_case(case_id, user_id=self.auth_context.user_id)

    def _send_artifact(self, case_id: str, artifact_id: str) -> None:
        self._require_case_access(case_id)
        path = self.app.artifacts.artifact_path(case_id, artifact_id)
        if not path:
            raise FileNotFoundError(f"artifact not found: {artifact_id}")
        content_type = "application/json"
        if path.suffix == ".jsonl":
            content_type = "application/x-ndjson"
        elif path.suffix == ".md":
            content_type = "text/markdown; charset=utf-8"
        self._send_bytes(path.read_bytes(), content_type=content_type)

    def _send_report_html(self, case_id: str) -> None:
        self._require_case_access(case_id)
        path = self.app.artifacts.report_html_path(case_id)
        if not path:
            raise FileNotFoundError("final HTML report not found")
        self._send_bytes(path.read_bytes(), content_type="text/html; charset=utf-8")

    def _send_frontend_static(self, parts: list[str]) -> None:
        dist = self.app.frontend_dist
        index_path = dist / "index.html"
        if not index_path.exists():
            raise FileNotFoundError("frontend dist not found; run `npm run build` in web/frontend or use Vite dev server")

        target = index_path
        if parts:
            candidate = (dist / Path(*parts)).resolve()
            dist_resolved = dist.resolve()
            if dist_resolved == candidate or dist_resolved in candidate.parents:
                if candidate.is_file():
                    target = candidate

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type = f"{content_type}; charset=utf-8"
        self._send_bytes(target.read_bytes(), content_type=content_type)

    def _path_parts(self) -> tuple[list[str], dict[str, list[str]]]:
        parsed = urlparse(self.path)
        return [part for part in parsed.path.split("/") if part], parse_qs(parsed.query)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes(
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            status=status,
            content_type="application/json; charset=utf-8",
        )

    def _send_bytes(
        self,
        payload: bytes,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, exc: Exception) -> None:
        if isinstance(exc, PermissionError):
            status = HTTPStatus.FORBIDDEN
        elif isinstance(exc, FileNotFoundError):
            status = HTTPStatus.NOT_FOUND
        else:
            status = HTTPStatus.BAD_REQUEST
        self._send_json({"error": type(exc).__name__, "detail": str(exc)}, status=status)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def log_message(self, format: str, *args: Any) -> None:
        return


def make_handler(app: VeritasWebApp, auth_provider: AuthProvider | None = None) -> type[VeritasRequestHandler]:
    if auth_provider is None:
        auth_provider = create_auth_provider(AuthConfig.from_env())

    class Handler(VeritasRequestHandler):
        pass

    Handler.app = app
    Handler.auth_provider = auth_provider
    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765, data_root: str = "web_data", output_root: str = "outputs") -> None:
    app = VeritasWebApp(data_root=data_root, output_root=output_root)
    auth_provider = create_auth_provider(AuthConfig.from_env())
    server = ThreadingHTTPServer((host, port), make_handler(app, auth_provider=auth_provider))
    auth_mode = "none" if isinstance(auth_provider, NoAuthProvider) else type(auth_provider).__name__
    print(f"Veritas Web backend listening on http://{host}:{port} (auth: {auth_mode})")
    server.serve_forever()


if __name__ == "__main__":
    serve()
