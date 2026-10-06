"""schema.org JSON-LD (Event / MusicEvent / Festival) extraction."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from tourdesk.core.text import clean_text, safe_url
from tourdesk_crawler.extract.dates import parse_iso_datetime
from tourdesk_crawler.pipeline.models import RawEvent

EVENT_TYPES = {
    "event", "musicevent", "festival", "comedyevent", "danceevent", "socialevent", "theaterevent", "publicationevent",
    "exhibitionevent", "screeningevent", "eventseries", "concert",
}
_STATUS = {
    "eventscheduled": "scheduled",
    "eventcancelled": "cancelled",
    "eventcanceled": "cancelled",
    "eventpostponed": "postponed",
    "eventrescheduled": "rescheduled",
    "eventmovedonline": "scheduled",
}
_AVAILABILITY = {
    "instock": "available",
    "onlineonly": "available",
    "instoreonly": "box_office",
    "limitedavailability": "limited",
    "soldout": "sold_out",
    "outofstock": "sold_out",
    "discontinued": "sold_out",
    "preorder": "presale",
    "presale": "presale",
    "backorder": "not_on_sale",
}


def _types(obj: dict) -> set[str]:
    t = obj.get("@type")
    if isinstance(t, str):
        t = [t]
    if not isinstance(t, list):
        return set()
    return {str(x).rsplit("/", 1)[-1].casefold() for x in t}


def _load_json(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("<!--"):
        raw = raw[4:]
    if raw.endswith("-->"):
        raw = raw[:-3]
    raw = raw.strip().rstrip(";")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r"[\x00-\x1f]", " ", raw)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


def iter_objects(data: Any) -> Iterator[dict]:
    if isinstance(data, list):
        for item in data:
            yield from iter_objects(item)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "itemListElement", "mainEntity", "subEvent", "event", "events", "item"):
            if key in data:
                yield from iter_objects(data[key])


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value") or value.get("text")
    return clean_text(str(value), 300) if value is not None else None


def _names(value: Any) -> list[str]:
    out: list[str] = []
    items = value if isinstance(value, list) else [value]
    for item in items:
        name = _text(item)
        if name and name not in out:
            out.append(name)
    return out


def _location(loc: Any, ev: RawEvent) -> None:
    if isinstance(loc, list):
        loc = next((x for x in loc if isinstance(x, dict) and "virtual" not in str(x.get("@type", "")).lower()), loc[0] if loc else None)
    if loc is None:
        return
    if isinstance(loc, str):
        parts = [p.strip() for p in loc.split(",") if p.strip()]
        if parts:
            ev.venue_name = clean_text(parts[0], 200)
        if len(parts) >= 2:
            ev.city = clean_text(parts[-1] if len(parts) == 2 else parts[-2], 160)
        if len(parts) >= 3:
            ev.country = clean_text(parts[-1], 60)
        return
    if not isinstance(loc, dict):
        return
    if "virtuallocation" in _types(loc):
        ev.extra["online"] = True
        return
    ev.venue_name = _text(loc.get("name"))
    addr = loc.get("address")
    if isinstance(addr, list):
        addr = addr[0] if addr else None
    if isinstance(addr, dict):
        ev.venue_address = _text(addr.get("streetAddress"))
        ev.city = _text(addr.get("addressLocality"))
        ev.region = _text(addr.get("addressRegion"))
        ev.postal_code = _text(addr.get("postalCode"))
        ev.country = _text(addr.get("addressCountry"))
    elif isinstance(addr, str):
        parts = [p.strip() for p in addr.split(",") if p.strip()]
        ev.venue_address = clean_text(parts[0], 300) if parts else None
        if len(parts) >= 2:
            city_part = parts[-2] if len(parts) >= 3 else parts[-1]
            ev.city = clean_text(re.sub(r"^\s*(?:[A-Z]{1,2}-)?\d{4,5}\s+", "", city_part), 160)
        if len(parts) >= 3:
            ev.country = clean_text(parts[-1], 60)
    geo = loc.get("geo")
    if isinstance(geo, dict):
        try:
            ev.latitude = float(geo.get("latitude"))
            ev.longitude = float(geo.get("longitude"))
        except (TypeError, ValueError):
            pass


def _offers(offers: Any, ev: RawEvent, base_url: str) -> None:
    items = offers if isinstance(offers, list) else [offers]
    for offer in items:
        if not isinstance(offer, dict):
            continue
        url = offer.get("url")
        if url and not ev.ticket_url:
            ev.ticket_url = safe_url(urljoin(base_url, str(url)))
        avail = str(offer.get("availability") or "").rsplit("/", 1)[-1].casefold()
        if avail in _AVAILABILITY and not ev.ticket_status:
            ev.ticket_status = _AVAILABILITY[avail]
        for key, attr in (("lowPrice", "price_min"), ("price", "price_min"), ("highPrice", "price_max")):
            value = offer.get(key)
            if value not in (None, "") and getattr(ev, attr) is None:
                try:
                    setattr(ev, attr, float(str(value).replace(",", ".")))
                except ValueError:
                    pass
        if offer.get("priceCurrency") and not ev.currency:
            ev.currency = str(offer["priceCurrency"])[:3].upper()
        valid_from = offer.get("validFrom")
        if valid_from and not ev.onsale_at:
            from datetime import datetime

            try:
                ev.onsale_at = datetime.fromisoformat(str(valid_from).replace("Z", "+00:00"))
            except ValueError:
                pass
        seller = offer.get("seller")
        if seller and not ev.ticket_provider:
            ev.ticket_provider = _text(seller)


def event_from_object(obj: dict, base_url: str) -> RawEvent | None:
    start_d, start_t, tz = parse_iso_datetime(obj.get("startDate") if isinstance(obj.get("startDate"), str) else None)
    if start_d is None:
        return None
    ev = RawEvent(start_date=start_d, start_time=start_t, method="jsonld", confidence=0.95)
    ev.extra["tzinfo"] = tz
    ev.raw_date = str(obj.get("startDate"))
    end_d, _end_t, _ = parse_iso_datetime(obj.get("endDate") if isinstance(obj.get("endDate"), str) else None)
    if end_d and end_d != start_d:
        ev.end_date = end_d
    door = obj.get("doorTime")
    if isinstance(door, str):
        _dd, door_t, _ = parse_iso_datetime(door if "T" in door else f"{start_d.isoformat()}T{door}")
        ev.doors_time = door_t
    ev.title = _text(obj.get("name"))
    ev.description = clean_text(str(obj.get("description") or ""), 1000)
    ev.performers = _names(obj.get("performer") or obj.get("performers"))
    _location(obj.get("location"), ev)
    _offers(obj.get("offers"), ev, base_url)
    status = str(obj.get("eventStatus") or "").rsplit("/", 1)[-1].casefold()
    ev.status = _STATUS.get(status)
    url = obj.get("url") or obj.get("@id")
    ev.url = safe_url(urljoin(base_url, str(url))) if isinstance(url, str) else None
    types = _types(obj)
    if "festival" in types:
        ev.event_type_hint = "festival"
        ev.festival_name = ev.title
    super_event = obj.get("superEvent")
    if isinstance(super_event, dict):
        name = _text(super_event.get("name"))
        if name:
            if "festival" in _types(super_event) or "festival" in name.casefold():
                ev.event_type_hint = "festival"
                ev.festival_name = name
            elif "tour" in name.casefold():
                ev.tour_name = name
    ident = obj.get("identifier")
    if isinstance(ident, (str, int)):
        ev.external_id = str(ident)[:200]
    return ev


def extract_jsonld(soup: BeautifulSoup, base_url: str) -> list[RawEvent]:
    events: list[RawEvent] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        data = _load_json(script.string or script.get_text() or "")
        if data is None:
            continue
        for obj in iter_objects(data):
            if not _types(obj) & EVENT_TYPES:
                continue
            ev = event_from_object(obj, base_url)
            if ev is not None:
                events.append(ev)
            # festivals frequently list performances as subEvents
            for sub in iter_objects(obj.get("subEvent") or []):
                if _types(sub) & EVENT_TYPES and sub is not obj:
                    sub_ev = event_from_object(sub, base_url)
                    if sub_ev:
                        if ev and ev.event_type_hint == "festival":
                            sub_ev.event_type_hint = "festival"
                            sub_ev.festival_name = sub_ev.festival_name or ev.title
                        events.append(sub_ev)
    return events

