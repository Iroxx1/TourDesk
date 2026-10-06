"""Server-side sessions.

The cookie holds a random 256-bit token; the database only stores an HMAC of it.
A per-session CSRF token is returned by ``/api/auth/me`` and must be sent as
``X-CSRF-Token`` header with every state-changing request.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from tourdesk.core.config import get_settings
from tourdesk.core.timeutil import utcnow
from tourdesk.models import UserSession

SESSION_COOKIE = "td_session"
SECURE_SESSION_COOKIE = "__Host-td_session"
TOUCH_INTERVAL = timedelta(minutes=1)


def hash_token(token: str) -> str:
    key = get_settings().get_secret_key().encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def request_is_secure(request: Request) -> bool:
    mode = get_settings().cookie_secure
    if mode == "true":
        return True
    if mode == "false":
        return False
    return request.url.scheme == "https"


def read_session_token(request: Request) -> str | None:
    return request.cookies.get(SECURE_SESSION_COOKIE) or request.cookies.get(SESSION_COOKIE)


def _lifetimes(remember: bool) -> tuple[timedelta, timedelta]:
    """Return (idle timeout, absolute maximum)."""
    s = get_settings()
    if remember:
        return timedelta(days=s.session_idle_days), timedelta(days=s.session_remember_days)
    return timedelta(hours=s.session_hours), timedelta(days=min(7, s.session_remember_days))


def create_session(
    db: Session, *, user_id: int, remember: bool, ip: str | None, user_agent: str | None
) -> tuple[str, UserSession]:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    idle, _absolute = _lifetimes(remember)
    record = UserSession(
        token_hash=hash_token(token),
        user_id=user_id,
        csrf_token=secrets.token_urlsafe(32),
        remember=remember,
        expires_at=now + idle,
        last_seen_at=now,
        ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:400] or None,
    )
    db.add(record)
    db.flush()
    return token, record


def load_session(db: Session, token: str | None) -> UserSession | None:
    if not token or len(token) > 200:
        return None
    record = db.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    ).unique().scalar_one_or_none()
    if record is None:
        return None
    if record.expires_at <= utcnow():
        db.delete(record)
        db.commit()
        return None
    return record


def touch_session(db: Session, record: UserSession) -> None:
    """Sliding expiration, written at most once per minute."""
    now = utcnow()
    if record.last_seen_at and now - record.last_seen_at < TOUCH_INTERVAL:
        return
    idle, absolute = _lifetimes(record.remember)
    new_expiry = min(record.created_at + absolute, now + idle)
    db.execute(
        update(UserSession)
        .where(UserSession.id == record.id)
        .values(last_seen_at=now, expires_at=max(new_expiry, record.expires_at))
    )
    db.commit()


def revoke_session(db: Session, record: UserSession) -> None:
    db.execute(delete(UserSession).where(UserSession.id == record.id))


def revoke_user_sessions(db: Session, user_id: int, *, except_id: int | None = None) -> int:
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if except_id is not None:
        stmt = stmt.where(UserSession.id != except_id)
    result = db.execute(stmt)
    # sessions of admins impersonating this user end as well
    db.execute(
        update(UserSession)
        .where(UserSession.impersonated_user_id == user_id)
        .values(impersonated_user_id=None, impersonation_started_at=None)
    )
    return result.rowcount or 0


def cleanup_expired_sessions(db: Session) -> int:
    result = db.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
    return result.rowcount or 0


def set_session_cookie(response: Response, request: Request, token: str, record: UserSession) -> None:
    secure = request_is_secure(request)
    name = SECURE_SESSION_COOKIE if secure else SESSION_COOKIE
    max_age = None
    if record.remember:
        _idle, absolute = _lifetimes(True)
        max_age = int(absolute.total_seconds())
    response.set_cookie(
        name,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    # remove a stale cookie of the other variant (http <-> https switch)
    other = SESSION_COOKIE if secure else SECURE_SESSION_COOKIE
    if other in request.cookies:
        response.delete_cookie(other, path="/", secure=other.startswith("__Host-"))


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(SECURE_SESSION_COOKIE, path="/", secure=True)


def session_expiry(record: UserSession) -> datetime:
    return record.expires_at
