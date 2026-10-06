"""Events embedded as JSON in pages (Next.js/Nuxt state, widget payloads, APIs).

Many tour pages are rendered by JavaScript. Their data frequently ships inside the
HTML (``__NEXT_DATA__``, ``window.__INITIAL_STATE__`` …) or comes from JSON APIs.
This module walks arbitrary JSON and picks objects that look like events.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from tourdesk.core.text import clean_text, safe_url
from tourdesk_crawler.extract.dates import parse_iso_datetime
from tourdesk_crawler.pipeline.models import RawEvent

DATE_KEYS = (
    "startDate", "start_date", "startsAt", "starts_at", "start", "datetime", "dateTime", "date", "eventDate", "event_date",
    "localDate", "starts-at-date-local", "startsAtDateLocal", "start_at", "date_local", "showDate",
)
TIME_KEYS = ("startTime", "start_time", "localTime", "time", "showTime", "doorsTime")
VENUE_KEYS = ("venue", "location", "place", "venueName", "venue_name", "venue-name", "locationName")
TITLE_KEYS = ("title", "name", "displayName", "eventName", "event_name", "headline")
URL_KEYS = ("url", "uri", "link", "eventUrl", "event_url", "permalink", "href")
TICKET_KEYS = ("ticketUrl", "ticket_url", "ticketLink", "ticket_link", "tickets", "ticketsUrl", "buyUrl", "offers", "ticket-link")
STATUS_KEYS = ("status", "eventStatus", "state")
MAX_NODES = 50_000

_SCRIPT_STATE = re.compile(
    r"(?:window\.)?(?:__INITIAL_STATE__|__NUXT__|__APOLLO_STATE__|__PRELOADED_STATE__|INITIAL_DATA|__DATA__)\s*=\s*(\{.*?\})\s*;?\s*(?:</script>|$)",
    re.S,
)


def _str(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    return clean_text(str(value), 300)


def _date_value(obj: dict) -> tuple[Any, str] | None:
    for key in DATE_KEYS:
        if key in obj:
            value = obj[key]
            if isinstance(value, dict):
                for sub in ("datetime", "date", "localDate", "dateTime"):
                    if isinstance(value.get(sub), str):
                        return value, sub
                continue
            if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value.strip()):
                return obj, key
    return None


def _looks_like_event(obj: dict) -> bool:
    if _date_value(obj) is None:
        return False
    return any(k in obj for k in VENUE_KEYS) or any(k in obj for k in ("city", "location", "venue"))


def _venue(obj: dict, ev: RawEvent) -> None:
    for key in VENUE_KEYS:
        value = obj.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            ev.venue_name = ev.venue_name or clean_text(value, 200)
        elif isinstance(value, dict):
            ev.venue_name = ev.venue_name or _str(value.get("name") or value.get("displayName") or value.get("title"))
            city = value.get("city") or value.get("locality") or value.get("addressLocality")
            if isinstance(city, dict):
                city = city.get("name") or city.get("displayName")
            ev.city = ev.city or _str(city)
            region = value.get("region") or value.get("state") or value.get("addressRegion")
            if isinstance(region, dict):
                region = region.get("name") or region.get("stateCode")
            ev.region = ev.region or _str(region)
            country = value.get("country") or value.get("countryCode") or value.get("addressCountry")
            if isinstance(country, dict):
                country = country.get("countryCode") or country.get("name") or country.get("displayName")
            ev.country = ev.country or _str(country)
            metro = value.get("metroArea")
            if isinstance(metro, dict):
                ev.city = ev.city or _str(metro.get("displayName"))
                c = metro.get("country")
                if isinstance(c, dict):
                    ev.country = ev.country or _str(c.get("displayName"))
            for lat_key, lon_key in (("latitude", "longitude"), ("lat", "lng"), ("lat", "lon")):
                try:
                    if value.get(lat_key) is not None and value.get(lon_key) is not None:
                        ev.latitude, ev.longitude = float(value[lat_key]), float(value[lon_key])
                        break
                except (TypeError, ValueError):
                    pass
            address = value.get("address") or value.get("formattedAddress") or value.get("formatted-address")
            if isinstance(address, str):
                ev.venue_address = ev.venue_address or clean_text(address, 300)
            elif isinstance(address, dict):
                ev.city = ev.city or _str(address.get("addressLocality") or address.get("city"))
                ev.country = ev.country or _str(address.get("addressCountry") or address.get("country"))
    for key in ("city", "cityName", "town"):
        if not ev.city and obj.get(key):
            ev.city = _str(obj[key]) if not isinstance(obj[key], dict) else _str(obj[key].get("name"))
    for key in ("country", "countryCode", "country_code"):
        if not ev.country and obj.get(key):
            ev.country = _str(obj[key]) if not isinstance(obj[key], dict) else _str(obj[key].get("name") or obj[key].get("countryCode"))
    if not ev.city and isinstance(obj.get("location"), dict):
        loc = obj["location"]
        ev.city = _str(loc.get("city"))
    if not ev.city and isinstance(obj.get("location"), str) and "," in obj["location"]:
        parts = [p.strip() for p in obj["location"].split(",")]
        ev.city, ev.country = clean_text(parts[0], 160), clean_text(parts[-1], 60)


def _performers(obj: dict) -> list[str]:
    out: list[str] = []
    for key in ("lineup", "performers", "performer", "artists", "performance", "acts"):
        value = obj.get(key)
        items = value if isinstance(value, list) else [value] if value else []
        for item in items:
            name = None
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                name = item.get("name") or item.get("displayName")
                if not name and isinstance(item.get("artist"), dict):
                    name = item["artist"].get("name") or item["artist"].get("displayName")
            name = clean_text(name, 200) if name else None
            if name and name not in out:
                out.append(name)
    return out


def _ticket(obj: dict, base_url: str) -> tuple[str | None, str | None]:
    for key in TICKET_KEYS:
        value = obj.get(key)
        if isinstance(value, str):
            url = safe_url(urljoin(base_url, value))
            if url:
                return url, None
        elif isinstance(value, list):
            for offer in value:
                if isinstance(offer, dict):
                    url = offer.get("url") or offer.get("link")
                    status = str(offer.get("status") or "").casefold()
                    if url:
                        return safe_url(urljoin(base_url, str(url))), ("sold_out" if "sold" in status else "available" if status == "available" else None)
        elif isinstance(value, dict):
            url = value.get("url") or value.get("link")
            if url:
                return safe_url(urljoin(base_url, str(url))), None
    return None, None


def event_from_json(obj: dict, base_url: str) -> RawEvent | None:
    found = _date_value(obj)
    if found is None:
        return None
    holder, key = found
    start_d, start_t, tz = parse_iso_datetime(str(holder[key]))
    if start_d is None:
        return None
    if start_t is None:
        for tkey in TIME_KEYS:
            value = obj.get(tkey) or (holder.get(tkey) if isinstance(holder, dict) else None)
            if isinstance(value, str) and re.match(r"^\d{1,2}:\d{2}", value):
                h, m = value.split(":")[:2]
                from datetime import time

                try:
                    start_t = time(int(h), int(m[:2]))
                except ValueError:
                    pass
                break
    ev = RawEvent(start_date=start_d, start_time=start_t, method="embedded", confidence=0.75, raw_date=str(holder[key]))
    ev.extra["tzinfo"] = tz
    for tk in TITLE_KEYS:
        if isinstance(obj.get(tk), str):
            ev.title = clean_text(obj[tk], 300)
            break
    _venue(obj, ev)
    ev.performers = _performers(obj)
    for uk in URL_KEYS:
        if isinstance(obj.get(uk), str):
            ev.url = safe_url(urljoin(base_url, obj[uk]))
            if ev.url:
                break
    ev.ticket_url, ticket_status = _ticket(obj, base_url)
    ev.ticket_status = ticket_status
    for sk in STATUS_KEYS:
        status = str(obj.get(sk) or "").casefold()
        if "cancel" in status:
            ev.status = "cancelled"
        elif "postpon" in status:
            ev.status = "postponed"
        elif "reschedul" in status:
            ev.status = "rescheduled"
        if ev.status:
            break
    if obj.get("soldOut") is True or obj.get("sold_out") is True or obj.get("isSoldOut") is True:
        ev.ticket_status = "sold_out"
    kind = str(obj.get("type") or obj.get("eventType") or "").casefold()
    if "festival" in kind or obj.get("festival_name") or obj.get("festivalName"):
        ev.event_type_hint = "festival"
        ev.festival_name = clean_text(str(obj.get("festival_name") or obj.get("festivalName") or ev.title or ""), 200)
    end = obj.get("endDate") or obj.get("end_date") or obj.get("festival_end_date")
    if isinstance(end, str):
        end_d, _, _ = parse_iso_datetime(end)
        if end_d and end_d != start_d:
            ev.end_date = end_d
    ident = obj.get("id") or obj.get("uuid") or obj.get("eventId")
    if isinstance(ident, (str, int)):
        ev.external_id = str(ident)[:200]
    return ev


def walk_json(data: Any, base_url: str, *, limit: int = 500) -> list[RawEvent]:
    events: list[RawEvent] = []
    seen = 0
    stack = [data]
    while stack and seen < MAX_NODES and len(events) < limit:
        node = stack.pop()
        seen += 1
        if isinstance(node, dict):
            if _looks_like_event(node):
                ev = event_from_json(node, base_url)
                if ev is not None:
                    events.append(ev)
                    continue
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            stack.extend(v for v in node if isinstance(v, (dict, list)))
    events.reverse()
    return events


def extract_embedded(soup: BeautifulSoup, base_url: str, raw_html: str | None = None) -> list[RawEvent]:
    payloads: list[Any] = []
    for script in soup.find_all("script"):
        stype = str(script.get("type") or "").lower()
        content = script.string or ""
        if not content.strip():
            continue
        if script.get("id") == "__NEXT_DATA__" or stype in ("application/json",):
            try:
                payloads.append(json.loads(content))
            except json.JSONDecodeError:
                continue
        elif not stype or "javascript" in stype:
            for m in _SCRIPT_STATE.finditer(content):
                try:
                    payloads.append(json.loads(m.group(1)))
                except json.JSONDecodeError:
                    continue
    events: list[RawEvent] = []
    for payload in payloads:
        events.extend(walk_json(payload, base_url))
    return events
