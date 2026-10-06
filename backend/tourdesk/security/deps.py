"""FastAPI dependencies for authentication and authorisation."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from tourdesk.core.config import get_settings
from tourdesk.core.db import get_db
from tourdesk.models import User, UserSession
from tourdesk.security.sessions import load_session, read_session_token, revoke_session, touch_session

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# state-changing endpoints that stay available while an admin views another user
IMPERSONATION_WRITE_ALLOWED = {"/api/admin/impersonation/stop", "/api/auth/logout"}
# endpoints usable while a password change is required
PASSWORD_CHANGE_ALLOWED = {"/api/auth/me", "/api/auth/logout", "/api/users/me/password", "/api/settings"}


@dataclass
class AuthContext:
    session: UserSession
    actor: User  # the logged in account
    user: User  # the account whose data is shown (differs while impersonating)

    @property
    def impersonating(self) -> bool:
        return self.actor.id != self.user.id

    @property
    def is_admin(self) -> bool:
        return self.actor.is_admin


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def verify_origin(request: Request) -> None:
    """Reject cross-site state-changing requests (CSRF defence in depth)."""
    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if not referer:
            return  # non-browser client; session requests still need the CSRF token
        origin = referer
    try:
        parts = urlsplit(origin)
    except ValueError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ungültiger Ursprung der Anfrage") from None
    origin_host = (parts.netloc or "").lower()
    request_host = (request.headers.get("host") or "").lower()
    allowed = {request_host}
    public_url = get_settings().public_url
    if public_url:
        allowed.add(urlsplit(public_url).netloc.lower())
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        allowed.add(forwarded_host.split(",")[0].strip().lower())
    if origin_host not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Anfrage von fremdem Ursprung abgelehnt")


def _authenticate(request: Request, db: Session) -> AuthContext | None:
    record = load_session(db, read_session_token(request))
    if record is None:
        return None
    actor = record.user
    if not actor.is_active:
        revoke_session(db, record)
        db.commit()
        return None
    effective = actor
    if record.impersonated_user_id is not None:
        target = record.impersonated_user
        if target is None or not actor.is_admin:
            record.impersonated_user_id = None
            record.impersonation_started_at = None
            db.commit()
        else:
            effective = target
    return AuthContext(session=record, actor=actor, user=effective)


def get_optional_context(request: Request, db: Session = Depends(get_db)) -> AuthContext | None:
    return _authenticate(request, db)


def get_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    ctx = _authenticate(request, db)
    if ctx is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
    path = request.url.path
    if request.method not in SAFE_METHODS:
        verify_origin(request)
        sent = request.headers.get("x-csrf-token") or ""
        if not hmac.compare_digest(sent.encode(), ctx.session.csrf_token.encode()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF-Token fehlt oder ist ungültig")
        if ctx.impersonating and path not in IMPERSONATION_WRITE_ALLOWED:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "In der Benutzeransicht sind keine Änderungen möglich (nur Lesezugriff).",
            )
    if ctx.actor.must_change_password and path not in PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password_change_required")
    touch_session(db, ctx.session)
    request.state.user_id = ctx.actor.id
    return ctx


def require_admin(ctx: AuthContext = Depends(get_context)) -> AuthContext:
    if not ctx.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur für Administratoren")
    return ctx
