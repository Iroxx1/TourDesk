"""Artists (shared catalogue) and per-user subscriptions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tourdesk.models.base import Base, CreatedMixin, TimestampMixin

if TYPE_CHECKING:
    from tourdesk.models.user import User


class Artist(TimestampMixin, Base):
    __tablename__ = "artists"
    __table_args__ = (
        Index(
            "ix_artists_name_norm_trgm",
            "name_norm",
            postgresql_using="gin",
            postgresql_ops={"name_norm": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    genre: Mapped[str | None] = mapped_column(String(100))
    country_code: Mapped[str | None] = mapped_column(String(2))
    description: Mapped[str | None] = mapped_column(Text)
    official_website: Mapped[str | None] = mapped_column(String(500))
    search_terms: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    external_ids: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    image_path: Mapped[str | None] = mapped_column(String(255))
    image_source: Mapped[str | None] = mapped_column(String(32))
    image_source_url: Mapped[str | None] = mapped_column(String(1000))
    image_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    image_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    crawl_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_crawl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    aliases: Mapped[list[ArtistAlias]] = relationship(
        back_populates="artist", cascade="all, delete-orphan", lazy="selectin", order_by="ArtistAlias.id"
    )

    @property
    def alias_names(self) -> list[str]:
        return [a.alias for a in self.aliases]


class ArtistAlias(CreatedMixin, Base):
    __tablename__ = "artist_aliases"
    __table_args__ = (UniqueConstraint("artist_id", "alias_norm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    alias_norm: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="user")

    artist: Mapped[Artist] = relationship(back_populates="aliases")


class UserArtist(TimestampMixin, Base):
    """A user's subscription to an artist incl. personal settings."""

    __tablename__ = "user_artists"
    __table_args__ = (UniqueConstraint("user_id", "artist_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_festivals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    baseline_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="subscriptions")
    artist: Mapped[Artist] = relationship(lazy="joined")
