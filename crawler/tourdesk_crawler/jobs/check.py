"""Dry run of a single source for the admin "Quelle prüfen" button (nothing is saved)."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from tourdesk.models import Artist, Source
from tourdesk_crawler.jobs.common import artist_spec, as_crawl_error, monitored_artists, source_spec
from tourdesk_crawler.jobs.context import provider_context
from tourdesk_crawler.pipeline.matcher import ArtistMatcher
from tourdesk_crawler.providers.base import get_provider


def run_source_check(db: Session, session_factory: sessionmaker[Session], source_id: int) -> dict[str, Any]:
    source = db.get(Source, source_id)
    if source is None:
        return {"ok": False, "error": "Quelle existiert nicht mehr"}
    provider = get_provider(source.provider)
    if provider is None:
        return {"ok": False, "error": f"Unbekannter Provider {source.provider}"}
    artist = db.get(Artist, source.artist_id) if source.artist_id else None
    spec = source_spec(db, source)
    with provider_context(db, session_factory, dry_run=True) as ctx:
        reason = provider.unavailable_reason(ctx)
        if reason:
            return {"ok": False, "error": reason}
        t0 = time.perf_counter()
        try:
            result = provider.fetch(ctx, spec, artist_spec(artist) if artist else None)
        except Exception as exc:  # noqa: BLE001
            ce = as_crawl_error(exc)
            db.rollback()
            return {"ok": False, "error": str(ce), "error_type": ce.error_type, "status_code": ce.status_code,
                    "duration_ms": int((time.perf_counter() - t0) * 1000)}
        duration = int((time.perf_counter() - t0) * 1000)
        matched: dict[str, int] = {}
        if spec.scope != "artist":
            artists = monitored_artists(db)
            matcher = ArtistMatcher(artists)
            names = {a.id: a.name for a in artists}
            for raw in result.events:
                for m in matcher.match(raw):
                    matched[names[m.artist_id]] = matched.get(names[m.artist_id], 0) + 1
        sample = []
        for raw in result.events[:40]:
            sample.append({
                "date": raw.start_date.isoformat() if raw.start_date else None,
                "time": raw.start_time.strftime("%H:%M") if raw.start_time else None,
                "title": raw.title,
                "performers": raw.performers[:5],
                "venue": raw.venue_name,
                "city": raw.city,
                "country": raw.country,
                "status": raw.status,
                "ticket_status": raw.ticket_status,
                "ticket_url": raw.ticket_url,
                "type": raw.event_type_hint,
                "method": raw.method,
            })
        db.rollback()
        return {
            "ok": True,
            "method": result.method,
            "pages": result.pages,
            "http_status": result.http_status,
            "duration_ms": duration,
            "events_total": len(result.events),
            "events": sample,
            "warnings": result.warnings,
            "discovered": {k: v for k, v in result.discovered.items() if isinstance(v, (str, int, float, list, dict))},
            "lineup_count": len(result.lineup),
            "lineup_sample": result.lineup[:30],
            "matched_artists": matched,
            "http_stats": ctx.http.stats,
        }
