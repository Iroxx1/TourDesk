"""FestivalProvider: official festival line-ups.

A monitored artist appearing in the official line-up of a festival is a confirmed
festival appearance (trust level 3). Rumours from other sites never confirm.
"""

from __future__ import annotations

from datetime import date, timedelta

from tourdesk.core.text import clean_text
from tourdesk_crawler.extract.dates import find_dates, parse_iso_datetime
from tourdesk_crawler.extract.heuristics import lineup_names
from tourdesk_crawler.extract.html import LINEUP_KEYWORDS, discover_links, parse_html, strip_noise
from tourdesk_crawler.extract.jsonld import EVENT_TYPES, _load_json, _names, _types, iter_objects
from tourdesk_crawler.http.errors import CrawlError
from tourdesk_crawler.pipeline.models import ArtistSpec, ProviderResult, RawEvent, SourceSpec
from tourdesk_crawler.providers.base import CrawlerProvider, ProviderContext, register


def _festival_dates_from_jsonld(soup) -> tuple[date | None, date | None, list[str]]:
    start = end = None
    performers: list[str] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        data = _load_json(script.string or "")
        for obj in iter_objects(data):
            types = _types(obj)
            if not types & EVENT_TYPES:
                continue
            s, _t, _ = parse_iso_datetime(obj.get("startDate") if isinstance(obj.get("startDate"), str) else None)
            e, _t2, _ = parse_iso_datetime(obj.get("endDate") if isinstance(obj.get("endDate"), str) else None)
            if "festival" in types and s:
                start, end = s, e or s
            performers += [p for p in _names(obj.get("performer")) if p not in performers]
    return start, end, performers


def _festival_dates_from_text(text: str, today: date) -> tuple[date | None, date | None]:
    candidates = []
    for m in find_dates(text, today=today):
        if m.start < today - timedelta(days=3) or m.start > today + timedelta(days=550):
            continue
        candidates.append(m)
    ranges = [m for m in candidates if m.end and 0 < (m.end - m.start).days <= 7]
    if ranges:
        return ranges[0].start, ranges[0].end
    if candidates:
        return candidates[0].start, candidates[0].start
    return None, None


@register
class FestivalProvider(CrawlerProvider):
    key = "festival_lineup"
    label = "Festival-Line-up"
    scopes = ("festival",)
    default_trust = 3
    needs_artist_match = True

    def fetch(self, ctx: ProviderContext, source: SourceSpec, artist: ArtistSpec | None) -> ProviderResult:
        festival = source.festival
        if festival is None:
            raise CrawlError("config", "Quelle ist keinem Festival zugeordnet")
        url = source.config.get("lineup_url") or source.config.get("discovered_url") or source.url
        if not url:
            raise CrawlError("config", "Keine Festival-URL hinterlegt")
        result = ProviderResult(method="lineup")
        page = ctx.http.fetch(url)
        result.pages, result.http_status = 1, page.status
        soup = parse_html(page.text)
        start, end, performers = _festival_dates_from_jsonld(soup)
        names = list(performers)
        lineup_url = url
        page_soup = strip_noise(parse_html(page.text))
        names += [n for n in lineup_names(page_soup) if n not in names]
        if len(names) < 15 and source.config.get("discover", True):
            for link in discover_links(soup, page.final_url, LINEUP_KEYWORDS, limit=2):
                try:
                    sub = ctx.http.fetch(link)
                except CrawlError as exc:
                    result.warnings.append(f"Line-up-Seite {link}: {exc}")
                    continue
                result.pages += 1
                sub_soup = parse_html(sub.text)
                s2, e2, perf2 = _festival_dates_from_jsonld(sub_soup)
                start, end = start or s2, end or e2
                found = perf2 + lineup_names(strip_noise(parse_html(sub.text)))
                new = [n for n in found if n not in names]
                if len(new) >= 5:
                    lineup_url = link
                    result.discovered["lineup_url"] = link
                names += new
        cfg_start = source.config.get("start_date")
        cfg_end = source.config.get("end_date")
        if cfg_start:
            start = date.fromisoformat(cfg_start)
            end = date.fromisoformat(cfg_end) if cfg_end else start
        if start is None:
            start, end = _festival_dates_from_text(soup.get_text(" ", strip=True), ctx.today)
        if start is None:
            result.warnings.append("Festivaldatum nicht gefunden – bitte start_date/end_date in der Quelle setzen")
            result.lineup = names
            return result
        result.discovered["festival_dates"] = [start.isoformat(), (end or start).isoformat()]
        result.lineup = names
        for name in names:
            result.events.append(
                RawEvent(
                    start_date=start,
                    end_date=end if end and end != start else None,
                    title=festival.name,
                    performers=[clean_text(name, 200) or name],
                    venue_name=festival.venue_name,
                    city=festival.city_name,
                    country=festival.country_code,
                    url=lineup_url,
                    event_type_hint="festival",
                    festival_name=festival.name,
                    role="festival",
                    method="lineup",
                    confidence=0.85,
                )
            )
        if not names:
            result.warnings.append("Kein Line-up gefunden")
        return result
