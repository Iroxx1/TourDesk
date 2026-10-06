"""Geography: countries → regions (hierarchical) → cities → venues."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tourdesk.models.base import Base, CreatedMixin, TimestampMixin


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(2), nullable=False, unique=True)
    code3: Mapped[str | None] = mapped_column(String(3))
    name_de: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    aliases_norm: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    continent: Mapped[str | None] = mapped_column(String(2))
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=100)

    @property
    def name(self) -> str:
        return self.name_de


class Region(Base):
    __tablename__ = "regions"
    __table_args__ = (
        UniqueConstraint("country_id", "name_norm"),
        Index("ix_regions_aliases_norm", "aliases_norm", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id", ondelete="SET NULL"), index=True)
    code: Mapped[str | None] = mapped_column(String(16), unique=True)
    geonames_code: Mapped[str | None] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    name_de: Mapped[str | None] = mapped_column(String(150))
    name_norm: Mapped[str] = mapped_column(String(150), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="Region")
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    aliases_norm: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    country: Mapped[Country] = relationship(lazy="joined")
    parent: Mapped[Region | None] = relationship(remote_side="Region.id")

    @property
    def display_name(self) -> str:
        return self.name_de or self.name


class City(CreatedMixin, Base):
    __tablename__ = "cities"
    __table_args__ = (
        Index("ix_cities_aliases_norm", "aliases_norm", postgresql_using="gin"),
        Index(
            "ix_cities_name_norm_trgm",
            "name_norm",
            postgresql_using="gin",
            postgresql_ops={"name_norm": "gin_trgm_ops"},
        ),
        Index("ix_cities_country_name", "country_id", "name_norm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_id: Mapped[int] = mapped_column(ForeignKey("countries.id", ondelete="CASCADE"), nullable=False)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_de: Mapped[str | None] = mapped_column(String(160))
    name_norm: Mapped[str] = mapped_column(String(160), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    aliases_norm: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    population: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timezone: Mapped[str | None] = mapped_column(String(64))
    geonames_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    country: Mapped[Country] = relationship(lazy="joined")
    region: Mapped[Region | None] = relationship(lazy="joined")

    @property
    def display_name(self) -> str:
        return self.name_de or self.name


class Venue(TimestampMixin, Base):
    __tablename__ = "venues"
    __table_args__ = (
        Index("ix_venues_aliases_norm", "aliases_norm", postgresql_using="gin"),
        Index(
            "ix_venues_name_norm_trgm",
            "name_norm",
            postgresql_using="gin",
            postgresql_ops={"name_norm": "gin_trgm_ops"},
        ),
        Index("ix_venues_city_name", "city_id", "name_norm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    aliases_norm: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    address: Mapped[str | None] = mapped_column(String(300))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    website: Mapped[str | None] = mapped_column(String(500))
    capacity: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str | None] = mapped_column(String(32))
    is_auto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    extra: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)

    city: Mapped[City | None] = relationship(lazy="joined")
