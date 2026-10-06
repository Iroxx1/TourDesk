"""/api/admin – all admin endpoints (protected by ``require_admin``)."""

from __future__ import annotations

from fastapi import APIRouter

from tourdesk.api.admin import crawler, system, users

router = APIRouter(prefix="/admin", tags=["admin"])
router.include_router(system.router)
router.include_router(users.router)
router.include_router(crawler.router)
