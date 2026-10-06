"""/api/health – liveness/readiness probe (no authentication)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from tourdesk import __version__
from tourdesk.core.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> JSONResponse:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # pragma: no cover - depends on infrastructure
        db_ok = False
    return JSONResponse(
        {"status": "ok" if db_ok else "degraded", "database": db_ok, "version": __version__},
        status_code=200 if db_ok else 503,
    )
