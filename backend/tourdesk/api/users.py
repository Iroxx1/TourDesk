"""/api/users/me – own profile, password, avatar."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from tourdesk.core.db import get_db
from tourdesk.core.timeutil import utcnow
from tourdesk.schemas.common import OkResponse
from tourdesk.schemas.users import PasswordChange, ProfileUpdate, UserOut
from tourdesk.security.deps import AuthContext, get_context
from tourdesk.security.passwords import hash_password, verify_password
from tourdesk.security.sessions import revoke_user_sessions
from tourdesk.services import audit
from tourdesk.services.media import MAX_UPLOAD_BYTES, ImageError, delete_avatar, save_avatar
from tourdesk.services.users import ensure_unique, norm_email, norm_username, user_out, validate_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def get_me(ctx: AuthContext = Depends(get_context)) -> UserOut:
    return user_out(ctx.user)


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: ProfileUpdate, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> UserOut:
    user = ctx.user
    changes: dict[str, str] = {}
    sensitive = (payload.email is not None and norm_email(payload.email) != user.email_norm) or (
        payload.username is not None and norm_username(payload.username) != user.username_norm
    )
    if sensitive:
        valid, _ = verify_password(user.password_hash, payload.current_password or "")
        if not valid:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Zur Änderung von Benutzername oder E-Mail bitte das aktuelle Passwort angeben.")
    if payload.username is not None and norm_username(payload.username) != user.username_norm:
        ensure_unique(db, username=payload.username, exclude_id=user.id)
        changes["username"] = f"{user.username} → {payload.username}"
        user.username = payload.username
        user.username_norm = norm_username(payload.username)
    if payload.email is not None and norm_email(payload.email) != user.email_norm:
        ensure_unique(db, email=payload.email, exclude_id=user.id)
        changes["email"] = "geändert"
        user.email = payload.email
        user.email_norm = norm_email(payload.email)
    if "display_name" in payload.model_fields_set:
        user.display_name = payload.display_name
    if changes:
        audit.record(db, "user.profile_update", actor=ctx.actor, request=request, target_type="user",
                     target_id=user.id, target_label=user.username, details=changes)
    db.commit()
    return user_out(user)


@router.post("/me/password", response_model=OkResponse)
def change_password(
    payload: PasswordChange, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> OkResponse:
    user = ctx.user
    valid, _ = verify_password(user.password_hash, payload.current_password)
    if not valid:
        audit.record(db, "auth.password_change_failed", actor=user, request=request, success=False)
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Das aktuelle Passwort ist falsch.")
    if payload.new_password == payload.current_password:
        raise HTTPException(422, "Das neue Passwort muss sich vom aktuellen unterscheiden.")
    validate_password(payload.new_password, username=user.username, email=user.email)
    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = utcnow()
    user.must_change_password = False
    revoke_user_sessions(db, user.id, except_id=ctx.session.id)
    audit.record(db, "auth.password_changed", actor=user, request=request, target_type="user", target_id=user.id)
    db.commit()
    return OkResponse(detail="Passwort geändert. Andere Sitzungen wurden abgemeldet.")


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> UserOut:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        path = save_avatar(ctx.user.id, data)
    except ImageError as exc:
        raise HTTPException(422, str(exc)) from exc
    ctx.user.avatar_path = path
    ctx.user.avatar_version += 1
    db.commit()
    return user_out(ctx.user)


@router.delete("/me/avatar", response_model=UserOut)
def remove_avatar(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> UserOut:
    delete_avatar(ctx.user.id)
    ctx.user.avatar_path = None
    ctx.user.avatar_version += 1
    db.commit()
    return user_out(ctx.user)
