"""User management helpers."""

from __future__ import annotations

import secrets
import string

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tourdesk.core.timeutil import utcnow
from tourdesk.models import User, UserFilter, UserSettings
from tourdesk.models.user import DEFAULT_NOTIFICATION_SETTINGS, DEFAULT_VIEW_SETTINGS
from tourdesk.schemas.users import SettingsOut, UserOut
from tourdesk.security.passwords import hash_password, password_problems
from tourdesk.services.media import avatar_url


def norm_username(value: str) -> str:
    return value.strip().casefold()


def norm_email(value: str) -> str:
    return value.strip().casefold()


def find_user_by_login(db: Session, login: str) -> User | None:
    key = login.strip().casefold()
    stmt = select(User).where((User.username_norm == key) | (User.email_norm == key))
    return db.execute(stmt).unique().scalar_one_or_none()


def user_count(db: Session) -> int:
    return db.execute(select(func.count(User.id))).scalar_one()


def ensure_unique(db: Session, *, username: str | None = None, email: str | None = None, exclude_id: int | None = None) -> None:
    if username is not None:
        stmt = select(User.id).where(User.username_norm == norm_username(username))
        if exclude_id:
            stmt = stmt.where(User.id != exclude_id)
        if db.execute(stmt).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "Dieser Benutzername ist bereits vergeben.")
    if email is not None:
        stmt = select(User.id).where(User.email_norm == norm_email(email))
        if exclude_id:
            stmt = stmt.where(User.id != exclude_id)
        if db.execute(stmt).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "Diese E-Mail-Adresse wird bereits verwendet.")


def validate_password(password: str, *, username: str | None, email: str | None) -> None:
    problems = password_problems(password, username=username, email=email)
    if problems:
        raise HTTPException(422, " ".join(problems))


def generate_temporary_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def create_user(
    db: Session,
    *,
    username: str,
    email: str,
    password: str,
    role: str = "user",
    display_name: str | None = None,
    is_active: bool = True,
    must_change_password: bool = False,
    created_by: User | None = None,
) -> User:
    ensure_unique(db, username=username, email=email)
    validate_password(password, username=username, email=email)
    user = User(
        username=username.strip(),
        username_norm=norm_username(username),
        email=email.strip(),
        email_norm=norm_email(email),
        display_name=display_name,
        password_hash=hash_password(password),
        role_key=role,
        is_active=is_active,
        must_change_password=must_change_password,
        password_changed_at=utcnow(),
        created_by_user_id=created_by.id if created_by else None,
    )
    db.add(user)
    db.flush()
    ensure_user_defaults(db, user)
    return user


def ensure_user_defaults(db: Session, user: User) -> None:
    if db.get(UserSettings, user.id) is None:
        db.add(
            UserSettings(
                user_id=user.id,
                view=dict(DEFAULT_VIEW_SETTINGS),
                notifications=dict(DEFAULT_NOTIFICATION_SETTINGS),
            )
        )
    has_filter = db.execute(select(UserFilter.id).where(UserFilter.user_id == user.id)).first()
    if not has_filter:
        db.add(UserFilter(user_id=user.id, name="Standard", is_default=True))
    db.flush()


def get_settings_row(db: Session, user: User) -> UserSettings:
    row = db.get(UserSettings, user.id)
    if row is None:
        ensure_user_defaults(db, user)
        row = db.get(UserSettings, user.id)
    assert row is not None
    return row


def settings_out(row: UserSettings) -> SettingsOut:
    view = dict(DEFAULT_VIEW_SETTINGS)
    view.update(row.view or {})
    notifications = dict(DEFAULT_NOTIFICATION_SETTINGS)
    notifications.update(row.notifications or {})
    return SettingsOut(
        theme=row.theme,  # type: ignore[arg-type]
        wallpaper=row.wallpaper,
        accent_color=row.accent_color,
        animations=row.animations,
        transparency=row.transparency,
        timezone=row.timezone,
        view=view,
        notifications=notifications,
    )


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        role=user.role_key,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        avatar_url=avatar_url(user.avatar_path, user.avatar_version),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def admin_count(db: Session, *, active_only: bool = True) -> int:
    stmt = select(func.count(User.id)).where(User.role_key == "admin")
    if active_only:
        stmt = stmt.where(User.is_active.is_(True))
    return db.execute(stmt).scalar_one()
