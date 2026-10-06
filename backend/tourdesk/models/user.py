"""Users, roles, settings, sessions and audit log."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tourdesk.models.base import Base, CreatedMixin, TimestampMixin

if TYPE_CHECKING:
    from tourdesk.models.artist import UserArtist
    from tourdesk.models.filters import UserFilter


DEFAULT_VIEW_SETTINGS: dict[str, Any] = {
    "tile_size": "medium",  # small | medium | large
    "sort": "next_event",  # next_event | name | added
    "show_artists_without_events": True,
    "tile_event_count": 3,
    "taskbar_labels": False,
    "open_windows_maximized": False,
}

DEFAULT_NOTIFICATION_SETTINGS: dict[str, Any] = {
    "new_events": True,
    "event_in_region": True,
    "tickets_on_sale": True,
    "event_changed": True,
    "event_cancelled": True,
    "festival_confirmed": True,
    "system": True,
}


class Role(Base):
    __tablename__ = "roles"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    permissions: Mapped[list[Any]] = mapped_column(nullable=False, default=list)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    username_norm: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    email_norm: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("roles.key", ondelete="RESTRICT"), nullable=False, default="user", index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    avatar_path: Mapped[str | None] = mapped_column(String(255))
    avatar_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    role: Mapped[Role] = relationship(lazy="joined")
    settings: Mapped[UserSettings | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    subscriptions: Mapped[list[UserArtist]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    filters: Mapped[list[UserFilter]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_admin(self) -> bool:
        return self.role_key == "admin"


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    theme: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    wallpaper: Mapped[str] = mapped_column(String(64), nullable=False, default="bloom")
    accent_color: Mapped[str | None] = mapped_column(String(16))
    animations: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    transparency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Berlin")
    view: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=lambda: dict(DEFAULT_VIEW_SETTINGS))
    notifications: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, default=lambda: dict(DEFAULT_NOTIFICATION_SETTINGS)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="settings")


class UserSession(CreatedMixin, Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    remember: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    impersonated_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    impersonation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="joined")
    impersonated_user: Mapped[User | None] = relationship(foreign_keys=[impersonated_user_id], lazy="joined")


class AuditLog(CreatedMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor_username: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    target_label: Mapped[str | None] = mapped_column(String(255))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    details: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
