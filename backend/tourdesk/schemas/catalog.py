"""Künstlerkatalog (API-Schemas)."""

from __future__ import annotations

from datetime import datetime

from tourdesk.schemas.common import ApiModel


class CatalogGenreOut(ApiModel):
    key: str
    label: str
    count: int


class CatalogProgress(ApiModel):
    done: int
    total: int


class CatalogMetaOut(ApiModel):
    total: int
    ready: bool
    importing: bool
    progress: CatalogProgress
    imported_at: datetime | None = None
    genres: list[CatalogGenreOut]
    dach_total: int


class CatalogEntryOut(ApiModel):
    mbid: str
    name: str
    sort_name: str
    letter: str
    kind: str | None = None
    country: str | None = None
    begin_year: int | None = None
    end_year: int | None = None
    ended: bool = False
    disambiguation: str | None = None
    genres: list[str]
    genre_keys: list[str]
    image: str  # ok | missing | unknown
    artist_id: int | None = None
    followed: bool = False


class CatalogPageOut(ApiModel):
    page: int
    per_page: int
    pages: int
    total: int
    letters: dict[str, int | None]
    items: list[CatalogEntryOut]


class CatalogDetailOut(CatalogEntryOut):
    tags: list[str]
    website: str | None = None
    wikipedia_url: str | None = None
    description: str | None = None
    description_lang: str | None = None
    musicbrainz_url: str
