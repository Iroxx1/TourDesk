"""/api/auth – first-run setup, login, logout, current session."""

from __future__ import annotations

import hmac
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from tourdesk import __version__
from tourdesk.core.config import get_settings
from tourdesk.core.db import get_db
from tourdesk.core.timeutil import utcnow
from tourdesk.schemas.common import OkResponse
from tourdesk.schemas.users import ImpersonationInfo, LoginRequest, MeResponse, SetupRequest, SetupStatus
from tourdesk.security.deps import AuthContext, client_ip, get_context, get_optional_context, verify_origin
from tourdesk.security.netsafety import is_private_client
from tourdesk.security.passwords import hash_password, verify_password
from tourdesk.security.ratelimit import get_limiter
from tourdesk.security.sessions import clear_session_cookie, create_session, revoke_session, set_session_cookie
from tourdesk.services import audit
from tourdesk.services.users import create_user, find_user_by_login, get_settings_row, settings_out, user_count, user_out

router = APIRouter(prefix="/auth", tags=["auth"])

GENERIC_LOGIN_ERROR = "Benutzername oder Passwort ist falsch."


def _setup_allowed(request: Request) -> bool:
    return get_settings().allow_remote_setup or is_private_client(client_ip(request))


@router.get("/setup-status", response_model=SetupStatus)
def setup_status(request: Request, db: Session = Depends(get_db)) -> SetupStatus:
    needs = user_count(db) == 0
    return SetupStatus(needs_setup=needs, setup_allowed=needs and _setup_allowed(request), version=__version__)


@router.post("/setup", response_model=MeResponse, status_code=status.HTTP_201_CREATED)
def setup(payload: SetupRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> MeResponse:
    verify_origin(request)
    # serialise concurrent setup attempts
    db.execute(text("SELECT pg_advisory_xact_lock(724001)"))
    if user_count(db) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "TourDesk ist bereits eingerichtet.")
    if not _setup_allowed(request):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Die Ersteinrichtung ist nur aus dem lokalen Netzwerk möglich "
            "(oder mit TOURDESK_ALLOW_REMOTE_SETUP=true).",
        )
    user = create_user(
        db, username=payload.username, email=payload.email, password=payload.password, role="admin"
    )
    user.last_login_at = utcnow()
    token, record = create_session(
        db, user_id=user.id, remember=False, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    audit.record(db, "auth.setup", actor=user, request=request, target_type="user", target_id=user.id, target_label=user.username)
    db.commit()
    set_session_cookie(response, request, token, record)
    return _me(db, AuthContext(session=record, actor=user, user=user))


@router.post("/login", response_model=MeResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> MeResponse:
    verify_origin(request)
    settings = get_settings()
    ip = client_ip(request) or "unknown"
    limiter = get_limiter("login-ip", settings.login_max_attempts_per_ip, settings.login_window_minutes * 60)
    if not limiter.hit(ip):
        audit.record(db, "auth.login_rate_limited", actor_username=payload.username[:64], request=request, success=False)
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Zu viele Anmeldeversuche. Bitte in einigen Minuten erneut versuchen.",
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )

    user = find_user_by_login(db, payload.username)
    now = utcnow()
    if user is not None and user.locked_until and user.locked_until > now:
        verify_password(None, payload.password)  # constant-ish timing
        audit.record(db, "auth.login_locked", actor=user, request=request, success=False)
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Anmeldung vorübergehend gesperrt. Bitte später erneut versuchen.",
        )

    valid, needs_rehash = verify_password(user.password_hash if user else None, payload.password)
    if user is None or not valid:
        if user is not None:
            user.failed_login_count += 1
            over = user.failed_login_count - settings.login_lockout_threshold
            if over >= 0:
                minutes = min(30, 2**over)
                user.locked_until = now + timedelta(minutes=minutes)
            audit.record(db, "auth.login_failed", actor=user, request=request, success=False,
                         details={"failed_count": user.failed_login_count})
        else:
            audit.record(db, "auth.login_failed", actor_username=payload.username[:64], request=request,
                         success=False, details={"unknown_user": True})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)

    if not user.is_active:
        audit.record(db, "auth.login_inactive", actor=user, request=request, success=False)
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dieses Konto ist deaktiviert.")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash:
        user.password_hash = hash_password(payload.password)
    token, record = create_session(
        db, user_id=user.id, remember=payload.remember, ip=ip, user_agent=request.headers.get("user-agent")
    )
    audit.record(db, "auth.login", actor=user, request=request, details={"remember": payload.remember})
    db.commit()
    set_session_cookie(response, request, token, record)
    return _me(db, AuthContext(session=record, actor=user, user=user))


@router.post("/logout", response_model=OkResponse)
def logout(
    request: Request,
    response: Response,
    ctx: AuthContext | None = Depends(get_optional_context),
    db: Session = Depends(get_db),
) -> OkResponse:
    verify_origin(request)
    if ctx is not None:
        sent = request.headers.get("x-csrf-token") or ""
        if not hmac.compare_digest(sent.encode(), ctx.session.csrf_token.encode()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF-Token fehlt oder ist ungültig")
        audit.record(db, "auth.logout", actor=ctx.actor, request=request)
        revoke_session(db, ctx.session)
        db.commit()
    clear_session_cookie(response, request)
    return OkResponse()


@router.get("/me", response_model=MeResponse)
def me(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> MeResponse:
    return _me(db, ctx)


def _me(db: Session, ctx: AuthContext) -> MeResponse:
    impersonation = None
    if ctx.impersonating:
        impersonation = ImpersonationInfo(admin=user_out(ctx.actor), started_at=ctx.session.impersonation_started_at)
    return MeResponse(
        user=user_out(ctx.user),
        impersonation=impersonation,
        csrf_token=ctx.session.csrf_token,
        settings=settings_out(get_settings_row(db, ctx.user)),
        is_admin=ctx.user.is_admin,
        version=__version__,
        session_expires_at=ctx.session.expires_at,
    )
