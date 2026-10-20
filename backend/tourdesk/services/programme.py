"""Complete programme of selected venues ("Programm" window).

The venue sources (programme page, Ticketmaster) normally only keep events of monitored artists.
For venues a user has selected, the crawler additionally stores *every* entry in ``venue_listings``;
from there the user can follow single artists.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tourdesk.core.text import normalize_name, normalize_variants
from tourdesk.core.timeutil import local_today
from tourdesk.models import (
    Artist,
    ArtistAlias,
    CatalogEntry,
    CrawlerJob,
    Source,
    User,
    UserArtist,
    UserVenue,
    Venue,
    VenueListing,
)
from tourdesk.services.app_settings import api_key
from tourdesk.services.jobs import PRIORITY_MANUAL, enqueue_job

TM_VENUE = "ticketmaster_venue"
TM_VENUE_INTERVAL = 720  # Minuten – das Programm eines Ortes ändert sich langsam
MAX_ARTISTS = 6

# ------------------------------------------------------------------------------- artist names
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_PRESENTS = re.compile(r"^.{0,80}?\b(?:presents|präsentiert|pres\.)\s*:?\s+", re.I)
_PREFIX = re.compile(r"^(?:konzert|live|concert|ausverkauft|sold out|neuer termin|zusatzkonzert|zusatzshow|verlegt)\s*[:!–—-]\s*", re.I)
# "Band – Tour 2027", "Band | Live", "Band: Die Jubiläumstour"
_PARTS = re.compile(r"\s+[–—|]\s+|\s+-{1,2}\s+|\s*:\s+")
# "Headliner – Support: Vorband", "Headliner (special guest: X)" – brackets are removed before
_SUPPORT = re.compile(r"(?:^|[\s,;|–—-])(?:support|special guests?|support acts?|vorband)\s*:\s*(.+)$", re.I)
# several artists in one title; "&" and "und" stay (Mumford & Sons, Simon und Garfunkel)
_NAMES = re.compile(
    r"\s+\+\s+|\s+(?:with\s+|w/\s*|\+\s*|and\s+)?special\s+guests?:?\s+|\s+(?:feat\.?|ft\.?|featuring|support:?|w/|plus|vs\.?)\s+|\s+/\s+",
    re.I,
)
# Programmseiten wie rockhal.lu hängen das Genre an: "URIAH HEEP Rock", "TIMMY TRUMPET Electro/Clubbing"
_GENRE = (
    r"(?:(?:french|german|deutsch|latin|indie|hard|classic|progressive|k-|j-)\s*)?"
    r"(?:pop|rock|metal|alternative|electro|electronic|clubbing|hip-hop|hip hop|rap|comedy|humour|humor|jazz|blues|soul|funk|"
    r"reggae|punk|folk|country|classical|classique|klassik|schlager|world|world music|r&b|rnb|singer-songwriter|chanson|"
    r"variété|variete|dance|techno|house|kids|family|musical|show|urban|edm|gospel|ska|emo|hardcore|grunge|cabaret|"
    r"kabarett|theater|theatre|other|divers)"
)
_TRAILING_GENRE = re.compile(rf"\s+({_GENRE}(?:\s*/\s*{_GENRE})*)\s*$", re.I)


def split_genre(title: str | None) -> tuple[str | None, str | None]:
    """``"URIAH HEEP Rock"`` -> ``("URIAH HEEP", "Rock")``.

    Only when the word before is written in capitals and the genre is not, so names like
    "Kid Rock", "Iggy Pop" or "KID ROCK" stay untouched.
    """
    if not title:
        return title, None
    m = _TRAILING_GENRE.search(title)
    if not m:
        return title, None
    head, genre = title[: m.start()].strip(), m.group(1).strip()
    last = head.split()[-1] if head.split() else ""
    if sum(c.isalpha() for c in last) < 2 or last != last.upper() or genre == genre.upper():
        return title, None
    return head, genre
_TRAILING = re.compile(
    r"[\s,.!-]+(?:live(?: in [\w .-]+)?|in concert|konzert|tour|world tour|europe(?:an)? tour|(?:19|20)\d\d(?:/\d\d)?|"
    r"open air|unplugged|acoustic|zusatzkonzert|zusatzshow|ausverkauft|sold out)$",
    re.I,
)


def _clean_name(value: str) -> str:
    value = value.strip(" \t\"'„“”‚‘’»«*.,;!-–—")
    while True:
        shorter = _TRAILING.sub("", value).strip(" \t\"'„“”*.,;!-–—")
        if shorter == value or not shorter:
            return value
        value = shorter


def guess_artists(title: str | None, performers: list[str] | None = None) -> list[str]:
    """Artist names to offer for an entry: the source's performers, otherwise read from the title.

    Titles are only guessed ("Band – Tour 2027", "A + B", "A feat. B", "Support: C"), so the
    window shows them as suggestions; the user decides what to follow.
    """
    out: dict[str, str] = {}

    def add(name: str) -> None:
        name = " ".join(_clean_name(name).split())
        key = normalize_name(name)
        if 2 <= len(name) <= 120 and key and key not in out:
            out[key] = name

    for p in performers or []:
        if p and p.strip():
            add(p)
    if out or not title:
        return list(out.values())[:MAX_ARTISTS]
    text = _BRACKETS.sub(" ", title)
    text = _PRESENTS.sub("", text) or text
    text = _PREFIX.sub("", text.strip())
    support = _SUPPORT.search(text)
    if support:
        text = text[: support.start()]
    parts = [p for p in _PARTS.split(text) if p.strip()]
    if parts:
        for name in _NAMES.split(parts[0]):
            add(name)
    if support:
        for part in _PARTS.split(support.group(1)):
            for name in _NAMES.split(part):
                add(name)
    return list(out.values())[:MAX_ARTISTS]


# ------------------------------------------------------------------------------- sources
def at_venue(venue: Venue | None, venue_name: str | None) -> bool:
    """Does an entry's location name mean this venue ("Saarlandhalle", "Rockhal Club" for Rockhal)?"""
    if venue is None or not venue_name:
        return False
    found = normalize_variants(venue_name)
    wanted = normalize_variants(venue.name) | set(venue.aliases_norm or [])
    return any(w == f or (len(w) >= 4 and w in f) for w in wanted for f in found)


