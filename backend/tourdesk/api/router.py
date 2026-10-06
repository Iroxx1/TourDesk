"""Assembles all API routers under /api."""

from __future__ import annotations

from fastapi import APIRouter

from tourdesk.api import artists, auth, events, filters, geo, health, misc, settings, users, venues
from tourdesk.api.admin import router as admin_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(settings.router)
api_router.include_router(geo.router)
api_router.include_router(venues.router)
api_router.include_router(filters.router)
api_router.include_router(artists.router)
api_router.include_router(events.router)
api_router.include_router(misc.router)
api_router.include_router(admin_router.router)
