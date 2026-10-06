"""EventNormalizer: RawEvent -> NormalizedEvent (resolved location, type, status …)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from tourdesk.core.text import clean_text, normalize_name, safe_url
from tourdesk.core.timeutil import safe_zone
from tourdesk.models import City
from tourdesk_crawler.extract.dates import to_local
from tourdesk_crawler.pipeline.geo_resolver import GeoResolver
from tourdesk_crawler.pipeline.models import ArtistSpec, NormalizedEvent, RawEvent, SourceSpec
from tourdesk_crawler.pipeline.tickets import (
    detect_statuses,
    normalize_event_status,
    normalize_ticket_status,
    ticket_provider_for,
)

SPECIAL_RE = re.compile(
    r"\b(special event|fan ?event|fanclub|meet\s*&?\s*greet|album release|release party|record release|listening session|"
    r"acoustic|akustik|unplugged|intimate show|secret show|livestream|live stream|signing|autogramm|in conversation|"
    r"q&a|private show|showcase|club show|warm[- ]?up show|benefiz|charity)\b",
    re.I,
)
FESTIVAL_RE = re.compile(r"\b(festival|open[\s-]?air|openair|fest\b|rock am ring|rock im park|wacken|hellfest|graspop|tomorrowland)", re.I)
TOUR_RE = re.compile(r"(?:^|[:\-–|]\s*)([^:\-–|]{2,70}?\b(?:world\s+)?tour(?:nee|née)?(?:\s+(?:20\d\d|'\d\d))?)\b", re.I)
GENERIC_TOUR = {"tour", "world tour", "tournee", "tournée", "live tour", "the tour", "on tour", "tour dates"}
MAX_PAST = timedelta(days=400)
MAX_FUTURE = timedelta(days=365 * 3)


@dataclass
class NormalizeContext:
    artist: ArtistSpec
    source: SourceSpec
    today: date
    geo: GeoResolver
    role: str | None = None  # from the matcher (headliner/support/festival/unknown)


def extract_tour_name(title: str | None, artist: ArtistSpec) -> str | None:
    if not title:
        return None
    text = title
    for name in artist.all_names:
        text = re.sub(rf"^\s*{re.escape(name)}\s*[:\-–|]?\s*", "", text, flags=re.I)
    m = TOUR_RE.search(text) or TOUR_RE.search(title)
    if not m:
        return None
    name = clean_text(m.group(1).strip(" -–:|"), 200)
    if not name or normalize_name(name) in GENERIC_TOUR or normalize_name(name) in {normalize_name(n) for n in artist.all_names}:
        return None
    # "Metallica M72 World Tour" -> "M72 World Tour"
    for artist_name in artist.all_names:
        if name.casefold().startswith(artist_name.casefold() + " "):
            name = name[len(artist_name) + 1 :]
    return name.strip() or None


def classify(raw: RawEvent, ctx: NormalizeContext, festival_id: int | None) -> str:
    text = " ".join(x for x in (raw.title, raw.venue_name, raw.description) if x)
    if festival_id or raw.event_type_hint == "festival" or ctx.source.scope == "festival" or raw.role == "festival" or ctx.role == "festival":
        return "festival"
    if raw.title and FESTIVAL_RE.search(raw.title) and not re.search(r"\btour\b", raw.title, re.I):
        return "festival"
    role = ctx.role or raw.role
    if role == "support" or raw.event_type_hint == "support" or (raw.extra.get("support_hint") and role != "headliner"):
        return "support"
    if raw.event_type_hint == "special" or (text and SPECIAL_RE.search(text)):
        return "special"
    return "concert"


def normalize(raw: RawEvent, ctx: NormalizeContext) -> tuple[NormalizedEvent | None, str | None]:
    """Return ``(event, None)`` or ``(None, reason)``."""
    if raw.start_date is None:
        return None, "kein Datum"
    if raw.start_date < ctx.today - MAX_PAST or raw.start_date > ctx.today + MAX_FUTURE:
        return None, "Datum außerhalb des sinnvollen Bereichs"
    if raw.extra.get("online"):
        return None, "Online-Event"

    geo = ctx.geo
    source = ctx.source
    venue = city = None
    region_id = country_id = None
    country_code = None
    venue_name = clean_text(raw.venue_name, 200)
    city_name = clean_text(raw.city, 160)

    if source.venue is not None:
        # venue agenda: the location is the venue itself
        from tourdesk.models import Venue

        venue = geo.db.get(Venue, source.venue.id)
        city = geo.db.get(City, venue.city_id) if venue and venue.city_id else None
    elif source.festival is not None and (raw.event_type_hint == "festival" or not (venue_name or city_name)):
        from tourdesk.models import Venue

        if source.festival.venue_id:
            venue = geo.db.get(Venue, source.festival.venue_id)
        if source.festival.city_id:
            city = geo.db.get(City, source.festival.city_id)
    if venue is None and city is None:
        loc = geo.resolve(
            venue_name=venue_name,
            city_name=city_name,
            region_name=clean_text(raw.region, 100),
            country_value=clean_text(raw.country, 60),
            lat=raw.latitude,
            lon=raw.longitude,
            address=raw.venue_address,
            postal_code=raw.postal_code,
        )
        venue, city = loc.venue, loc.city
        region_id = loc.region_id
        country_id = loc.country.id if loc.country else None
        country_code = loc.country.code if loc.country else None
    if city is None and venue is not None and venue.city_id:
        city = geo.db.get(City, venue.city_id)
    if city is not None:
        region_id = city.region_id
        country_id = city.country_id
        c = geo.country_by_id(city.country_id)
        country_code = c.code if c else country_code

    festival = None
    if source.festival is not None:
        from tourdesk.models import Festival

        festival = geo.db.get(Festival, source.festival.id)
    elif raw.festival_name or raw.event_type_hint == "festival":
        festival = geo.festival(raw.festival_name or raw.title, city=city, venue=venue)
        if festival is not None:
            from tourdesk.models import Venue

            if venue is None and festival.venue_id and (city is None or city.id == festival.city_id):
                venue = geo.db.get(Venue, festival.venue_id)
            if city is None and festival.city_id:
                city = geo.db.get(City, festival.city_id)
            if city is not None:
                region_id, country_id = city.region_id, city.country_id

    tz_name = city.timezone if city else None
    start_date, start_time = raw.start_date, raw.start_time
    tzinfo = raw.extra.pop("tzinfo", None)
    if tzinfo is not None and start_time is not None and tz_name:
        start_date, start_time = to_local(start_date, start_time, tzinfo, tz_name)

    text_for_status = " ".join(x for x in (raw.title, raw.description) if x)
    status_hint, ticket_hint = detect_statuses(text_for_status) if text_for_status else (None, None)
    status = normalize_event_status(raw.status) if raw.status else (status_hint or "scheduled")
    ticket_status = normalize_ticket_status(raw.ticket_status) if raw.ticket_status else (ticket_hint or "unknown")
    if status == "cancelled":
        ticket_status = "cancelled" if ticket_status in ("unknown", "available") else ticket_status

    ticket_url = safe_url(raw.ticket_url)
    provider, _resale = ticket_provider_for(ticket_url)
    ticket_provider = clean_text(raw.ticket_provider, 100) or provider
    if ticket_url and ticket_status == "unknown":
        ticket_status = "available"

    event_type = classify(raw, ctx, festival.id if festival else None)
    # only the artist's own concerts belong to a tour (support slots are part of the headliner's tour)
    tour_name = None
    if event_type == "concert":
        tour_name = clean_text(raw.tour_name, 200) or extract_tour_name(raw.title, ctx.artist)

    loc_key = (
        f"v{venue.id}" if venue else f"c{city.id}" if city else normalize_name(venue_name or city_name or "")[:60] or "unknown"
    )
    if raw.external_id:
        obs_key = f"{ctx.artist.id}:x:{raw.external_id}"[:255]
    else:
        obs_key = f"{ctx.artist.id}:{start_date.isoformat()}:{loc_key}"[:255]
    dedup_key = f"{ctx.artist.id}|{start_date.isoformat()}|{loc_key}"[:255]

    title = clean_text(raw.title, 300)
    norm = NormalizedEvent(
        artist_id=ctx.artist.id,
        event_date=start_date,
        obs_key=obs_key,
        dedup_key=dedup_key,
        title=title,
        end_date=raw.end_date if raw.end_date and raw.end_date > start_date else None,
        start_time=start_time,
        doors_time=raw.doors_time,
        timezone=tz_name if safe_zone(tz_name) else None,
        venue_id=venue.id if venue else None,
        venue_name=venue.name if venue else venue_name,
        city_id=city.id if city else None,
        city_name=city.display_name if city else city_name,
        region_id=region_id,
        country_id=country_id,
        country_code=country_code,
        event_type=event_type,
        status=status,
        ticket_status=ticket_status,
        ticket_url=ticket_url,
        ticket_provider=ticket_provider,
        onsale_at=raw.onsale_at,
        price_min=raw.price_min,
        price_max=raw.price_max,
        currency=raw.currency,
        tour_name=tour_name,
        festival_id=festival.id if festival else None,
        url=safe_url(raw.url),
        external_id=raw.external_id,
        confidence=raw.confidence,
        method=raw.method,
        raw_title=clean_text(raw.title, 500),
        raw_venue=clean_text(raw.venue_name, 300),
        raw_city=clean_text(raw.city, 200),
        raw_date=clean_text(raw.raw_date, 100),
    )
    return norm, None
