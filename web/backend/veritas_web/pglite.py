"""PGlite socket server support for local development and tests."""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PGliteServer:
    process: subprocess.Popen[bytes]
    host: str
    port: int
    database_url: str

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


_DEFAULT_SERVER: PGliteServer | None = None


def get_or_start_pglite_server() -> PGliteServer:
    """Return a process-wide in-memory PGlite PostgreSQL socket server."""
    global _DEFAULT_SERVER
    if _DEFAULT_SERVER is not None and _DEFAULT_SERVER.process.poll() is None:
        return _DEFAULT_SERVER
    _DEFAULT_SERVER = start_pglite_server()
    atexit.register(_DEFAULT_SERVER.stop)
    return _DEFAULT_SERVER


def start_pglite_server(
    *, host: str = "127.0.0.1", port: int | None = None, max_connections: int = 16
) -> PGliteServer:
    port = port or _free_port(host)
    command = _pglite_command()
    cmd = [
        *command,
        "--db=memory://",
        f"--host={host}",
        f"--port={port}",
        f"--max-connections={max_connections}",
    ]
    database_url = f"postgresql://postgres:postgres@{host}:{port}/postgres?sslmode=disable"
    env = os.environ.copy()
    env.setdefault("PGSSLMODE", "disable")
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        _wait_for_postgres(database_url, process)
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        raise
    return PGliteServer(process=process, host=host, port=port, database_url=database_url)


def _pglite_command() -> list[str]:
    configured = os.environ.get("VERITAS_PGLITE_SERVER_BIN")
    if configured:
        return [configured]

    repo_root = Path(__file__).resolve().parents[3]
    local_bin = repo_root / "web" / "frontend" / "node_modules" / ".bin" / "pglite-server"
    if local_bin.exists():
        return [str(local_bin)]

    global_bin = shutil.which("pglite-server")
    if global_bin:
        return [global_bin]

    npx = shutil.which("npx")
    if npx:
        return [npx, "--no-install", "pglite-server"]

    raise RuntimeError(
        "PGlite server is not available. Run `make web-install` or install "
        "`@electric-sql/pglite-socket` so `pglite-server` is on PATH."
    )


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_for_postgres(
    database_url: str,
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"pglite-server exited with code {process.returncode}")
        try:
            import psycopg2

            conn = psycopg2.connect(database_url, connect_timeout=1)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("select 1")
                    cursor.fetchone()
                return
            finally:
                conn.close()
        except Exception as exc:
            last_error = exc
            time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for pglite-server: {last_error}")