def programme_venue_ids(db: Session) -> set[int]:
    """Venues selected by at least one active user – only for these the whole programme is kept."""
    return set(db.execute(
        select(UserVenue.venue_id).join(User, User.id == UserVenue.user_id).where(User.is_active.is_(True))
    ).scalars())


def ensure_programme_sources(db: Session, venue: Venue, *, created_by: int | None = None) -> list[Source]:
    """Create the Ticketmaster source of a selected venue (if a key is set); return all its venue sources."""
    sources = list(db.execute(select(Source).where(Source.venue_id == venue.id, Source.scope == "venue")).scalars())
    if api_key(db, "ticketmaster") and not any(s.provider == TM_VENUE for s in sources):
        source = Source(
            scope="venue",
            provider=TM_VENUE,
            name=f"{venue.name} – Ticketmaster",
            venue_id=venue.id,
            trust_level=4,
            is_enabled=True,
            is_auto=True,
            config={"relevance": "favorites"},
            crawl_interval_minutes=TM_VENUE_INTERVAL,
            created_by_user_id=created_by,
        )
        db.add(source)
        db.flush()
        sources.append(source)
    return sources


def request_programme(db: Session, sources: list[Source], requested_by: int | None) -> bool:
    """Queue a crawl for enabled sources that never stored a programme yet. True while one is pending."""
    enabled = [s for s in sources if s.is_enabled]
    for s in enabled:
        if not (s.config or {}).get("programme_at"):
            enqueue_job(db, "source_crawl", source_id=s.id, priority=PRIORITY_MANUAL, reason="manual", requested_by=requested_by)
    ids = [s.id for s in enabled]
    if not ids:
        return False
    return db.execute(
        select(CrawlerJob.id).where(
            CrawlerJob.job_type == "source_crawl", CrawlerJob.source_id.in_(ids), CrawlerJob.status.in_(["queued", "running"])
        ).limit(1)
    ).first() is not None


# ------------------------------------------------------------------------------- read out
_catalog_cache: dict[str, Any] = {"at": 0.0, "index": {}}
_catalog_lock = threading.Lock()
CATALOG_TTL = 3600.0


def _catalog_index(db: Session) -> dict[str, tuple[str, str]]:
    """normalised name -> (mbid, name) of the artist catalogue; correct spelling for "VÉRONIQUE SANSON"."""
    with _catalog_lock:
        if time.monotonic() - _catalog_cache["at"] < CATALOG_TTL and _catalog_cache["index"]:
            return _catalog_cache["index"]
        index: dict[str, tuple[str, str]] = {}
        for mbid, name in db.execute(select(CatalogEntry.mbid, CatalogEntry.name).order_by(CatalogEntry.sort_key)):
            index.setdefault(normalize_name(name), (mbid, name))
        _catalog_cache.update(at=time.monotonic(), index=index)
        return index


def reset_catalog_index() -> None:
    with _catalog_lock:
        _catalog_cache.update(at=0.0, index={})


