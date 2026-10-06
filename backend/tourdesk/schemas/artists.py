"""Schemas for artists, subscriptions, sources, events and dashboard tiles."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from pydantic import Field, field_validator

from tourdesk.schemas.common import ApiModel, CleanStr, HttpUrl


def _clean_list(values: list[str] | None, max_items: int = 30, max_len: int = 200) -> list[str] | None:
    if values is None:
        return None
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        v = (v or "").strip()
        if not v or len(v) > max_len:
            continue
        key = v.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out[:max_items]


class SubscriptionOut(ApiModel):
    is_active: bool
    show_festivals: bool
    notify: bool
    pinned: bool
    sort_order: int
    created_at: datetime


class ArtistImages(ApiModel):
    thumb: str | None = None
    tile: str | None = None
    hero: str | None = None
    source: str | None = None
    source_url: str | None = None


class ArtistOut(ApiModel):
    id: int
    name: str
    slug: str
    genre: str | None = None
    country_code: str | None = None
    official_website: str | None = None
    aliases: list[str] = []
    search_terms: list[str] = []
    external_ids: dict[str, Any] = {}
    images: ArtistImages
    is_demo: bool = False
    crawl_status: str
    last_crawled_at: datetime | None = None
    last_success_at: datetime | None = None
    next_crawl_at: datetime | None = None
    last_error: str | None = None
    subscription: SubscriptionOut | None = None
    can_edit: bool = True


class ArtistCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    official_website: HttpUrl = None
    genre: CleanStr = Field(default=None, max_length=100)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    search_terms: list[str] = Field(default_factory=list, max_length=30)
    show_festivals: bool | None = None
    musicbrainz_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    artist_id: int | None = None  # follow an existing catalogue entry

    @field_validator("aliases", "search_terms")
    @classmethod
    def _lists(cls, v: list[str]) -> list[str]:
        return _clean_list(v) or []

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Bitte einen Namen angeben")
        return v


class ArtistUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    genre: CleanStr = Field(default=None, max_length=100)
    official_website: HttpUrl = None
    aliases: list[str] | None = Field(default=None, max_length=30)
    search_terms: list[str] | None = Field(default=None, max_length=30)
    is_active: bool | None = None
    show_festivals: bool | None = None
    notify: bool | None = None
    pinned: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("aliases", "search_terms")
    @classmethod
    def _lists(cls, v: list[str] | None) -> list[str] | None:
        return _clean_list(v)


class ArtistLookupItem(ApiModel):
    source: str  # catalog | musicbrainz
    name: str
    disambiguation: str | None = None
    country: str | None = None
    kind: str | None = None
    musicbrainz_id: str | None = None
    artist_id: int | None = None
    followed: bool = False
    genre: str | None = None
    score: int | None = None


class SourceOut(ApiModel):
    id: int
    scope: str
    provider: str
    provider_label: str
    name: str
    url: str | None = None
    trust_level: int
    trust_label: str
    is_enabled: bool
    is_auto: bool
    status: str
    artist_id: int | None = None
    artist_name: str | None = None
    venue_id: int | None = None
    venue_name: str | None = None
    festival_id: int | None = None
    festival_name: str | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    last_error_type: str | None = None
    consecutive_failures: int = 0
    total_failures: int = 0
    total_runs: int = 0
    next_attempt_at: datetime | None = None
    last_http_status: int | None = None
    last_duration_ms: int | None = None
    last_event_count: int | None = None
    last_method: str | None = None
    config: dict[str, Any] = {}
    can_delete: bool = False


class SourceCreate(ApiModel):
    url: HttpUrl
    name: CleanStr = Field(default=None, max_length=200)
    provider: str = Field(default="tour_page", max_length=50)

    @field_validator("url")
    @classmethod
    def _required(cls, v: str | None) -> str:
        if not v:
            raise ValueError("Bitte eine URL angeben")
        return v


class NamedRef(ApiModel):
    id: int
    name: str


class CountryRef(ApiModel):
    id: int
    code: str
    name: str


class EventOut(ApiModel):
    id: int
    artist_id: int
    artist_name: str
    title: str | None = None
    date: date
    end_date: date | None = None
    start_time: time | None = None
    doors_time: time | None = None
    timezone: str | None = None
    event_type: str
    status: str
    ticket_status: str
    ticket_url: str | None = None
    ticket_provider: str | None = None
    onsale_at: datetime | None = None
    venue: NamedRef | None = None
    venue_name: str | None = None
    city: NamedRef | None = None
    city_name: str | None = None
    region: NamedRef | None = None
    country: CountryRef | None = None
    tour: NamedRef | None = None
    festival: NamedRef | None = None
    is_confirmed: bool
    confidence: float
    source_count: int
    best_trust: int
    is_listed: bool
    primary_source_url: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    last_checked_at: datetime | None = None
    updated_at: datetime
    matches: bool | None = None
    hidden_reason: str | None = None


class EventSourceOut(ApiModel):
    provider: str
    provider_label: str
    source_name: str
    url: str | None = None
    domain: str | None = None
    trust_level: int
    trust_label: str
    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime


class TicketOut(ApiModel):
    provider: str
    url: str
    status: str
    trust_level: int
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    is_active: bool


class EventDetailOut(EventOut):
    sources: list[EventSourceOut] = []
    tickets: list[TicketOut] = []
    explanation: dict[str, Any] | None = None
    artist_image: str | None = None


class TourStatusOut(ApiModel):
    state: str
    label: str
    emoji: str
    detail: str
    tour_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    event_count: int = 0
    upcoming_count: int = 0
    next_date: date | None = None
    festival_only: bool = False


class TileOut(ApiModel):
    artist: ArtistOut
    tour_status: TourStatusOut
    matching_events: list[EventOut]
    matching_count: int
    more_count: int
    total_upcoming: int
    festival_upcoming: int
    hidden_festivals: int
    outside_filters: int
    last_updated: datetime | None = None


class DashboardOut(ApiModel):
    tiles: list[TileOut]
    total_matching: int
    generated_at: datetime
    has_location_rules: bool
    crawler_last_run: datetime | None = None


class ArtistEventsOut(ApiModel):
    artist_id: int
    tour_status: TourStatusOut
    matching: list[EventOut]
    all_events: list[EventOut]
    past_events: list[EventOut]
    tours: list[NamedRef]
