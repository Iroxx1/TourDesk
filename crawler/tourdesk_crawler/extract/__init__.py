"""Event extraction from web pages: structured data first, heuristics as fallback."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from tourdesk_crawler.extract.embedded import extract_embedded
from tourdesk_crawler.extract.heuristics import extract_heuristic
from tourdesk_crawler.extract.html import page_info, parse_html, strip_noise
from tourdesk_crawler.extract.jsonld import extract_jsonld
from tourdesk_crawler.extract.microdata import extract_microdata
from tourdesk_crawler.pipeline.models import RawEvent


def extract_events(
    html: str,
    url: str,
    *,
    today: date,
    is_city: Callable[[str], bool] | None = None,
    is_country: Callable[[str], bool] | None = None,
    allow_heuristics: bool = True,
) -> tuple[list[RawEvent], str | None]:
    """Return ``(events, method)``; ``method`` names the extractor that produced them."""
    soup = parse_html(html)
    info = page_info(soup, url)
    for method, func in (("jsonld", extract_jsonld), ("microdata", extract_microdata)):
        events = func(soup, url)
        if events:
            return events, method
    events = extract_embedded(soup, url, html)
    if events:
        return events, "embedded"
    if not allow_heuristics:
        return [], None
    events = extract_heuristic(strip_noise(parse_html(html)), url, today=today, lang=info.lang, is_city=is_city, is_country=is_country)
    return events, ("heuristic" if events else None)


__all__ = ["extract_events"]
