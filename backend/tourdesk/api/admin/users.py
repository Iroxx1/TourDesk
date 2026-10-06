"""/api/admin/users – user management and "view as user" (impersonation)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from tourdesk.api.auth import _me
from tourdesk.api.filters import filter_out
from tourdesk.core.db import get_db
from tourdesk.core.text import escape_like
from tourdesk.core.timeutil import utcnow
from tourdesk.models import AuditLog, User, UserArtist, UserSession
from tourdesk.schemas.common import OkResponse
from tourdesk.schemas.users import (
    AdminPasswordReset,
    AdminPasswordResetResult,
    AdminUserCreate,
    AdminUserCreated,
    AdminUserOut,
    AdminUserUpdate,
    MeResponse,
)
from tourdesk.security.deps import AuthContext, require_admin
from tourdesk.security.passwords import hash_password
from tourdesk.security.sessions import revoke_user_sessions
from tourdesk.services import audit
from tourdesk.services.artists import artist_out
from tourdesk.services.filters import get_default_filter, location_rule_count
from tourdesk.services.media import delete_avatar
from tourdesk.services.users import (
    admin_count,
    create_user,
    ensure_unique,
    generate_temporary_password,
    norm_email,
    norm_username,
    user_out,
    validate_password,
)

router = APIRouter(prefix="/users")


def admin_user_out(db: Session, user: User) -> AdminUserOut:
    base = user_out(user).model_dump()
    artist_count = db.execute(select(func.count(UserArtist.id)).where(UserArtist.user_id == user.id)).scalar_one()
    active_count = db.execute(
        select(func.count(UserArtist.id)).where(UserArtist.user_id == user.id, UserArtist.is_active.is_(True))
    ).scalar_one()
    sessions = db.execute(
        select(func.count(UserSession.id)).where(UserSession.user_id == user.id, UserSession.expires_at > utcnow())
    ).scalar_one()
    return AdminUserOut(
        **base,
        last_seen_at=user.last_seen_at,
        locked_until=user.locked_until,
        failed_login_count=user.failed_login_count,
        artist_count=artist_count,
        active_artist_count=active_count,
        location_rule_count=location_rule_count(db, user.id),
        session_count=sessions,
    )


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Benutzer nicht gefunden")
    return user


@router.get("", response_model=list[AdminUserOut])
def list_users(
    q: str = Query("", max_length=100),
    role: str | None = Query(None, pattern="^(user|admin)$"),
    active: bool | None = None,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AdminUserOut]:
    stmt = select(User)
    if q.strip():
        like = "%" + escape_like(q.strip().casefold()) + "%"
        stmt = stmt.where(or_(User.username_norm.like(like, escape="\\"), User.email_norm.like(like, escape="\\")))
    if role:
        stmt = stmt.where(User.role_key == role)
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    users = db.execute(stmt.order_by(User.username_norm)).unique().scalars().all()
    return [admin_user_out(db, u) for u in users]


@router.post("", response_model=AdminUserCreated, status_code=status.HTTP_201_CREATED)
def create(payload: AdminUserCreate, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> AdminUserCreated:
    temporary = None
    password = payload.password
    if not password:
        temporary = password = generate_temporary_password()
    user = create_user(
        db,
        username=payload.username,
        email=payload.email,
        password=password,
        role=payload.role,
        display_name=payload.display_name,
        is_active=payload.is_active,
        must_change_password=payload.must_change_password or temporary is not None,
        created_by=ctx.actor,
    )
    audit.record(db, "admin.user_create", actor=ctx.actor, request=request, target_type="user", target_id=user.id,
                 target_label=user.username, details={"role": user.role_key})
    db.commit()
    return AdminUserCreated(user=admin_user_out(db, user), temporary_password=temporary)


@router.get("/{user_id}", response_model=AdminUserOut)
def get_user(user_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> AdminUserOut:
    return admin_user_out(db, _get_user(db, user_id))


@router.patch("/{user_id}", response_model=AdminUserOut)
def update(user_id: int, payload: AdminUserUpdate, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> AdminUserOut:
    user = _get_user(db, user_id)
    data = payload.model_dump(exclude_unset=True)
    changes: dict[str, str] = {}
    revoke = False
    if data.get("username") and norm_username(data["username"]) != user.username_norm:
        ensure_unique(db, username=data["username"], exclude_id=user.id)
        changes["username"] = f"{user.username} → {data['username']}"
        user.username, user.username_norm = data["username"], norm_username(data["username"])
    if data.get("email") and norm_email(data["email"]) != user.email_norm:
        ensure_unique(db, email=data["email"], exclude_id=user.id)
        changes["email"] = f"{user.email} → {data['email']}"
        user.email, user.email_norm = data["email"], norm_email(data["email"])
    if "display_name" in data:
        user.display_name = data["display_name"]
    if data.get("role") and data["role"] != user.role_key:
        if user.id == ctx.actor.id:
            raise HTTPException(422, "Die eigene Rolle kann nicht geändert werden.")
        if user.role_key == "admin" and admin_count(db) <= 1:
            raise HTTPException(422, "Der letzte aktive Administrator kann nicht herabgestuft werden.")
        changes["role"] = f"{user.role_key} → {data['role']}"
        user.role_key = data["role"]
        revoke = True
    if data.get("is_active") is not None and data["is_active"] != user.is_active:
        if user.id == ctx.actor.id:
            raise HTTPException(422, "Das eigene Konto kann nicht deaktiviert werden.")
        if not data["is_active"] and user.role_key == "admin" and admin_count(db) <= 1:
            raise HTTPException(422, "Der letzte aktive Administrator kann nicht deaktiviert werden.")
        changes["is_active"] = "aktiviert" if data["is_active"] else "deaktiviert"
        user.is_active = data["is_active"]
        revoke = revoke or not user.is_active
    if data.get("must_change_password") is not None:
        user.must_change_password = data["must_change_password"]
    if revoke:
        revoke_user_sessions(db, user.id)
    if changes:
        audit.record(db, "admin.user_update", actor=ctx.actor, request=request, target_type="user", target_id=user.id,
                     target_label=user.username, details=changes)
    db.commit()
    return admin_user_out(db, user)


@router.delete("/{user_id}", response_model=OkResponse)
def delete(user_id: int, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> OkResponse:
    user = _get_user(db, user_id)
    if user.id == ctx.actor.id:
        raise HTTPException(422, "Das eigene Konto kann nicht gelöscht werden.")
    if user.role_key == "admin" and user.is_active and admin_count(db) <= 1:
        raise HTTPException(422, "Der letzte aktive Administrator kann nicht gelöscht werden.")
    name = user.username
    revoke_user_sessions(db, user.id)
    delete_avatar(user.id)
    audit.record(db, "admin.user_delete", actor=ctx.actor, request=request, target_type="user", target_id=user.id, target_label=name)
    db.delete(user)
    db.commit()
    return OkResponse(detail=f"Benutzer {name} wurde gelöscht.")


@router.post("/{user_id}/password", response_model=AdminPasswordResetResult)
def reset_password(user_id: int, payload: AdminPasswordReset, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> AdminPasswordResetResult:
    user = _get_user(db, user_id)
    temporary = None
    password = payload.new_password
    if not password:
        temporary = password = generate_temporary_password()
    else:
        validate_password(password, username=user.username, email=user.email)
    user.password_hash = hash_password(password)
    user.password_changed_at = utcnow()
    user.must_change_password = payload.must_change_password or temporary is not None
    user.failed_login_count = 0
    user.locked_until = None
    revoke_user_sessions(db, user.id)
    audit.record(db, "admin.password_reset", actor=ctx.actor, request=request, target_type="user", target_id=user.id,
                 target_label=user.username, details={"generated": temporary is not None})
    db.commit()
    return AdminPasswordResetResult(temporary_password=temporary)


@router.post("/{user_id}/unlock", response_model=OkResponse)
def unlock(user_id: int, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> OkResponse:
    user = _get_user(db, user_id)
    user.failed_login_count = 0
    user.locked_until = None
    audit.record(db, "admin.user_unlock", actor=ctx.actor, request=request, target_type="user", target_id=user.id, target_label=user.username)
    db.commit()
    return OkResponse()


@router.get("/{user_id}/artists")
def user_artists(user_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    _get_user(db, user_id)
    subs = db.execute(
        select(UserArtist).where(UserArtist.user_id == user_id).order_by(UserArtist.sort_order, UserArtist.id)
    ).unique().scalars().all()
    return [artist_out(ua.artist, ua).model_dump(mode="json") for ua in subs]


@router.get("/{user_id}/filters")
def user_filters(user_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    _get_user(db, user_id)
    f = get_default_filter(db, user_id)
    db.commit()
    return filter_out(db, f).model_dump(mode="json")


@router.get("/{user_id}/audit")
def user_audit(user_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(AuditLog)
        .where(or_(AuditLog.actor_user_id == user_id, (AuditLog.target_type == "user") & (AuditLog.target_id == str(user_id))))
        .order_by(AuditLog.created_at.desc())
        .limit(100)
    ).scalars().all()
    return [
        {"id": a.id, "created_at": a.created_at, "action": a.action, "actor": a.actor_username, "target": a.target_label,
         "success": a.success, "details": a.details, "ip": a.ip}
        for a in rows
    ]


@router.post("/{user_id}/impersonate", response_model=MeResponse)
def impersonate(user_id: int, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> MeResponse:
    target = _get_user(db, user_id)
    if target.id == ctx.actor.id:
        raise HTTPException(422, "Du kannst nicht deine eigene Ansicht simulieren.")
    ctx.session.impersonated_user_id = target.id
    ctx.session.impersonation_started_at = utcnow()
    audit.record(db, "admin.impersonation_start", actor=ctx.actor, request=request, target_type="user", target_id=target.id,
                 target_label=target.username)
    db.commit()
    return _me(db, AuthContext(session=ctx.session, actor=ctx.actor, user=target))
