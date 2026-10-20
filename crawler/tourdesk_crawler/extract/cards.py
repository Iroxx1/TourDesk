"""Event cards with BEM class names, common in WordPress themes.

    <article class="event"> <div class="event__date">27. - 01. Nov 2026</div> <div class="event__time">08:30 Uhr</div>
      <div class="event__location"><a>Saarlandhalle</a></div> <h2 class="event__title"><a href="…">Titel</a></h2>
      <div class="event__categories"><span>Sport</span></div> </article>
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from tourdesk.core.text import clean_text, safe_url
from tourdesk_crawler.extract.dates import find_dates, find_times, month_number
from tourdesk_crawler.extract.html import normalize_link
from tourdesk_crawler.pipeline.models import RawEvent

_DATE_CLASS = re.compile(r"^([a-z0-9-]*event[a-z0-9-]*)__date$", re.I)
# "27. - 01. Nov 2026": Bereich über den Monatswechsel, der erste Tag gehört zum Vormonat
_CROSS_MONTH = re.compile(r"^\s*(?P<d1>[0-3]?\d)\.?\s*[-–]\s*(?P<d2>[0-3]?\d)\.?\s*(?P<mon>[^\W\d_]+)\.?\s*(?P<y>(?:19|20)\d\d)?", re.U)
_GAP = re.compile(r"\s*\n\s*|[ \t ]{2,}")
MIN_CARDS = 2


def _part(card: Tag, prefix: str, *names: str) -> Tag | None:
    for name in names:
        found = card.find(class_=f"{prefix}__{name}")
        if isinstance(found, Tag):
            return found
    return None


def _text(tag: Tag | None) -> str | None:
    return clean_text(tag.get_text(" ", strip=True), 500) if tag is not None else None


def _dates(text: str, today: date) -> tuple[date | None, date | None]:
    m = _CROSS_MONTH.match(text)
    if m and int(m["d2"]) < int(m["d1"]):
        month = month_number(m["mon"])
        if month:
            year = int(m["y"]) if m["y"] else today.year
            end = _safe(year, month, int(m["d2"]))
            sy, sm = (year - 1, 12) if month == 1 else (year, month - 1)
            return _safe(sy, sm, int(m["d1"])), end
    found = find_dates(text, today=today)
    if not found:
        return None, None
    return found[0].start, found[0].end


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def extract_cards(soup: BeautifulSoup, url: str, *, today: date) -> list[RawEvent]:
    events: list[RawEvent] = []
    for date_tag in soup.find_all(class_=_DATE_CLASS):
        if not isinstance(date_tag, Tag):
            continue
        prefix = next((m.group(1) for c in date_tag.get("class") or [] if (m := _DATE_CLASS.match(c))), None)
        if not prefix:
            continue
        card = date_tag
        while card.parent is not None and isinstance(card.parent, Tag) and card.find(class_=f"{prefix}__title") is None:
            card = card.parent
        title_tag = _part(card, prefix, "title", "name", "headline")
        title = _text(title_tag)
        if title_tag is not None:
            # "Lisa Eckhart  Ich war mal wer": doppelter Leerraum trennt Künstler und Programmtitel
            parts = [p for p in _GAP.split(title_tag.get_text().strip()) if p.strip()]
            if len(parts) >= 2:
                title = clean_text(" – ".join(parts), 500)
        start, end = _dates(_text(date_tag) or "", today)
        if not title or start is None:
            continue
        raw = RawEvent(start_date=start, end_date=end, title=title, method="cards", confidence=0.8)
        time_text = _text(_part(card, prefix, "time", "start"))
        if time_text:
            raw.start_time, raw.doors_time = find_times(time_text)
        raw.venue_name = _text(_part(card, prefix, "location", "venue", "place"))
        link = title_tag.find("a", href=True) if title_tag is not None else None
        if isinstance(link, Tag):
            raw.url = safe_url(normalize_link(url, str(link["href"])))
        category = _text(_part(card, prefix, "categories", "category", "genre"))
        if category:
            raw.extra["category"] = category.strip(" |")[:80] or None
        raw.raw_date = _text(date_tag)
        events.append(raw)
    return events if len(events) >= MIN_CARDS else []


__all__ = ["extract_cards"]
