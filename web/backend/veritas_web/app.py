"""FastAPI application for the Veritas web backend.

Replaces the previous stdlib ``ThreadingHTTPServer`` implementation.
All API routes live in ``routers/`` sub-modules; this file wires them
together, sets up CORS, serves the frontend static build, and exposes
the ``serve()`` entry point used by the Makefile.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Load project .env into os.environ BEFORE reading any config variables.
#
# ``load_project_env`` returns a merged dict (shell env + .env file, shell
# wins) but does NOT mutate ``os.environ``.  We inject via ``setdefault``
# so that ``get_env()`` — and any downstream ``os.environ.get()`` — sees
# .env values.  Shell exports still take priority (setdefault won't
# overwrite).
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
from engine.env import get_env, load_project_env  # noqa: E402

for _k, _v in load_project_env(_PROJECT_ROOT).items():
    os.environ.setdefault(_k, _v)

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import logging_config
from .artifacts import ArtifactService
from .auth import AuthContext, AuthProvider, NoAuthProvider
from .case_store import CaseStore
from .config import AuthConfig, create_auth_provider
from .database import create_db_engine, get_database_url
from .dependencies import AppDependencies, get_auth_context, set_dependencies
from .investigations import WebInvestigationService
from .runner import AuditRunner
from .routers import (
    artifacts,
    audit_jobs,
    cases,
    client_report,
    investigations,
    materials,
    metrics,
    review,
    tools,
    users,
    verify,
    visual,
)
from .tool_catalog import seed_tool_registry

logger = logging.getLogger(__name__)


class VeritasWebApp:
    """Kept for backward compat — some modules import this class."""

    def __init__(
        self,
        data_root: str | Path = "web_data",
        output_root: str | Path = "outputs",
        frontend_dist: str | Path | None = None,
        database_url: str | None = None,
    ) -> None:
        self.store = CaseStore(
            data_root, database_url=_resolve_database_url(data_root, database_url)
        )
        self.runner = AuditRunner(self.store, output_root=output_root)
        self.recovered_interrupted_runs = self.runner.recover_interrupted_runs()
        self.artifacts = ArtifactService(self.store, output_root=output_root)
        self.investigations = WebInvestigationService(self.store, self.artifacts)
        self.frontend_dist = (
            Path(frontend_dist)
            if frontend_dist
            else Path(__file__).resolve().parents[2] / "frontend" / "dist"
        )


def create_app(
    data_root: str | Path = "web_data",
    output_root: str | Path = "outputs",
    frontend_dist: str | Path | None = None,
    database_url: str | None = None,
    auth_provider: AuthProvider | None = None,
) -> FastAPI:
    """Build and return the configured FastAPI application."""
    logging_config.configure_logging()
    app = FastAPI(title="Veritas Web P1", version="0.1.0")

    # Log database configuration with redacted credentials
    resolved_database_url = _resolve_database_url(data_root, database_url)
    logger.info(logging_config.redact_dsn(resolved_database_url))
    store = CaseStore(data_root, database_url=resolved_database_url)
    runner = AuditRunner(store, output_root=output_root)
    artifacts_svc = ArtifactService(store, output_root=output_root)
    investigations_svc = WebInvestigationService(store, artifacts_svc)
    auth = auth_provider or create_auth_provider(AuthConfig.from_env())

    # --- Dependency injection -----------------------------------------
    # Use CaseStore's engine if it has one (keeps apps on one connection pool).
    engine = getattr(store, "_engine", None) or (
        create_db_engine() if (database_url or store.sql_mode) else None
    )
    deps = AppDependencies(
        store=store,
        auth_provider=auth,
        engine=engine,
        runner=runner,
        artifacts=artifacts_svc,
        investigations=investigations_svc,
    )
    app.state.dependencies = deps
    set_dependencies(deps)

    if deps._session_factory is not None:
        from .database import check_db_or_raise

        check_db_or_raise(engine)
        session = deps._session_factory()
        try:
            seed_tool_registry(session)
        finally:
            session.close()

    recovered = runner.recover_interrupted_runs()

    # --- Middleware ----------------------------------------------------
    # Request logging — must be added BEFORE CORS so it sees the original request.
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        import time

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        # Skip health checks to reduce noise.
        path = request.url.path
        if path.startswith("/api/health"):
            return response

        # Polling paths (runs/events/artifacts) are too noisy at INFO.
        # Only log at INFO for errors (5xx) or slow requests (>5s).
        if logging_config.is_polling_path(path):
            if (
                response.status_code >= 500
                or duration_ms > logging_config.SLOW_REQUEST_THRESHOLD_MS
            ):
                logger.info(
                    "%s %s -> %d (%.1fms)",
                    request.method,
                    path,
                    response.status_code,
                    duration_ms,
                )
            return response

        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            path,
            response.status_code,
            duration_ms,
        )
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Exception handlers -------------------------------------------
    @app.exception_handler(FileNotFoundError)
    async def handle_not_found(
        request: Request, exc: FileNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"error": "NotFound", "detail": str(exc)}
        )

    @app.exception_handler(PermissionError)
    async def handle_forbidden(request: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse(
            status_code=403, content={"error": "Forbidden", "detail": str(exc)}
        )

    @app.exception_handler(ValueError)
    async def handle_bad_request(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400, content={"error": "BadRequest", "detail": str(exc)}
        )

    # --- Routers -------------------------------------------------------
    app.include_router(cases.router, prefix="/api")
    app.include_router(audit_jobs.router, prefix="/api")
    app.include_router(artifacts.router, prefix="/api")
    app.include_router(investigations.router, prefix="/api")
    app.include_router(visual.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(materials.router, prefix="/api")
    app.include_router(metrics.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(
        verify.router, prefix=""
    )  # verify router already has /api/verify prefix
    app.include_router(client_report.router, prefix="/api")

    # --- Health endpoint -----------------------------------------------
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        runner_mode = (
            "celery"
            if get_env("VERITAS_USE_CELERY", required=False, default="").lower()
            in ("1", "true", "yes")
            else "thread_pool"
        )
        return {
            "status": "ok",
            "runner_mode": runner_mode,
            "recovered_interrupted_runs": recovered,
        }

    @app.get("/api/health/deep")
    async def health_deep() -> dict[str, Any]:
        """Deep health check — verifies audit-critical dependencies exist.

        Used by deploy smoke tests and Docker HEALTHCHECK to catch
        missing third_party scripts or broken imports early.
        """
        import shutil as _shutil
        from engine.static_audit._shared import AUDITOR_ROOT

        checks: dict[str, Any] = {}
        all_ok = True

        # 1. MinerU / evidence_ledger / numeric_forensics scripts
        mineru_scripts = AUDITOR_ROOT / "scripts"
        mineru_ok = (
            mineru_scripts.is_dir() and (mineru_scripts / "mineru_convert.py").exists()
        )
        checks["mineru_scripts"] = {
            "ok": mineru_ok,
            "path": str(mineru_scripts),
            "detail": "ok"
            if mineru_ok
            else "AUDITOR_ROOT scripts directory or mineru_convert.py missing",
        }
        if not mineru_ok:
            all_ok = False

        # 2. opencode binary
        opencode_path = _shutil.which("opencode")
        checks["opencode"] = {
            "ok": opencode_path is not None,
            "path": opencode_path or "not found on PATH",
        }
        if opencode_path is None:
            all_ok = False

        # 3. Data directories writable
        _data = Path(str(data_root) if not isinstance(data_root, Path) else data_root)  # type: ignore[name-defined]
        _out = Path(
            str(output_root) if not isinstance(output_root, Path) else output_root
        )  # type: ignore[name-defined]
        for name, d in [("data_root", _data), ("output_root", _out)]:
            writable = d.exists() and os.access(str(d), os.W_OK)
            checks[name] = {"ok": writable, "path": str(d)}
            if not writable:
                all_ok = False

        # 4. Python audit imports
        import_ok = True
        try:
            import importlib

            importlib.import_module("engine.static_audit._pipeline_steps")
            paperconan_adapter = importlib.import_module(
                "engine.static_audit.adapters.paperconan_adapter"
            )
            getattr(paperconan_adapter, "run_paperconan_scan")
        except (AttributeError, ImportError) as exc:
            import_ok = False
            checks["python_imports"] = {"ok": False, "detail": str(exc)}
            all_ok = False
        if import_ok:
            checks["python_imports"] = {"ok": True}

        return {
            "status": "ok" if all_ok else "degraded",
            "checks": checks,
        }

    # --- Auth info endpoint --------------------------------------------
    @app.get("/api/me")
    async def get_me(
        auth: AuthContext = Depends(get_auth_context),
    ) -> dict[str, Any]:
        """Return the current user's identity and roles.

        Used by the frontend to determine auth state on page load.
        """
        return {
            "user_id": auth.user_id,
            "email": auth.email,
            "roles": sorted(auth.roles),
            "is_admin": auth.is_admin(),
        }

    # --- Frontend static files ----------------------------------------
    dist = (
        Path(frontend_dist)
        if frontend_dist
        else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )

    if dist.exists() and (dist / "index.html").exists():
        # Catch-all for SPA: serve index.html for non-API, non-file paths
        @app.get("/{path:path}")
        async def serve_spa(path: str) -> Any:
            from fastapi.responses import FileResponse

            dist_resolved = dist.resolve()
            target = (dist / path).resolve()
            if target == dist_resolved or dist_resolved in target.parents:
                if target.exists() and target.is_file():
                    content_type = (
                        mimetypes.guess_type(str(target))[0]
                        or "application/octet-stream"
                    )
                    return FileResponse(target, media_type=content_type)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/{path:path}")
        async def frontend_not_found(path: str) -> JSONResponse:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "FrontendNotBuilt",
                    "detail": "frontend dist not found; run `npm run build` in web/frontend or use Vite dev server",
                },
            )

    return app


def _resolve_database_url(
    data_root: str | Path, database_url: str | None = None
) -> str:
    if database_url:
        return database_url
    return get_database_url()


# Module-level app — created lazily so that test imports don't trigger DB connections.
# Use ``create_app(...)`` explicitly in tests; ``uvicorn`` resolves ``app`` on demand.
_app: FastAPI | None = None


def get_app() -> FastAPI:
    """Return the module-level FastAPI app, creating it on first call."""
    global _app
    if _app is None:
        _app = create_app()
    return _app


# For ``uvicorn web.backend.veritas_web.app:app`` — resolves via module attribute lookup.
class _LazyApp:
    """Proxy that defers ``create_app()`` until the ASGI server actually calls it."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_app(), name)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await get_app()(scope, receive, send)


app = _LazyApp()


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    data_root: str = "web_data",
    output_root: str = "outputs",
) -> None:
    """Start the web server with uvicorn.  Used by the Makefile."""
    import uvicorn

    global app
    app = create_app(data_root=data_root, output_root=output_root)
    auth_mode = (
        "none"
        if isinstance(create_auth_provider(AuthConfig.from_env()), NoAuthProvider)
        else type(create_auth_provider(AuthConfig.from_env())).__name__
    )
    logger.info(
        "Veritas Web backend listening on http://%s:%s (auth: %s)",
        host,
        port,
        auth_mode,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    serve(
        host=get_env("VERITAS_HOST", required=False, default="127.0.0.1"),
        port=int(get_env("VERITAS_PORT", required=False, default="8765")),
        data_root=get_env("VERITAS_DATA_ROOT", required=False, default="web_data"),
        output_root=get_env("VERITAS_OUTPUT_ROOT", required=False, default="outputs"),
    )