def _artist_lookup(db: Session, names: set[str]) -> dict[str, int]:
    """normalised variant -> artist id for every name (batch version of ``find_catalog_artist``)."""
    variants: dict[str, str] = {}
    for name in names:
        for v in normalize_variants(name):
            variants.setdefault(v, name)
    if not variants:
        return {}
    keys = list(variants)
    found: dict[str, int] = {}
    for artist_id, name_norm in db.execute(select(Artist.id, Artist.name_norm).where(Artist.name_norm.in_(keys)).order_by(Artist.id)):
        found.setdefault(name_norm, artist_id)
    for artist_id, alias_norm in db.execute(
        select(ArtistAlias.artist_id, ArtistAlias.alias_norm).where(ArtistAlias.alias_norm.in_(keys))
    ):
        found.setdefault(alias_norm, artist_id)
    return found


def _resolve(name: str, lookup: dict[str, int]) -> int | None:
    variants = normalize_variants(name)
    exact = normalize_name(name)
    if exact in lookup:
        return lookup[exact]
    return next((lookup[v] for v in sorted(variants) if v in lookup), None)


def _merge_key(row: VenueListing) -> str:
    first = row.artists[0] if row.artists else (row.title or "")
    return f"{row.event_date.isoformat()}|{normalize_name(first)}"


def venue_programme(db: Session, venue: Venue, user_id: int, *, today: date | None = None, limit: int = 600) -> list[dict[str, Any]]:
    """Upcoming programme entries of a venue, duplicates of several sources merged."""
    today = today or local_today()
    rows = list(db.execute(
        select(VenueListing, Source.provider)
        .join(Source, Source.id == VenueListing.source_id)
        .where(VenueListing.venue_id == venue.id, VenueListing.event_date >= today, Source.is_enabled.is_(True))
        .order_by(VenueListing.event_date, VenueListing.start_time.nulls_last(), VenueListing.id)
        .limit(limit * 2)
    ).all())
    merged: dict[str, dict[str, Any]] = {}
    for row, provider in rows:
        key = _merge_key(row)
        item = merged.get(key)
        if item is None:
            merged[key] = item = {
                "key": f"{row.id}", "date": row.event_date, "time": row.start_time, "title": row.title,
                "names": list(row.artists), "clean": provider == TM_VENUE, "category": row.category, "status": row.status,
                "url": row.url, "ticket_url": row.ticket_url, "providers": [provider],
            }
            continue
        if provider not in item["providers"]:
            item["providers"].append(provider)
        # Ticketmaster liefert saubere Künstlernamen und Kategorien
        if provider == TM_VENUE and row.artists and not item["clean"]:
            item["names"], item["clean"] = list(row.artists), True
        item["time"] = item["time"] or row.start_time
        item["category"] = item["category"] or row.category
        item["url"] = item["url"] or row.url
        item["ticket_url"] = item["ticket_url"] or row.ticket_url
        if row.status != "scheduled":
            item["status"] = row.status
    items = list(merged.values())[:limit]
    lookup = _artist_lookup(db, {n for it in items for n in it["names"]})
    catalog = _catalog_index(db)
    followed = set(db.execute(
        select(UserArtist.artist_id).where(UserArtist.user_id == user_id, UserArtist.is_active.is_(True))
    ).scalars())
    for it in items:
        artists = []
        for name in it.pop("names"):
            artist_id = _resolve(name, lookup)
            hit = catalog.get(normalize_name(name))
            if artist_id is None and hit:
                artist_id = _resolve(hit[1], lookup)
            artists.append({
                "name": hit[1] if hit else name,
                "artist_id": artist_id,
                "musicbrainz_id": hit[0] if hit else None,
                "followed": artist_id in followed if artist_id else False,
            })
        it["artists"] = artists
        it.pop("clean")
    return items


def programme_sources_out(sources: list[Source]) -> list[dict[str, Any]]:
    from tourdesk.core.constants import provider_label

    out = []
    for s in sources:
        if not s.is_enabled:
            continue
        cfg = s.config or {}
        out.append({
            "id": s.id,
            "provider": s.provider,
            "label": provider_label(s.provider),
            "status": s.status,
            "last_success_at": s.last_success_at,
            "programme_at": _parse_dt(cfg.get("programme_at")),
            "count": cfg.get("programme_count"),
            "message": s.last_error,
        })
    return out


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


__all__ = [
    "TM_VENUE",
    "ensure_programme_sources",
    "guess_artists",
    "programme_sources_out",
    "programme_venue_ids",
    "request_programme",
    "venue_programme",
]
