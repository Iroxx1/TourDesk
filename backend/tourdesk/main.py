"""ASGI application: REST API under /api, media under /media, the SPA everywhere else."""

from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tourdesk import __version__
from tourdesk.api.router import api_router
from tourdesk.core.config import get_settings
from tourdesk.core.db import get_db
from tourdesk.core.logging import setup_logging
from tourdesk.security.middleware import (
    AccessLogMiddleware,
    ApiRateLimitMiddleware,
    ProxyHeadersMiddleware,
    SecurityHeadersMiddleware,
)
from tourdesk.security.sessions import load_session, read_session_token
from tourdesk.services.media import resolve_media_path

log = logging.getLogger("tourdesk.api")

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/manifest+json", ".webmanifest")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.get_secret_key()  # fail fast when missing in production
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    log.info(
        "TourDesk API %s startet", __version__,
        extra={"event": "api.start", "frontend": str(settings.resolved_frontend_dist or "-")},
    )
    yield
    log.info("TourDesk API beendet", extra={"event": "api.stop"})


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
        msg = str(err.get("msg", "ungültig"))
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "Ungültige Eingabe"


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging("api")
    docs = settings.enable_api_docs or not settings.is_production
    app = FastAPI(
        title="TourDesk API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": [str(p) for p in err.get("loc", [])], "msg": str(err.get("msg", "")), "type": str(err.get("type", ""))}
            for err in exc.errors()[:10]
        ]
        return JSONResponse({"detail": _validation_message(exc), "errors": errors}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code == 404 and not request.url.path.startswith(("/api/", "/media/")):
            return _spa_response(request)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"event": "api.error", "path": request.url.path})
        return JSONResponse({"detail": "Interner Fehler. Details stehen im Server-Log."}, status_code=500)

    app.include_router(api_router, prefix="/api")

    @app.get("/media/{path:path}", include_in_schema=False)
    def media(path: str, request: Request, db=Depends(get_db)) -> Response:
        if load_session(db, read_session_token(request)) is None:
            raise HTTPException(401, "Nicht angemeldet")
        file = resolve_media_path(path)
        if file is None:
            raise HTTPException(404, "Nicht gefunden")
        return FileResponse(file, headers={"Cache-Control": "private, max-age=86400"})

    dist = settings.resolved_frontend_dist

    def _spa_response(request: Request) -> Response:
        if dist is None:
            return JSONResponse(
                {"detail": "Frontend nicht gebaut. Bitte `npm run build` im Ordner frontend ausführen."},
                status_code=503,
            )
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str, request: Request) -> Response:
        if full_path.startswith(("api/", "media/")):
            raise HTTPException(404, "Nicht gefunden")
        if dist is not None and full_path:
            candidate = (dist / full_path).resolve()
            if dist.resolve() in candidate.parents and candidate.is_file():
                immutable = full_path.startswith("assets/")
                cache = "public, max-age=31536000, immutable" if immutable else "public, max-age=3600"
                return FileResponse(candidate, headers={"Cache-Control": cache})
        return _spa_response(request)

    # middleware order: last added runs first
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(ApiRateLimitMiddleware)
    app.add_middleware(AccessLogMiddleware)
    if settings.allowed_host_list and settings.allowed_host_list != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
    app.add_middleware(ProxyHeadersMiddleware)
    return app


def run() -> None:  # pragma: no cover - started via CLI
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "tourdesk.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        proxy_headers=False,  # handled by ProxyHeadersMiddleware
        access_log=False,
        log_config=None,
        server_header=False,
    )

