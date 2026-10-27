"""FastAPI application factory for the atlas-api service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from project_atlas import APP_NAME, __version__
from project_atlas.core.config import Settings, load_settings
from project_atlas.core.context import build_context
from project_atlas.core.errors import AtlasError

log = logging.getLogger("atlas")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; frame-ancestors 'none'; "
    "base-uri 'none'; form-action 'self'; object-src 'none'"
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ctx = build_context(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from project_atlas.backup.service import BackupScheduler

        token = ctx.ensure_setup_token()
        if token:
            log.warning("No users exist. Initial setup token written to %s", ctx.setup_token_path)
        scheduler = BackupScheduler(ctx, settings.backup_interval_hours)
        scheduler.start()
        yield
        scheduler.stop()
        ctx.dispose()

    app = FastAPI(
        title="atlas-api", version=__version__, lifespan=lifespan,
        description=f"{APP_NAME} — Offline Intelligence and Data Operations Platform. Navigate the Complexity of Data.",
        docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None,
    )
    app.state.ctx = ctx

    @app.exception_handler(AtlasError)
    async def atlas_error(_req: Request, exc: AtlasError):
        return JSONResponse(status_code=exc.status_code,
                            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_req: Request, exc: RequestValidationError):
        errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_failed",
                                                                "message": "Request validation failed", "details": {"errors": errs}}})

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.tls_terminated:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    from project_atlas.api import (
        admin, ai, analysis, auth, data, documents, entities, investigations, projects, reports, search, workflows,
    )

    for r in (auth.router, admin.router, projects.router, data.router, data.jobs_router, entities.router, search.router,
              documents.router, analysis.router, investigations.router, workflows.router, reports.router, ai.router,
              admin.system_router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": APP_NAME, "version": __version__, "offline_mode": settings.offline_mode}

    bundled = Path(__file__).resolve().parent / "static"
    dist = settings.frontend_dist or (bundled if (bundled / "index.html").exists()
                                      else Path(__file__).resolve().parents[2] / "frontend" / "dist")
    if dist.is_dir():
        index = dist / "index.html"
        root = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Not found"}})
            candidate = (root / path).resolve()
            if path and root in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index)

    return app
