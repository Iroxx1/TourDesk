"""Web page providers: official website, tour page, venue agenda, promoter, ticket listing, generic."""

from __future__ import annotations

from typing import ClassVar

from tourdesk_crawler.extract import extract_events
from tourdesk_crawler.extract.embedded import walk_json
from tourdesk_crawler.extract.html import (
    AGENDA_KEYWORDS,
    TOUR_KEYWORDS,
    detect_widgets,
    discover_links,
    find_next_page,
    parse_html,
)
from tourdesk_crawler.extract.ical import extract_ical
from tourdesk_crawler.http.errors import CrawlError
from tourdesk_crawler.pipeline.models import ArtistSpec, ProviderResult, SourceSpec
from tourdesk_crawler.providers.base import CrawlerProvider, ProviderContext, register


class WebPageProvider(CrawlerProvider):
    discover_keywords: ClassVar[tuple[str, ...]] = TOUR_KEYWORDS
    allow_heuristics: ClassVar[bool] = True

    def start_url(self, source: SourceSpec) -> str | None:
        return source.url

    def fetch(self, ctx: ProviderContext, source: SourceSpec, artist: ArtistSpec | None) -> ProviderResult:
        base = self.start_url(source)
        if not base:
            raise CrawlError("config", "Für diese Quelle ist keine URL hinterlegt")
        result = ProviderResult()
        discovered = source.config.get("discovered_url")
        queue: list[str] = [discovered] if discovered and discovered != base else []
        queue.append(base)
        visited: set[str] = set()
        max_pages = int(ctx.settings.get("max_pages_per_source", 3)) + (1 if discovered else 0)
        discover = bool(source.config.get("discover", True))
        first_error: CrawlError | None = None
        while queue and len(visited) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                page = ctx.http.fetch(url)
            except CrawlError as exc:
                if url == discovered:
                    result.discovered["discovered_url"] = None  # stale discovery, fall back
                    result.warnings.append(f"Gespeicherte Unterseite nicht mehr erreichbar ({exc.status_code or exc.error_type})")
                    continue
                if not result.pages:
                    first_error = exc
                    break
                result.warnings.append(f"{url}: {exc}")
                continue
            result.pages += 1
            result.http_status = page.status
            ctype = (page.content_type or "").lower()
            if "calendar" in ctype or url.lower().endswith(".ics"):
                events, method = extract_ical(page.content), "ical"
            elif "json" in ctype:
                events, method = walk_json(page.json(), page.final_url), "embedded"
            else:
                html = page.text
                events, method = extract_events(
                    html,
                    page.final_url,
                    today=ctx.today,
                    is_city=ctx.geo.is_city,
                    is_country=ctx.geo.is_country,
                    allow_heuristics=self.allow_heuristics and source.config.get("heuristics", True),
                )
                soup = parse_html(html)
                if events:
                    if url not in (base, discovered):
                        result.discovered["discovered_url"] = url
                    nxt = find_next_page(soup, page.final_url)
                    if nxt and nxt not in visited and len(visited) < max_pages:
                        queue.insert(0, nxt)
                elif discover and url in (base, discovered):
                    for link in discover_links(soup, page.final_url, self.discover_keywords, limit=max_pages):
                        if link not in visited and link not in queue:
                            queue.append(link)
                    widgets = detect_widgets(soup)
                    if widgets:
                        result.discovered["widgets"] = widgets
            if events:
                result.method = result.method or method
                result.events.extend(events)
                if method in ("jsonld", "microdata", "embedded", "ical") and url == discovered:
                    break
        if first_error is not None and not result.events:
            raise first_error
        if not result.events:
            hint = ""
            widgets = result.discovered.get("widgets") or {}
            if "bandsintown_artist" in widgets:
                hint = " (Tourdaten kommen von einem Bandsintown-Widget – Bandsintown-API-Schlüssel hinterlegen)"
            elif widgets:
                hint = " (Tourdaten werden per JavaScript-Widget geladen)"
            result.warnings.append("Keine Termine gefunden" + hint)
        return result


@register
class ArtistWebsiteProvider(WebPageProvider):
    key = "official_website"
    label = "Offizielle Website"
    scopes = ("artist",)
    default_trust = 1


@register
class TourPageProvider(WebPageProvider):
    key = "tour_page"
    label = "Tourseite"
    scopes = ("artist",)
    default_trust = 1


@register
class GenericWebProvider(WebPageProvider):
    key = "generic_web"
    label = "Webseite"
    scopes = ("artist", "global")
    default_trust = 6
    needs_artist_match = True


@register
class VenueWebsiteProvider(WebPageProvider):
    key = "venue_website"
    label = "Veranstaltungsort"
    scopes = ("venue",)
    default_trust = 2
    needs_artist_match = True
    discover_keywords = AGENDA_KEYWORDS


@register
class PromoterWebsiteProvider(WebPageProvider):
    key = "promoter_website"
    label = "Veranstalter"
    scopes = ("global",)
    default_trust = 3
    needs_artist_match = True
    discover_keywords = AGENDA_KEYWORDS


@register
class TicketListingProvider(WebPageProvider):
    key = "ticket_listing"
    label = "Ticketseite"
    scopes = ("global", "artist")
    default_trust = 4
    needs_artist_match = True
    discover_keywords = ("events", "tickets", "konzerte", "concerts")
