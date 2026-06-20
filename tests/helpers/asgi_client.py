from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4


@dataclass
class ASGIResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class LocalASGITestClient:
    """Tiny synchronous ASGI client for tests.

    Starlette's sync TestClient currently depends on an anyio thread bridge that
    hangs in this environment. This client drives the ASGI app directly on the
    current thread and implements only the subset these tests need.
    """

    __test__ = False

    def __init__(self, app: Any, *, raise_server_exceptions: bool = True) -> None:
        self.app = app
        self.raise_server_exceptions = raise_server_exceptions
        self.cookies: dict[str, str] = {}

    def get(self, path: str, *, headers: dict[str, str] | None = None) -> ASGIResponse:
        return self.request("GET", path, headers=headers)

    def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ASGIResponse:
        body = b""
        next_headers = dict(headers or {})
        if files is not None:
            body, content_type = self._multipart_body(files, data or {})
            next_headers.setdefault("content-type", content_type)
        elif json is not None:
            body = self._json_body(json)
            next_headers.setdefault("content-type", "application/json")
        return self.request("POST", path, body=body, headers=next_headers)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> ASGIResponse:
        return asyncio.run(
            self._request(method, path, body=body, headers=headers or {})
        )

    async def _request(
        self, method: str, path: str, *, body: bytes, headers: dict[str, str]
    ) -> ASGIResponse:
        parsed = urlsplit(path)
        sent_request = False
        messages: list[dict[str, Any]] = []
        scope_headers = self._headers(headers)

        async def receive() -> dict[str, Any]:
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": parsed.path or "/",
            "raw_path": (parsed.path or "/").encode("ascii"),
            "query_string": parsed.query.encode("ascii"),
            "headers": scope_headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
            "state": {},
        }

        try:
            await self.app(scope, receive, send)
        except Exception:
            if self.raise_server_exceptions:
                raise
            return ASGIResponse(status_code=500, content=b"", headers={})

        status = 500
        response_headers: dict[str, str] = {}
        chunks: list[bytes] = []
        for message in messages:
            if message["type"] == "http.response.start":
                status = int(message["status"])
                response_headers = {
                    key.decode("latin1").lower(): value.decode("latin1")
                    for key, value in message.get("headers", [])
                }
                self._store_cookies(response_headers)
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
        return ASGIResponse(
            status_code=status, content=b"".join(chunks), headers=response_headers
        )

    def _headers(self, headers: dict[str, str]) -> list[tuple[bytes, bytes]]:
        merged = {"host": "testserver", **headers}
        if self.cookies and "cookie" not in {key.lower() for key in merged}:
            merged["cookie"] = "; ".join(
                f"{key}={value}" for key, value in self.cookies.items()
            )
        return [
            (key.lower().encode("latin1"), value.encode("latin1"))
            for key, value in merged.items()
        ]

    def _store_cookies(self, headers: dict[str, str]) -> None:
        set_cookie = headers.get("set-cookie")
        if not set_cookie:
            return
        cookie = SimpleCookie()
        cookie.load(set_cookie)
        for key, morsel in cookie.items():
            self.cookies[key] = morsel.value

    @staticmethod
    def _json_body(value: Any) -> bytes:
        return json.dumps(value, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _multipart_body(
        files: dict[str, tuple[str, bytes, str]],
        fields: dict[str, str],
    ) -> tuple[bytes, str]:
        boundary = f"----veritas-test-{uuid4().hex}"
        chunks: list[bytes] = []
        for field_name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("ascii"),
                    f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'.encode(
                        "utf-8"
                    ),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )
        for field_name, (filename, content, content_type) in files.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("ascii"),
                    (
                        f'Content-Disposition: form-data; name="{field_name}"; '
                        f'filename="{filename}"\r\n'
                    ).encode("utf-8"),
                    f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
                    content,
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode("ascii"))
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
