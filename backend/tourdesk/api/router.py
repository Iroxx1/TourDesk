"""Assembles all API routers under /api."""

from __future__ import annotations

from fastapi import APIRouter

from tourdesk.api import auth, health, settings, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(settings.router)
