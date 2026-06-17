"""FastAPI application for the Veritas web backend.

Replaces the previous stdlib ``ThreadingHTTPServer`` implementation.
All API routes live in ``routers/`` sub-modules; this file wires them
together, sets up CORS, serves the frontend static build, and exposes
the ``serve()`` entry point used by the Makefile.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .artifacts import ArtifactService
from .auth import AuthProvider, NoAuthProvider
from .case_store import CaseStore
from .config import AuthConfig, create_auth_provider
from .database import create_db_engine
from .dependencies import AppDependencies, set_dependencies
from .investigations import WebInvestigationService
from .runner import AuditRunner
from .routers import artifacts, cases, embeddings, investigations, review, tools, visual
from .tool_catalog import seed_tool_registry


class VeritasWebApp:
    """Kept for backward compat — some modules import this class."""

    def __init__(
        self,
        data_root: str | Path = "web_data",
        output_root: str | Path = "outputs",
        frontend_dist: str | Path | None = None,
        database_url: str | None = None,
    ) -> None:
        self.store = CaseStore(data_root, database_url=_resolve_database_url(data_root, database_url))
        self.runner = AuditRunner(self.store, output_root=output_root)
        self.recovered_interrupted_runs = self.runner.recover_interrupted_runs()
        self.artifacts = ArtifactService(self.store)
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
    app = FastAPI(title="Veritas Web P1", version="0.1.0")

    # --- Core services ------------------------------------------------
    resolved_database_url = _resolve_database_url(data_root, database_url)
    store = CaseStore(data_root, database_url=resolved_database_url)
    runner = AuditRunner(store, output_root=output_root)
    artifacts_svc = ArtifactService(store)
    investigations_svc = WebInvestigationService(store, artifacts_svc)
    auth = auth_provider or create_auth_provider(AuthConfig.from_env())

    # --- Dependency injection -----------------------------------------
    # Use CaseStore's engine if it has one (avoids duplicate in-memory SQLite DBs)
    engine = getattr(store, "_engine", None) or (
        create_db_engine() if (database_url or store.sql_mode) else None
    )
    deps = AppDependencies(store=store, auth_provider=auth, engine=engine)
    deps.runner = runner  # type: ignore[attr-defined]
    deps.artifacts = artifacts_svc  # type: ignore[attr-defined]
    deps.investigations = investigations_svc  # type: ignore[attr-defined]
    app.state.dependencies = deps
    set_dependencies(deps)

    if deps._session_factory is not None:
        session = deps._session_factory()
        try:
            seed_tool_registry(session)
        finally:
            session.close()

    recovered = runner.recover_interrupted_runs()

    # --- Middleware ----------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Exception handlers -------------------------------------------
    @app.exception_handler(FileNotFoundError)
    async def handle_not_found(request: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": "NotFound", "detail": str(exc)})

    @app.exception_handler(PermissionError)
    async def handle_forbidden(request: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"error": "Forbidden", "detail": str(exc)})

    @app.exception_handler(ValueError)
    async def handle_bad_request(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "BadRequest", "detail": str(exc)})

    # --- Routers -------------------------------------------------------
    app.include_router(cases.router, prefix="/api")
    app.include_router(artifacts.router, prefix="/api")
    app.include_router(investigations.router, prefix="/api")
    app.include_router(visual.router, prefix="/api")
    app.include_router(review.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(embeddings.router, prefix="/api")

    # --- Health endpoint -----------------------------------------------
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "runner_mode": "thread_pool",
            "recovered_interrupted_runs": recovered,
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
                    content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
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


def _resolve_database_url(data_root: str | Path, database_url: str | None = None) -> str:
    if database_url:
        return database_url
    env_url = os.environ.get("VERITAS_DATABASE_URL")
    if env_url:
        return env_url
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{root / 'veritas_web.sqlite3'}"


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
    auth_mode = "none" if isinstance(
        create_auth_provider(AuthConfig.from_env()), NoAuthProvider
    ) else type(create_auth_provider(AuthConfig.from_env())).__name__
    print(f"Veritas Web backend listening on http://{host}:{port} (auth: {auth_mode})")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    serve(
        host=os.environ.get("VERITAS_HOST", "127.0.0.1"),
        port=int(os.environ.get("VERITAS_PORT", "8765")),
        data_root=os.environ.get("VERITAS_DATA_ROOT", "web_data"),
        output_root=os.environ.get("VERITAS_OUTPUT_ROOT", "outputs"),
    )
