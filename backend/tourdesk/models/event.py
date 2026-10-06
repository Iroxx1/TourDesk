"""Events, tours, festivals and their provenance."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tourdesk.models.artist import Artist
from tourdesk.models.base import Base, TimestampMixin
from tourdesk.models.geo import City, Country, Region, Venue
from tourdesk.models.source import Source


class Tour(TimestampMixin, Base):
    __tablename__ = "tours"
    __table_args__ = (UniqueConstraint("artist_id", "name_norm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(300), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Festival(TimestampMixin, Base):
    """A festival (series). Individual appearances are events with ``festival_id``."""

    __tablename__ = "festivals"
    __table_args__ = (Index("ix_festivals_aliases_norm", "aliases_norm", postgresql_using="gin"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    aliases_norm: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"), index=True)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id", ondelete="SET NULL"), index=True)
    website: Mapped[str | None] = mapped_column(String(500))
    typical_month: Mapped[int | None] = mapped_column(SmallInteger)
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    city: Mapped[City | None] = relationship(lazy="joined")
    venue: Mapped[Venue | None] = relationship(lazy="joined")


class Event(TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_artist_date", "artist_id", "event_date"),
        Index("ix_events_event_date", "event_date"),
        Index("ix_events_listing", "is_listed", "is_confirmed", "event_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"), nullable=False)
    tour_id: Mapped[int | None] = mapped_column(ForeignKey("tours.id", ondelete="SET NULL"), index=True)
    festival_id: Mapped[int | None] = mapped_column(ForeignKey("festivals.id", ondelete="SET NULL"), index=True)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id", ondelete="SET NULL"), index=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"), index=True)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id", ondelete="SET NULL"), index=True)
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id", ondelete="SET NULL"), index=True)

    title: Mapped[str | None] = mapped_column(String(500))
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time)
    doors_time: Mapped[time | None] = mapped_column(Time)
    timezone: Mapped[str | None] = mapped_column(String(64))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event_type: Mapped[str] = mapped_column(String(16), nullable=False, default="concert")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    ticket_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    ticket_url: Mapped[str | None] = mapped_column(String(1000))
    ticket_provider: Mapped[str | None] = mapped_column(String(100))
    onsale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # display fallbacks (raw names when no catalogue entry could be resolved)
    venue_name: Mapped[str | None] = mapped_column(String(200))
    city_name: Mapped[str | None] = mapped_column(String(160))
    country_code: Mapped[str | None] = mapped_column(String(2))

    is_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    source_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    best_trust: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=6)
    is_listed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    primary_source_url: Mapped[str | None] = mapped_column(String(1000))
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    artist: Mapped[Artist] = relationship(lazy="joined")
    tour: Mapped[Tour | None] = relationship(lazy="joined")
    festival: Mapped[Festival | None] = relationship(lazy="joined")
    venue: Mapped[Venue | None] = relationship(lazy="joined")
    city: Mapped[City | None] = relationship(lazy="joined")
    region: Mapped[Region | None] = relationship(lazy="joined")
    country: Mapped[Country | None] = relationship(lazy="joined")
    observations: Mapped[list[EventSource]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )
    tickets: Mapped[list[TicketSource]] = relationship(
        back_populates="event", cascade="all, delete-orphan", passive_deletes=True
    )


class EventSource(Base):
    """One observation of an event by one source (provenance)."""

    __tablename__ = "event_sources"
    __table_args__ = (
        UniqueConstraint("source_id", "obs_key"),
        Index("ix_event_sources_source_active", "source_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    obs_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    trust_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=6)
    domain: Mapped[str | None] = mapped_column(String(253))
    external_id: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(1000))
    raw_title: Mapped[str | None] = mapped_column(String(500))
    raw_venue: Mapped[str | None] = mapped_column(String(300))
    raw_city: Mapped[str | None] = mapped_column(String(200))
    raw_date: Mapped[str | None] = mapped_column(String(100))
    data: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inactive_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    event: Mapped[Event] = relationship(back_populates="observations")
    source: Mapped[Source] = relationship(lazy="joined")


class TicketSource(Base):
    """Ticket offer/link of one provider for an event (prepared for price monitoring)."""

    __tablename__ = "ticket_sources"
    __table_args__ = (UniqueConstraint("event_id", "url"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    trust_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=6)
    price_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    event: Mapped[Event] = relationship(back_populates="tickets")
