"""Stores the complete programme of a venue source in ``venue_listings`` (all artists)."""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tourdesk.core.text import normalize_name
from tourdesk.models import VenueListing
from tourdesk.services.programme import guess_artists, split_genre
from tourdesk_crawler.pipeline.models import RawEvent

MAX_LISTINGS = 1000


def listing_key(raw: RawEvent) -> str:
    if raw.external_id:
        return f"x:{raw.external_id}"[:255]
    title = normalize_name(raw.title or " ".join(raw.performers))
    digest = hashlib.sha1(title.encode(), usedforsecurity=False).hexdigest()[:16]
    when = raw.start_time.strftime("%H%M") if raw.start_time else ""
    return f"d:{raw.start_date.isoformat() if raw.start_date else ''}:{when}:{digest}"


def store_listings(db: Session, *, source_id: int, venue_id: int, events: list[RawEvent], today: date, now: datetime,
                   replace: bool = True) -> int:
    """Upsert the source's upcoming entries; entries the source no longer lists are removed (``replace``)."""
    existing = {row.listing_key: row for row in db.execute(select(VenueListing).where(VenueListing.source_id == source_id)).scalars()}
    seen: set[str] = set()
    for raw in events:
        if raw.start_date is None or raw.start_date < today:
            continue
        if not (raw.title or raw.performers):
            continue
        key = listing_key(raw)
        if key in seen:
            continue
        if len(seen) >= MAX_LISTINGS:
            break
        seen.add(key)
        row = existing.get(key)
        if row is None:
            row = VenueListing(source_id=source_id, venue_id=venue_id, listing_key=key, first_seen_at=now)
            db.add(row)
        title, genre = split_genre(raw.title)
        row.venue_id = venue_id
        row.event_date = raw.start_date
        row.start_time = raw.start_time
        row.title = (title or "")[:500] or None
        row.performers = [p[:200] for p in raw.performers if p][:30]
        row.artists = guess_artists(title, raw.performers)
        row.category = ((raw.extra or {}).get("category") or genre or "")[:80] or None
        row.status = raw.status or "scheduled"
        row.url = (raw.url or "")[:1000] or None
        row.ticket_url = (raw.ticket_url or "")[:1000] or None
        row.last_seen_at = now
    stale = [k for k, row in existing.items() if k not in seen and (replace or row.event_date < today)]
    if stale:
        db.execute(delete(VenueListing).where(VenueListing.source_id == source_id, VenueListing.listing_key.in_(stale)))
    db.flush()
    return len(seen)
