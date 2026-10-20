"""API based providers: Ticketmaster Discovery API, Bandsintown, Songkick.

All of them need an API key (configured in the admin crawler settings or .env).
Without a key they are skipped and never cause errors.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from urllib.parse import quote

from tourdesk.core.text import clean_text, normalize_name, normalize_variants, safe_url
from tourdesk.core.timeutil import utcnow
from tourdesk_crawler.extract.dates import parse_iso_datetime
from tourdesk_crawler.http.errors import CrawlError
from tourdesk_crawler.pipeline.models import ArtistSpec, ProviderResult, RawEvent, SourceSpec, VenueSpec
from tourdesk_crawler.providers.base import CrawlerProvider, ProviderContext, register


def _name_matches(candidate: str | None, artist: ArtistSpec) -> bool:
    if not candidate:
        return False
    wanted: set[str] = set()
    for n in artist.all_names:
        wanted |= normalize_variants(n)
    return bool(normalize_variants(candidate) & wanted)


def _auth_error(exc: CrawlError, label: str) -> CrawlError:
    if exc.status_code in (401, 403):
        return CrawlError("auth", f"{label}: API-Schlüssel ungültig oder ohne Berechtigung", url=exc.url, status_code=exc.status_code)
    return exc


@register
class TicketmasterProvider(CrawlerProvider):
    key = "ticketmaster"
    label = "Ticketmaster"
    scopes = ("artist",)
    default_trust = 4
    api_key_name = "ticketmaster"
    BASE = "https://app.ticketmaster.com/discovery/v2"

    def fetch(self, ctx: ProviderContext, source: SourceSpec, artist: ArtistSpec | None) -> ProviderResult:
        assert artist is not None
        api_key = ctx.api_key("ticketmaster")
        if not api_key:
            raise CrawlError("config", "Kein Ticketmaster-API-Schlüssel")
        result = ProviderResult(method="api")
        attraction_id = source.config.get("attraction_id") or (artist.external_ids or {}).get("ticketmaster")
        try:
            if not attraction_id:
                data = ctx.http.fetch_json(
                    f"{self.BASE}/attractions.json",
                    params={"apikey": api_key, "keyword": artist.name, "classificationName": "music", "size": 20},
                    api=True,
                    min_interval=0.3,
                )
                result.pages += 1
                for att in (data.get("_embedded") or {}).get("attractions", []):
                    if _name_matches(att.get("name"), artist):
                        attraction_id = att.get("id")
                        break
                if not attraction_id:
                    result.warnings.append("Künstler bei Ticketmaster nicht gefunden")
                    return result
                result.discovered["attraction_id"] = attraction_id
                result.artist_updates["ticketmaster"] = attraction_id
            page = 0
            while page < 5:
                data = ctx.http.fetch_json(
                    f"{self.BASE}/events.json",
                    params={"apikey": api_key, "attractionId": attraction_id, "size": 100, "page": page, "sort": "date,asc"},
                    api=True,
                    min_interval=0.3,
                )
                result.pages += 1
                for ev in (data.get("_embedded") or {}).get("events", []):
                    raw = self._map(ev)
                    if raw:
                        result.events.append(raw)
                total_pages = int((data.get("page") or {}).get("totalPages") or 1)
                page += 1
                if page >= total_pages:
                    break
        except CrawlError as exc:
            raise _auth_error(exc, self.label) from exc
        result.http_status = 200
        return result

    def _map(self, ev: dict) -> RawEvent | None:
        dates = ev.get("dates") or {}
        start = dates.get("start") or {}
        local_date = start.get("localDate")
        if not local_date:
            return None
        d, _t, _ = parse_iso_datetime(local_date)
        if d is None:
            return None
        t = None
        if start.get("localTime") and not start.get("timeTBA"):
            try:
                hh, mm = start["localTime"].split(":")[:2]
                t = time(int(hh), int(mm))
            except ValueError:
                t = None
        raw = RawEvent(start_date=d, start_time=t, method="api", confidence=0.95, external_id=str(ev.get("id"))[:200])
        raw.timezone = dates.get("timezone")
        raw.title = clean_text(ev.get("name"), 300)
        raw.url = safe_url(ev.get("url"))
        raw.ticket_url = raw.url
        raw.ticket_provider = "Ticketmaster"
        code = ((dates.get("status") or {}).get("code") or "").lower()
        public_sale = ((ev.get("sales") or {}).get("public") or {}).get("startDateTime")
        onsale = None
        if public_sale:
            try:
                onsale = datetime.fromisoformat(public_sale.replace("Z", "+00:00"))
            except ValueError:
                onsale = None
        raw.onsale_at = onsale
        if code == "cancelled":
            raw.status = "cancelled"
        elif code == "postponed":
            raw.status = "postponed"
        elif code == "rescheduled":
            raw.status = "rescheduled"
        if code == "onsale":
            raw.ticket_status = "available"
        elif code == "offsale":
            raw.ticket_status = "not_on_sale" if onsale and onsale > utcnow() else "sold_out"
        venues = (ev.get("_embedded") or {}).get("venues") or []
        if venues:
            v = venues[0]
            raw.venue_name = clean_text(v.get("name"), 200)
            raw.city = clean_text((v.get("city") or {}).get("name"), 160)
            raw.region = clean_text((v.get("state") or {}).get("name") or (v.get("state") or {}).get("stateCode"), 100)
            raw.country = (v.get("country") or {}).get("countryCode") or (v.get("country") or {}).get("name")
            raw.postal_code = v.get("postalCode")
            raw.venue_address = clean_text((v.get("address") or {}).get("line1"), 300)
            loc = v.get("location") or {}
            try:
                raw.latitude, raw.longitude = float(loc["latitude"]), float(loc["longitude"])
            except (KeyError, TypeError, ValueError):
                pass
        raw.performers = [a.get("name") for a in (ev.get("_embedded") or {}).get("attractions", []) if a.get("name")]
        prices = ev.get("priceRanges") or []
        if prices:
            raw.price_min, raw.price_max, raw.currency = prices[0].get("min"), prices[0].get("max"), prices[0].get("currency")
        name = (raw.title or "").casefold()
        if "festival" in name and len(raw.performers) > 3:
            raw.event_type_hint = "festival"
            raw.festival_name = raw.title
        cls = (ev.get("classifications") or [{}])[0] or {}
        segment = (cls.get("segment") or {}).get("name")
        genre = (cls.get("genre") or {}).get("name")
        if segment and segment.casefold() not in ("undefined", "miscellaneous"):
            label = SEGMENT_LABELS.get(segment.casefold(), segment)
            raw.extra["category"] = f"{label} · {genre}" if genre and genre.casefold() not in ("undefined", "other") else label
        return raw


SEGMENT_LABELS = {"music": "Musik", "arts & theatre": "Bühne", "sports": "Sport", "film": "Film"}


def _venue_score(candidate: dict, venue: VenueSpec) -> int:
    """How well a Ticketmaster venue matches the catalogue venue (0 = not at all)."""
    names = normalize_variants(venue.name)
    cand = normalize_variants(candidate.get("name"))
    if not cand:
        return 0
    if names & cand:
        score = 4
    elif any(a in b or b in a for a in names for b in cand if len(a) >= 4 and len(b) >= 4):
        score = 2  # "Rockhal" ↔ "Rockhal Main Hall"
    else:
        return 0
    city = normalize_name((candidate.get("city") or {}).get("name"))
    if venue.city_name and city:
        # Ticketmaster schreibt Städte uneinheitlich: "Esch-Alzette", "Esch S/alzette", "Esch-sur-Alzette"
        wanted = normalize_name(venue.city_name)
        shared = {t for t in city.split() if len(t) >= 4} & {t for t in wanted.split() if len(t) >= 4}
        if city == wanted or shared:
            score += 2
        else:
            return 0
    return score


@register
class TicketmasterVenueProvider(TicketmasterProvider):
    """All events of one venue (its complete programme), used for venues a user has selected."""

    key = "ticketmaster_venue"
    label = "Ticketmaster (Ort)"
    scopes = ("venue",)
    needs_artist_match = True
    MAX_VENUES = 8
    LOOKUP_DAYS = 7  # Ticketmaster legt für dieselbe Halle immer wieder neue Einträge an

    def _lookup(self, ctx: ProviderContext, api_key: str, venue: VenueSpec, result: ProviderResult) -> list[str]:
        params = {"apikey": api_key, "keyword": venue.name, "size": 50, "locale": "*"}
        if venue.country_code:
            params["countryCode"] = venue.country_code
        data = ctx.http.fetch_json(f"{self.BASE}/venues.json", params=params, api=True, min_interval=0.3)
        result.pages += 1
        candidates = []
        for v in (data.get("_embedded") or {}).get("venues", []):
            score = _venue_score(v, venue)
            upcoming = (v.get("upcomingEvents") or {}).get("_total")
            if v.get("id") and score:
                candidates.append((score, upcoming, v["id"]))
        best = max((c[0] for c in candidates), default=0)
        # Hallen eines Hauses (Rockhal Main Hall / Club / Box) gehören zusammen; Einträge ohne Termine weglassen
        chosen = [c for c in candidates if c[0] >= 4 and c[0] >= best - 2 and c[1] != 0]
        chosen.sort(key=lambda c: (-c[0], -(c[1] or 0)))
        return [vid for _score, _upcoming, vid in chosen[: self.MAX_VENUES]]

    def fetch(self, ctx: ProviderContext, source: SourceSpec, artist: ArtistSpec | None) -> ProviderResult:
        venue = source.venue
        if venue is None:
            raise CrawlError("config", "Quelle ohne Veranstaltungsort")
        api_key = ctx.api_key("ticketmaster")
        if not api_key:
            raise CrawlError("config", "Kein Ticketmaster-API-Schlüssel")
        result = ProviderResult(method="api")
        venue_ids = list(source.config.get("tm_venue_ids") or [])
        checked = source.config.get("tm_venue_checked")
        try:
            if not checked or checked < (ctx.today - timedelta(days=self.LOOKUP_DAYS)).isoformat():
                venue_ids = self._lookup(ctx, api_key, venue, result)
                result.discovered["tm_venue_ids"] = venue_ids
                result.discovered["tm_venue_checked"] = ctx.today.isoformat()
            if not venue_ids:
                result.warnings.append("Bei Ticketmaster gibt es für diesen Ort derzeit keine Termine")
                return result
            seen: set[str] = set()
            for venue_id in venue_ids:
                page = 0
                while page < 5:
                    data = ctx.http.fetch_json(
                        f"{self.BASE}/events.json",
                        params={"apikey": api_key, "venueId": venue_id, "size": 200, "page": page, "sort": "date,asc", "locale": "*"},
                        api=True,
                        min_interval=0.3,
                    )
                    result.pages += 1
                    for ev in (data.get("_embedded") or {}).get("events", []):
                        raw = self._map(ev)
                        if raw and raw.external_id not in seen:
                            seen.add(raw.external_id or "")
                            result.events.append(raw)
                    total_pages = int((data.get("page") or {}).get("totalPages") or 1)
                    page += 1
                    if page >= total_pages:
                        break
        except CrawlError as exc:
            raise _auth_error(exc, self.label) from exc
        result.http_status = 200
        return result


@register
class BandsintownProvider(CrawlerProvider):
    key = "bandsintown"
    label = "Bandsintown"
    scopes = ("artist",)
    default_trust = 4
    api_key_name = "bandsintown"

    def fetch(self, ctx: ProviderContext, source: SourceSpec, artist: ArtistSpec | None) -> ProviderResult:
        assert artist is not None
        app_id = ctx.api_key("bandsintown")
        if not app_id:
            raise CrawlError("config", "Keine Bandsintown-App-ID")
        name = source.config.get("artist_name") or artist.name
        url = f"https://rest.bandsintown.com/artists/{quote(name, safe='')}/events"
        try:
            data = ctx.http.fetch_json(url, params={"app_id": app_id, "date": "upcoming"}, api=True, min_interval=1.0)
        except CrawlError as exc:
            if exc.status_code == 404:
                return ProviderResult(method="api", warnings=["Künstler bei Bandsintown nicht gefunden"])
            raise _auth_error(exc, self.label) from exc
        result = ProviderResult(method="api", pages=1, http_status=200)
        if not isinstance(data, list):
            result.warnings.append("Unerwartete Antwort von Bandsintown")
            return result
        for ev in data:
            d, t, tz = parse_iso_datetime(ev.get("datetime") or ev.get("starts_at"))
            if d is None:
                continue
            raw = RawEvent(start_date=d, start_time=t, method="api", confidence=0.9, external_id=str(ev.get("id"))[:200])
            raw.extra["tzinfo"] = tz
            raw.title = clean_text(ev.get("title"), 300)
            raw.description = clean_text(ev.get("description"), 1000)
            raw.url = safe_url(ev.get("url"))
            venue = ev.get("venue") or {}
            raw.venue_name = clean_text(venue.get("name"), 200)
            raw.city = clean_text(venue.get("city"), 160)
            raw.region = clean_text(venue.get("region"), 100)
            raw.country = clean_text(venue.get("country"), 60)
            try:
                raw.latitude, raw.longitude = float(venue["latitude"]), float(venue["longitude"])
            except (KeyError, TypeError, ValueError):
                pass
            for offer in ev.get("offers") or []:
                if offer.get("url"):
                    raw.ticket_url = safe_url(offer["url"])
                    status = str(offer.get("status") or "").casefold()
                    raw.ticket_status = "available" if status == "available" else "sold_out" if "sold" in status else None
                    break
            raw.performers = [n for n in ev.get("lineup") or [] if isinstance(n, str)]
            if ev.get("festival_start_date") or ev.get("festival_name"):
                raw.event_type_hint = "festival"
                raw.festival_name = clean_text(ev.get("festival_name") or ev.get("title"), 200)
            result.events.append(raw)
        return result


@register
class SongkickProvider(CrawlerProvider):
    key = "songkick"
    label = "Songkick"
    scopes = ("artist",)
    default_trust = 5
    api_key_name = "songkick"
    BASE = "https://api.songkick.com/api/3.0"

    def fetch(self, ctx: ProviderContext, source: SourceSpec, artist: ArtistSpec | None) -> ProviderResult:
        assert artist is not None
        api_key = ctx.api_key("songkick")
        if not api_key:
            raise CrawlError("config", "Kein Songkick-API-Schlüssel")
        result = ProviderResult(method="api")
        sk_id = source.config.get("songkick_id") or (artist.external_ids or {}).get("songkick")
        try:
            if not sk_id:
                data = ctx.http.fetch_json(f"{self.BASE}/search/artists.json", params={"apikey": api_key, "query": artist.name}, api=True)
                result.pages += 1
                for a in ((data.get("resultsPage") or {}).get("results") or {}).get("artist", []):
                    if _name_matches(a.get("displayName"), artist):
                        sk_id = a.get("id")
                        break
                if not sk_id:
                    result.warnings.append("Künstler bei Songkick nicht gefunden")
                    return result
                result.discovered["songkick_id"] = sk_id
                result.artist_updates["songkick"] = sk_id
            data = ctx.http.fetch_json(f"{self.BASE}/artists/{sk_id}/calendar.json", params={"apikey": api_key, "per_page": 50}, api=True)
            result.pages += 1
        except CrawlError as exc:
            raise _auth_error(exc, self.label) from exc
        for ev in ((data.get("resultsPage") or {}).get("results") or {}).get("event", []):
            start = ev.get("start") or {}
            d, t, tz = parse_iso_datetime(start.get("datetime") or start.get("date"))
            if d is None:
                continue
            raw = RawEvent(start_date=d, start_time=t, method="api", confidence=0.8, external_id=str(ev.get("id"))[:200])
            raw.extra["tzinfo"] = tz
            raw.title = clean_text(ev.get("displayName"), 300)
            raw.url = safe_url(ev.get("uri"))
            status = str(ev.get("status") or "").casefold()
            raw.status = "cancelled" if status == "cancelled" else "postponed" if status == "postponed" else None
            venue = ev.get("venue") or {}
            raw.venue_name = clean_text(venue.get("displayName"), 200)
            metro = venue.get("metroArea") or {}
            city = (ev.get("location") or {}).get("city") or metro.get("displayName")
            if city and "," in city:
                parts = [p.strip() for p in city.split(",")]
                raw.city, raw.country = parts[0], parts[-1]
            else:
                raw.city = city
            raw.country = raw.country or ((metro.get("country") or {}).get("displayName"))
            raw.performers = [p.get("displayName") or (p.get("artist") or {}).get("displayName") for p in ev.get("performance") or []]
            raw.performers = [p for p in raw.performers if p]
            billing = {p.get("billing") for p in ev.get("performance") or [] if _name_matches(p.get("displayName"), artist)}
            if "support" in billing:
                raw.event_type_hint = "support"
            if str(ev.get("type") or "").casefold() == "festival":
                raw.event_type_hint = "festival"
                raw.festival_name = clean_text((ev.get("series") or {}).get("displayName") or ev.get("displayName"), 200)
            result.events.append(raw)
        result.http_status = 200
        return result
