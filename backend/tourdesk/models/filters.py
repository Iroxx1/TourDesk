"""Filter profiles and hierarchical location rules (country / region / city / venue)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tourdesk.models.base import Base, CreatedMixin, TimestampMixin
from tourdesk.models.geo import City, Country, Region, Venue

if TYPE_CHECKING:
    from tourdesk.models.user import User


class UserFilter(TimestampMixin, Base):
    """A filter profile. Currently one ("Standard") per user; the schema already
    supports several profiles per user."""

    __tablename__ = "user_filters"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="Standard")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    date_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="upcoming")
    months_ahead: Mapped[int | None] = mapped_column(SmallInteger)
    date_from: Mapped[date | None] = mapped_column(Date)
    date_to: Mapped[date | None] = mapped_column(Date)

    include_concerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_support: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_special: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    festival_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="artist")
    festival_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="filters")
    show_cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_unconfirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_show_festivals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped[User] = relationship(back_populates="filters")
    countries: Mapped[list[UserCountry]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    regions: Mapped[list[UserRegion]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    cities: Mapped[list[UserCity]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    venues: Mapped[list[UserVenue]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class _LocationRuleMixin(CreatedMixin):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class UserCountry(_LocationRuleMixin, Base):
    __tablename__ = "user_countries"
    __table_args__ = (UniqueConstraint("filter_id", "country_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filter_id: Mapped[int] = mapped_column(ForeignKey("user_filters.id", ondelete="CASCADE"), nullable=False)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    country: Mapped[Country] = relationship(lazy="joined")


class UserRegion(_LocationRuleMixin, Base):
    __tablename__ = "user_regions"
    __table_args__ = (UniqueConstraint("filter_id", "region_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filter_id: Mapped[int] = mapped_column(ForeignKey("user_filters.id", ondelete="CASCADE"), nullable=False)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id", ondelete="CASCADE"), nullable=False, index=True)
    region: Mapped[Region] = relationship(lazy="joined")


class UserCity(_LocationRuleMixin, Base):
    __tablename__ = "user_cities"
    __table_args__ = (UniqueConstraint("filter_id", "city_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filter_id: Mapped[int] = mapped_column(ForeignKey("user_filters.id", ondelete="CASCADE"), nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True)
    city: Mapped[City] = relationship(lazy="joined")


class UserVenue(_LocationRuleMixin, Base):
    __tablename__ = "user_venues"
    __table_args__ = (UniqueConstraint("filter_id", "venue_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filter_id: Mapped[int] = mapped_column(ForeignKey("user_filters.id", ondelete="CASCADE"), nullable=False)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    venue: Mapped[Venue] = relationship(lazy="joined")
