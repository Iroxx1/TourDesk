"""Crawl sources (artist-, venue-, festival- and global sources) incl. health state.

The table ``sources`` with ``scope = 'artist'`` is what the requirements call
``artist_sources``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tourdesk.models.base import Base, TimestampMixin


class Source(TimestampMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (
        Index("ix_sources_scope_enabled", "scope", "is_enabled"),
        Index("ix_sources_next_attempt", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    artist_id: Mapped[int | None] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), index=True)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), index=True)
    festival_id: Mapped[int | None] = mapped_column(ForeignKey("festivals.id", ondelete="CASCADE"), index=True)
    trust_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=6)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    crawl_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    # health
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_type: Mapped[str | None] = mapped_column(String(32))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    last_event_count: Mapped[int | None] = mapped_column(Integer)
    last_method: Mapped[str | None] = mapped_column(String(32))
