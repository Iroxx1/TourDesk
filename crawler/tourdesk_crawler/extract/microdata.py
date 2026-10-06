"""schema.org Microdata (itemscope/itemprop) event extraction."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from tourdesk.core.text import clean_text, safe_url
from tourdesk_crawler.extract.dates import parse_iso_datetime
from tourdesk_crawler.extract.jsonld import _AVAILABILITY, _STATUS
from tourdesk_crawler.pipeline.models import RawEvent

_EVENT_TYPES = ("event", "musicevent", "festival", "concert")


def _itemtype(tag: Tag) -> str:
    return str(tag.get("itemtype") or "").rsplit("/", 1)[-1].casefold()


def _props(scope: Tag) -> dict[str, list[Tag]]:
    """itemprops belonging directly to ``scope`` (not to nested item scopes)."""
    out: dict[str, list[Tag]] = {}
    for tag in scope.find_all(attrs={"itemprop": True}):
        parent = tag.parent
        while parent is not None and parent is not scope and not parent.has_attr("itemscope"):
            parent = parent.parent
        if parent is not scope:
            continue
        for name in str(tag["itemprop"]).split():
            out.setdefault(name, []).append(tag)
    return out


def _value(tag: Tag, base_url: str) -> str | None:
    for attr in ("content", "datetime"):
        if tag.has_attr(attr):
            return str(tag[attr]).strip()
    if tag.name in ("a", "link") and tag.has_attr("href"):
        return urljoin(base_url, str(tag["href"]))
    if tag.name in ("img",) and tag.has_attr("src"):
        return urljoin(base_url, str(tag["src"]))
    if tag.name == "meta":
        return None
    return clean_text(tag.get_text(" ", strip=True), 300)


def _first(props: dict[str, list[Tag]], name: str, base_url: str) -> str | None:
    for tag in props.get(name, []):
        value = _value(tag, base_url)
        if value:
            return value
    return None


def extract_microdata(soup: BeautifulSoup, base_url: str) -> list[RawEvent]:
    events: list[RawEvent] = []
    for scope in soup.find_all(attrs={"itemscope": True, "itemtype": True}):
        if _itemtype(scope) not in _EVENT_TYPES:
            continue
        props = _props(scope)
        start_raw = _first(props, "startDate", base_url)
        start_d, start_t, tz = parse_iso_datetime(start_raw)
        if start_d is None:
            continue
        ev = RawEvent(start_date=start_d, start_time=start_t, method="microdata", confidence=0.9, raw_date=start_raw)
        ev.extra["tzinfo"] = tz
        ev.title = clean_text(_first(props, "name", base_url), 300)
        end_d, _, _ = parse_iso_datetime(_first(props, "endDate", base_url))
        if end_d and end_d != start_d:
            ev.end_date = end_d
        url = _first(props, "url", base_url)
        ev.url = safe_url(url) if url else None
        status = (_first(props, "eventStatus", base_url) or "").rsplit("/", 1)[-1].casefold()
        ev.status = _STATUS.get(status)
        if _itemtype(scope) == "festival":
            ev.event_type_hint = "festival"
            ev.festival_name = ev.title
        for perf in props.get("performer", []):
            name = None
            if perf.has_attr("itemscope"):
                name = _first(_props(perf), "name", base_url)
            name = name or _value(perf, base_url)
            if name and name not in ev.performers:
                ev.performers.append(clean_text(name, 200) or name)
        for loc in props.get("location", []):
            if loc.has_attr("itemscope"):
                lp = _props(loc)
                ev.venue_name = clean_text(_first(lp, "name", base_url), 200)
                for addr in lp.get("address", []):
                    if addr.has_attr("itemscope"):
                        ap = _props(addr)
                        ev.venue_address = clean_text(_first(ap, "streetAddress", base_url), 300)
                        ev.city = clean_text(_first(ap, "addressLocality", base_url), 160)
                        ev.region = clean_text(_first(ap, "addressRegion", base_url), 100)
                        ev.postal_code = clean_text(_first(ap, "postalCode", base_url), 20)
                        ev.country = clean_text(_first(ap, "addressCountry", base_url), 60)
                    else:
                        ev.venue_address = clean_text(_value(addr, base_url), 300)
            else:
                ev.venue_name = clean_text(_value(loc, base_url), 200)
            break
        for offer in props.get("offers", []):
            if offer.has_attr("itemscope"):
                op = _props(offer)
                link = _first(op, "url", base_url)
                ev.ticket_url = ev.ticket_url or (safe_url(link) if link else None)
                avail = (_first(op, "availability", base_url) or "").rsplit("/", 1)[-1].casefold()
                ev.ticket_status = ev.ticket_status or _AVAILABILITY.get(avail)
        events.append(ev)
    return events
