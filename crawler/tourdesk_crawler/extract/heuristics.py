"""Text heuristics for tour/agenda pages without structured data.

Strategy: every *maximal* element that contains exactly one date (or date range)
is treated as one event block (list item, table row, card …). Inside the block the
date, times, city (looked up in the geo catalogue), venue and links are separated.
Results get a lower confidence than structured data.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from tourdesk.core.text import clean_text, normalize_name, safe_url
from tourdesk_crawler.extract.dates import DateMatch, find_dates, find_times
from tourdesk_crawler.pipeline.models import RawEvent
from tourdesk_crawler.pipeline.tickets import TICKET_WORDS, detect_statuses, ticket_provider_for

EVENTISH = re.compile(r"(event|show|tour|date|concert|konzert|gig|termin|veranstaltung|agenda|programm|listing|row|item|card|spectacle)", re.I)
VENUE_WORDS = re.compile(
    r"\b(halle|hall|arena|club|klub|stadion|stadium|theater|theatre|théâtre|zenith|zénith|festival|open air|park|kulturzentrum|"
    r"centre|center|zentrum|saal|forum|palais|dome|bühne|buehne|kirche|church|kathedrale|scala|olympia|music hall|live|"
    r"amphitheater|ring|messe|expo|garage|fabrik|werk|kantine|keller|bar|café|cafe|lounge|box)\b",
    re.I,
)
NOISE = re.compile(
    r"^(tickets?|karten|billets?|info|infos|mehr|more|details|weitere infos|read more|mehr erfahren|buy|kaufen|"
    r"vip|rsvp|share|teilen|facebook|instagram|book|jetzt|now|notify me|remind me|"
    r"mo|di|mi|do|fr|sa|so|mon|tue|wed|thu|fri|sat|sun|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\.?,?$",
    re.I,
)
SPLIT = re.compile(r"\n|\s[|•·]\s|\s[–—]\s|\s-\s|\s@\s|\s/\s")
FESTIVAL_RE = re.compile(r"\b([\w'’&.\- ]{2,40}?(?:festival|open air|openair|fest))\b", re.I)
SUPPORT_RE = re.compile(r"\b(support|special guests?|opening act|vorband|en première partie|voorprogramma)\b", re.I)


def _blocks(soup: BeautifulSoup, today: date, lang: str | None) -> list[tuple[Tag, DateMatch]]:
    candidates: dict[int, tuple[Tag, DateMatch]] = {}
    info: dict[int, bool] = {}

    for el in soup.find_all(True):
        if el.name in ("html", "body", "head", "script", "style"):
            continue
        text = el.get_text(" ", strip=True)
        if not (8 <= len(text) <= 600):
            info[id(el)] = False
            continue
        matches = find_dates(text, today=today, locale=lang)
        if len(matches) == 1:
            candidates[id(el)] = (el, matches[0])
            info[id(el)] = True
        else:
            info[id(el)] = False

    blocks: list[tuple[Tag, DateMatch]] = []
    for key, (el, dm) in candidates.items():
        parent = el.parent
        if isinstance(parent, Tag) and info.get(id(parent)):
            continue  # not maximal
        blocks.append((el, dm))
    return blocks


def _segments(block: Tag) -> list[str]:
    text = block.get_text("\n", strip=True)
    out: list[str] = []
    for raw in SPLIT.split(text):
        for part in raw.split("\n"):
            part = part.strip(" ,;:")
            if part and part not in out:
                out.append(part)
    return out


def _eventish(block: Tag) -> bool:
    el: Tag | None = block
    for _ in range(3):
        if el is None or not isinstance(el, Tag):
            break
        attrs = " ".join(el.get("class") or []) + " " + str(el.get("id") or "")
        if EVENTISH.search(attrs) or el.name in ("tr", "li", "article"):
            return True
        el = el.parent if isinstance(el.parent, Tag) else None
    return False


def extract_heuristic(
    soup: BeautifulSoup,
    base_url: str,
    *,
    today: date,
    lang: str | None = None,
    is_city: Callable[[str], bool] | None = None,
    is_country: Callable[[str], bool] | None = None,
    max_events: int = 300,
) -> list[RawEvent]:
    is_city = is_city or (lambda s: False)
    is_country = is_country or (lambda s: False)
    events: list[RawEvent] = []
    seen: set[tuple] = set()
    for block, dm in _blocks(soup, today, lang):
        full_text = block.get_text(" ", strip=True)
        segments = _segments(block)
        start_t, doors_t = find_times(full_text.replace(dm.text, " "))
        city = country = venue = None
        title = None
        leftovers: list[str] = []
        for seg in segments:
            cleaned = seg
            if dm.text in cleaned:
                cleaned = cleaned.replace(dm.text, " ")
            cleaned = re.sub(r"\b\d{1,2}[:.h]\d{2}\s*(uhr|h)?\b", " ", cleaned, flags=re.I)
            cleaned = re.sub(r"\b\d{1,2}\s*(uhr|[ap]\.?m\.?)\b", " ", cleaned, flags=re.I)
            cleaned = re.sub(r"\b(einlass|beginn|doors|show|start)\s*:?", " ", cleaned, flags=re.I)
            cleaned = clean_text(cleaned) or ""
            if not cleaned or len(cleaned) < 2 or NOISE.match(cleaned) or TICKET_WORDS.fullmatch(cleaned):
                continue
            if re.fullmatch(r"[\d\s.,:/€$£%-]+", cleaned):
                continue
            # "Esch-sur-Alzette, LU" / "Saarbrücken (DE)"
            parts = [p.strip(" ()") for p in re.split(r",|\(|\)", cleaned) if p.strip(" ()")]
            matched_city = False
            for i, part in enumerate(parts):
                if city is None and is_city(part):
                    city = part
                    matched_city = True
                    rest = parts[i + 1 :]
                    for r in rest:
                        if country is None and is_country(r):
                            country = r
                    before = [p for p in parts[:i] if not is_country(p)]
                    if before and venue is None:
                        venue = before[-1]
                    break
            if matched_city:
                continue
            if country is None and is_country(cleaned):
                country = cleaned
                continue
            leftovers.append(cleaned)
        heading = block.find(["h1", "h2", "h3", "h4", "h5", "strong", "b"])
        if isinstance(heading, Tag):
            htext = clean_text(heading.get_text(" ", strip=True), 300)
            if htext and dm.text not in htext and htext not in (city, venue, country):
                title = htext
        # venue: prefer segments with venue words, else the first leftover that is not the title
        if venue is None:
            venue_like = [s for s in leftovers if VENUE_WORDS.search(s) and s != title]
            others = [s for s in leftovers if s != title and len(s) <= 80]
            venue = (venue_like or others or [None])[0]
        if not (city or venue or _eventish(block)):
            continue
        url = ticket_url = None
        for a in block.find_all("a", href=True):
            href = safe_url(urljoin(base_url, str(a["href"])))
            if not href:
                continue
            label = a.get_text(" ", strip=True)
            provider, _resale = ticket_provider_for(href)
            if provider or TICKET_WORDS.search(label or "") or "ticket" in href.lower():
                ticket_url = ticket_url or href
            elif url is None:
                url = href
        status, ticket_status = detect_statuses(full_text)
        ev = RawEvent(
            start_date=dm.start,
            end_date=dm.end,
            start_time=start_t,
            doors_time=doors_t,
            title=title,
            venue_name=clean_text(venue, 200) if venue else None,
            city=clean_text(city, 160) if city else None,
            country=clean_text(country, 60) if country else None,
            url=url,
            ticket_url=ticket_url,
            status=status,
            ticket_status=ticket_status or ("available" if ticket_url else None),
            raw_date=dm.text,
            method="heuristic",
            confidence=0.55 if city else 0.45,
        )
        ev.ticket_provider = ticket_provider_for(ticket_url)[0] if ticket_url else None
        fest = FESTIVAL_RE.search(" ".join(x for x in (title or "", venue or "") if x))
        if fest:
            ev.event_type_hint = "festival"
            ev.festival_name = clean_text(fest.group(1), 200)
        elif SUPPORT_RE.search(full_text):
            ev.extra["support_hint"] = True
        key = (ev.start_date, normalize_name(ev.venue_name), normalize_name(ev.city), normalize_name(ev.title))
        if key in seen:
            continue
        seen.add(key)
        events.append(ev)
        if len(events) >= max_events:
            break
    return events


def lineup_names(soup: BeautifulSoup, *, max_names: int = 2000) -> list[str]:
    """Candidate artist names on a festival line-up page."""
    names: list[str] = []
    seen: set[str] = set()
    selectors = ["li", "a", "h2", "h3", "h4", "h5", "figcaption", "span", "div", "p", "td"]
    for el in soup.find_all(selectors):
        attrs = " ".join(el.get("class") or []) + " " + str(el.get("id") or "")
        text = el.get_text(" ", strip=True)
        if not text or len(text) > 60 or len(text) < 2:
            continue
        if el.name in ("div", "span", "p", "td") and not re.search(r"(artist|band|act|lineup|line-up|name|performer|title)", attrs, re.I):
            continue
        for part in re.split(r"\s+[•·|/]\s+|\s*\n\s*", text):
            part = part.strip(" ,;")
            key = normalize_name(part)
            if not key or key in seen or len(part) > 60:
                continue
            seen.add(key)
            names.append(part)
            if len(names) >= max_names:
                return names
    return names
