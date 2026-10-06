"""iCalendar feed provider (artist, venue or promoter calendars)."""

from __future__ import annotations

from tourdesk_crawler.extract.ical import extract_ical
from tourdesk_crawler.http.errors import CrawlError
from tourdesk_crawler.pipeline.models import ArtistSpec, ProviderResult, SourceSpec
from tourdesk_crawler.providers.base import CrawlerProvider, ProviderContext, register


@register
class ICalProvider(CrawlerProvider):
    key = "ical_feed"
    label = "iCal-Feed"
    scopes = ("artist", "venue", "global")
    default_trust = 2

    def fetch(self, ctx: ProviderContext, source: SourceSpec, artist: ArtistSpec | None) -> ProviderResult:
        if not source.url:
            raise CrawlError("config", "Keine Feed-URL hinterlegt")
        page = ctx.http.fetch(source.url, accept="text/calendar, text/plain;q=0.8, */*;q=0.5")
        events = extract_ical(page.content)
        result = ProviderResult(events=events, method="ical", pages=1, http_status=page.status)
        if not events:
            result.warnings.append("Feed enthält keine Termine")
        return result
