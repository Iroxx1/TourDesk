"""Plain data structures passed through the crawl pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any


@dataclass
class RawEvent:
    """An event as found on a page/API, before normalisation."""

    start_date: date | None = None
    title: str | None = None
    performers: list[str] = field(default_factory=list)
    start_time: time | None = None
    end_date: date | None = None
    doors_time: time | None = None
    timezone: str | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    postal_code: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    url: str | None = None
    ticket_url: str | None = None
    ticket_status: str | None = None
    ticket_provider: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    onsale_at: datetime | None = None
    status: str | None = None
    event_type_hint: str | None = None  # festival | support | special
    festival_name: str | None = None
    tour_name: str | None = None
    external_id: str | None = None
    description: str | None = None
    raw_date: str | None = None
    method: str = "unknown"
    confidence: float = 0.5
    role: str | None = None  # headliner | support | festival (set by matcher/provider)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtistSpec:
    id: int
    name: str
    aliases: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
    official_website: str | None = None
    external_ids: dict[str, Any] = field(default_factory=dict)
    is_demo: bool = False

    @property
    def all_names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class VenueSpec:
    id: int
    name: str
    city_id: int | None
    city_name: str | None
    country_code: str | None
    website: str | None = None


@dataclass(frozen=True)
class FestivalSpec:
    id: int
    name: str
    aliases: tuple[str, ...]
    city_id: int | None
    city_name: str | None
    venue_id: int | None
    venue_name: str | None
    country_code: str | None
    website: str | None
    typical_month: int | None


@dataclass(frozen=True)
class SourceSpec:
    id: int
    scope: str
    provider: str
    name: str
    url: str | None
    trust_level: int
    config: dict[str, Any]
    artist_id: int | None = None
    venue: VenueSpec | None = None
    festival: FestivalSpec | None = None


@dataclass
class NormalizedEvent:
    artist_id: int
    event_date: date
    obs_key: str
    dedup_key: str
    title: str | None = None
    end_date: date | None = None
    start_time: time | None = None
    doors_time: time | None = None
    timezone: str | None = None
    venue_id: int | None = None
    venue_name: str | None = None
    city_id: int | None = None
    city_name: str | None = None
    region_id: int | None = None
    country_id: int | None = None
    country_code: str | None = None
    event_type: str = "concert"
    status: str = "scheduled"
    ticket_status: str = "unknown"
    ticket_url: str | None = None
    ticket_provider: str | None = None
    onsale_at: datetime | None = None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    tour_name: str | None = None
    festival_id: int | None = None
    url: str | None = None
    external_id: str | None = None
    confidence: float = 0.5
    method: str = "unknown"
    raw_title: str | None = None
    raw_venue: str | None = None
    raw_city: str | None = None
    raw_date: str | None = None

    def data(self) -> dict[str, Any]:
        """Serialisable observation payload stored in ``event_sources.data``."""
        return {
            "date": self.event_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "start_time": self.start_time.strftime("%H:%M") if self.start_time else None,
            "doors_time": self.doors_time.strftime("%H:%M") if self.doors_time else None,
            "timezone": self.timezone,
            "venue_id": self.venue_id,
            "venue_name": self.venue_name,
            "city_id": self.city_id,
            "city_name": self.city_name,
            "region_id": self.region_id,
            "country_id": self.country_id,
            "country_code": self.country_code,
            "title": self.title,
            "event_type": self.event_type,
            "status": self.status,
            "ticket_status": self.ticket_status,
            "ticket_url": self.ticket_url,
            "ticket_provider": self.ticket_provider,
            "onsale_at": self.onsale_at.isoformat() if self.onsale_at else None,
            "price_min": self.price_min,
            "price_max": self.price_max,
            "currency": self.currency,
            "tour_name": self.tour_name,
            "festival_id": self.festival_id,
            "url": self.url,
            "confidence": self.confidence,
            "method": self.method,
        }


@dataclass
class ProviderResult:
    events: list[RawEvent] = field(default_factory=list)
    method: str | None = None
    pages: int = 0
    http_status: int | None = None
    warnings: list[str] = field(default_factory=list)
    discovered: dict[str, Any] = field(default_factory=dict)
    artist_updates: dict[str, Any] = field(default_factory=dict)
    lineup: list[str] = field(default_factory=list)  # festival line-ups
