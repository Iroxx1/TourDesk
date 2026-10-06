"""Schemas for authentication, users and personal settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from tourdesk.core.constants import WALLPAPER_KEYS
from tourdesk.schemas.common import HEX_COLOR_RE, ApiModel, CleanStr, Email, Username


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=254, description="Benutzername oder E-Mail")
    password: str = Field(min_length=1, max_length=256)
    remember: bool = False


class SetupRequest(ApiModel):
    username: Username
    email: Email
    password: str = Field(min_length=1, max_length=256)


class SetupStatus(ApiModel):
    needs_setup: bool
    setup_allowed: bool
    version: str


class UserOut(ApiModel):
    id: int
    username: str
    email: str
    display_name: str | None = None
    role: str
    is_active: bool
    must_change_password: bool
    avatar_url: str | None = None
    created_at: datetime
    last_login_at: datetime | None = None


class AdminUserOut(UserOut):
    last_seen_at: datetime | None = None
    locked_until: datetime | None = None
    failed_login_count: int = 0
    artist_count: int = 0
    active_artist_count: int = 0
    location_rule_count: int = 0
    session_count: int = 0


class SettingsOut(ApiModel):
    theme: Literal["light", "dark", "system"]
    wallpaper: str
    accent_color: str | None = None
    animations: bool
    transparency: bool
    timezone: str
    view: dict[str, Any]
    notifications: dict[str, Any]


class SettingsUpdate(ApiModel):
    theme: Literal["light", "dark", "system"] | None = None
    wallpaper: str | None = None
    accent_color: str | None = None
    animations: bool | None = None
    transparency: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)
    view: dict[str, Any] | None = None
    notifications: dict[str, bool] | None = None

    @field_validator("wallpaper")
    @classmethod
    def _wallpaper(cls, value: str | None) -> str | None:
        if value is not None and value not in WALLPAPER_KEYS:
            raise ValueError("Unbekannter Hintergrund")
        return value

    @field_validator("accent_color")
    @classmethod
    def _accent(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not HEX_COLOR_RE.match(value):
            raise ValueError("Akzentfarbe muss als #RRGGBB angegeben werden")
        return value.lower()


class ImpersonationInfo(ApiModel):
    admin: UserOut
    started_at: datetime | None = None


class MeResponse(ApiModel):
    user: UserOut
    impersonation: ImpersonationInfo | None = None
    csrf_token: str
    settings: SettingsOut
    is_admin: bool
    version: str
    session_expires_at: datetime


class ProfileUpdate(ApiModel):
    username: Username | None = None
    email: Email | None = None
    display_name: CleanStr = Field(default=None, max_length=100)
    current_password: str | None = Field(default=None, max_length=256)


class PasswordChange(ApiModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class AdminUserCreate(ApiModel):
    username: Username
    email: Email
    password: str | None = Field(default=None, max_length=256)
    display_name: CleanStr = Field(default=None, max_length=100)
    role: Literal["user", "admin"] = "user"
    is_active: bool = True
    must_change_password: bool = True


class AdminUserUpdate(ApiModel):
    username: Username | None = None
    email: Email | None = None
    display_name: CleanStr = Field(default=None, max_length=100)
    role: Literal["user", "admin"] | None = None
    is_active: bool | None = None
    must_change_password: bool | None = None


class AdminPasswordReset(ApiModel):
    new_password: str | None = Field(default=None, max_length=256)
    must_change_password: bool = True


class AdminPasswordResetResult(ApiModel):
    ok: bool = True
    temporary_password: str | None = None


class AdminUserCreated(ApiModel):
    user: AdminUserOut
    temporary_password: str | None = None
