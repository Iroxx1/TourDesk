"""Künstlerkatalog: bekannte Künstler je Genre aus MusicBrainz (zum Stöbern und Hinzufügen)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from tourdesk.models.base import Base, TimestampMixin


class CatalogEntry(TimestampMixin, Base):
    """One MusicBrainz artist in the browsable catalogue (shared by all users)."""

    __tablename__ = "catalog_entries"
    __table_args__ = (
        Index("ix_catalog_entries_genres", "genres", postgresql_using="gin"),
        Index("ix_catalog_entries_sort", "sort_key", "mbid"),
    )

    mbid: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    sort_name: Mapped[str] = mapped_column(String(300), nullable=False)
    # normalised sort name (lowercase, no accents) – order of the catalogue
    sort_key: Mapped[str] = mapped_column(String(300), nullable=False)
    # register letter A–Z, "#" for digits and other characters
    letter: Mapped[str] = mapped_column(String(1), nullable=False, index=True)
    kind: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(2))
    is_dach: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    begin_year: Mapped[int | None] = mapped_column(SmallInteger)
    end_year: Mapped[int | None] = mapped_column(SmallInteger)
    ended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disambiguation: Mapped[str | None] = mapped_column(String(300))
    # curated genre keys (see services/catalog_genres.py) and the rank within each genre list
    genres: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    genre_ranks: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    # most used MusicBrainz tags (shown in the detail view)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    # small picture (Deezer), fetched lazily when a catalogue page is shown
    image_path: Mapped[str | None] = mapped_column(String(255))
    image_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")  # unknown | ok | missing
    image_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ok: deezer | wikimedia – missing: deezer (nur Deezer gefragt) | all (auch Wikidata gefragt)
    image_source: Mapped[str | None] = mapped_column(String(16))
    # Bildnachweis (Seite der Datei bei Wikimedia Commons)
    image_credit: Mapped[str | None] = mapped_column(String(500))

    # detail data (website, Wikipedia text, …), fetched when the detail view is opened
    details: Mapped[dict[str, Any] | None] = mapped_column()
    details_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CatalogGenre(Base):
    """Import state of one curated genre list."""

    __tablename__ = "catalog_genres"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending | running | ok | error
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
