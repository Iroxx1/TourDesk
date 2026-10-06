"""ArtistCrawler job: crawl all sources of one artist, merge events, notify."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tourdesk.core.text import url_domain
from tourdesk.core.timeutil import utcnow
from tourdesk.models import Artist, CrawlerJob, Source
from tourdesk.services.notifications import complete_baselines, dispatch_changes
from tourdesk_crawler.jobs.common import (
    RunRecorder,
    artist_spec,
    as_crawl_error,
    is_monitored,
    mark_source_failure,
    mark_source_success,
    next_crawl_time,
    source_spec,
    summary_footer,
    summary_header,
)
from tourdesk_crawler.jobs.context import provider_context
from tourdesk_crawler.pipeline.matcher import ArtistMatcher
from tourdesk_crawler.pipeline.normalizer import NormalizeContext, normalize
from tourdesk_crawler.pipeline.store import EventStore
from tourdesk_crawler.providers.base import RunLog, get_provider

API_PROVIDERS = (("ticketmaster", "Ticketmaster", 4), ("bandsintown", "Bandsintown", 4), ("songkick", "Songkick", 5))


def ensure_auto_sources(db: Session, artist: Artist, settings: dict[str, Any], api_keys: dict[str, str | None]) -> None:
    existing = {s.provider for s in db.execute(select(Source).where(Source.artist_id == artist.id)).scalars()}
    providers = settings.get("providers") or {}
    for key, label, trust in API_PROVIDERS:
        if key in existing or not api_keys.get(key) or not providers.get(key, True):
            continue
        db.add(Source(scope="artist", provider=key, name=label, url=None, artist_id=artist.id, trust_level=trust,
                      is_enabled=True, is_auto=True, config={}))
    if artist.official_website and "official_website" not in existing:
        db.add(Source(scope="artist", provider="official_website", name=f"Offizielle Website ({url_domain(artist.official_website)})",
                      url=artist.official_website, artist_id=artist.id, trust_level=1, is_enabled=True, is_auto=True,
                      config={"discover": True}))
    if artist.is_demo and "demo" not in existing:
        db.add(Source(scope="artist", provider="demo", name="Demo-Tourdaten", artist_id=artist.id, trust_level=1,
                      is_enabled=True, is_auto=True, config={}))
    db.flush()


def run_artist_crawl(db: Session, session_factory: sessionmaker[Session], job: CrawlerJob | None, artist_id: int,
                     *, force: bool = False) -> dict[str, Any]:
    artist = db.get(Artist, artist_id)
    if artist is None:
        return {"status": "skipped", "reason": "Künstler existiert nicht mehr"}
    manual = force or (job is not None and job.reason in ("manual", "new_artist"))
    if not manual and not is_monitored(db, artist_id):
        artist.next_crawl_at = None
        db.commit()
        return {"status": "skipped", "reason": "Kein aktiver Benutzer überwacht diesen Künstler"}

    now = utcnow()
    runlog = RunLog()
    summary_header(runlog, f"Artist: {artist.name}", now)
    recorder = RunRecorder(db, job, job_type="artist_crawl", label=artist.name, artist_id=artist.id)
    stats: dict[str, Any] = {"sources_total": 0, "sources_ok": 0, "sources_failed": 0, "events_found": 0,
                             "events_new": 0, "events_updated": 0, "events_removed": 0}
    first_error: str | None = None
    with provider_context(db, session_factory, runlog=runlog, manual=manual) as ctx:
        settings = ctx.settings
        interval = int(settings.get("interval_minutes", 60))
        ensure_auto_sources(db, artist, settings, {k: ctx.api_key(k) for k, _l, _t in API_PROVIDERS})
        # commit the new sources now: the rollback after a failing source must not discard them
        # (they would stay in the session as deleted rows → ObjectDeletedError on the next source)
        db.commit()
        sources = list(
            db.execute(
                select(Source).where(Source.artist_id == artist.id, Source.is_enabled.is_(True)).order_by(Source.trust_level, Source.id)
            ).scalars()
        )
        aspec = artist_spec(artist)
        store = EventStore(db, artist.id, today=ctx.today, now=now)
        crawled_ok: set[int] = set()
        runlog.info("")
        for source in sources:
            provider = get_provider(source.provider)
            if provider is None:
                runlog.fail(f"{source.name}: unbekannter Provider '{source.provider}'")
                continue
            reason = provider.unavailable_reason(ctx)
            if reason:
                runlog.info(f"  – {source.name}: übersprungen ({reason})")
                continue
            if not manual and source.next_attempt_at and source.next_attempt_at > now:
                runlog.info(f"  – {source.name}: pausiert bis {source.next_attempt_at:%d.%m. %H:%M} (Backoff nach Fehlern)")
                continue
            stats["sources_total"] += 1
            spec = source_spec(db, source)
            t0 = time.perf_counter()
            try:
                result = provider.fetch(ctx, spec, aspec)
            except Exception as exc:  # noqa: BLE001 - one broken source must never stop the crawl
                db.rollback()
                ce = as_crawl_error(exc)
                retry_at = mark_source_failure(source, ce, now=now, interval_minutes=interval,
                                               backoff_max_hours=int(settings.get("source_backoff_max_hours", 24)))
                recorder.error(exc, source=source, retry_at=retry_at)
                runlog.fail(f"{source.name}: {ce}")
                stats["sources_failed"] += 1
                first_error = first_error or str(ce)
                db.commit()
                continue
            duration = int((time.perf_counter() - t0) * 1000)
            raws = result.events
            if provider.needs_artist_match:
                matcher = ArtistMatcher([aspec])
                raws = [r for r in raws if not (r.title or r.performers) or matcher.match(r)]
            normalized = []
            for raw in raws:
                n, _why = normalize(raw, NormalizeContext(aspec, spec, ctx.today, ctx.geo))
                if n is not None:
                    normalized.append(n)
            suspicious = not normalized and (source.last_event_count or 0) >= 3 and not result.events
            for n in normalized:
                store.add(n, spec)
            if result.artist_updates:
                artist.external_ids = {**(artist.external_ids or {}), **result.artist_updates}
            mark_source_success(source, result, duration_ms=duration, events=len(normalized), now=now)
            if suspicious:
                source.status = "warning"
                source.last_error = "Quelle lieferte plötzlich keine Termine mehr – bestehende Termine bleiben erhalten"
                runlog.warn(f"{source.name}: keine Termine (vorher {source.last_event_count}) – Entfernen übersprungen")
            else:
                crawled_ok.add(source.id)
            stats["sources_ok"] += 1
            stats["events_found"] += len(normalized)
            method = f" [{result.method}]" if result.method else ""
            runlog.ok(f"{source.name} – {len(normalized)} Events{method}, {duration} ms")
            for w in result.warnings[:5]:
                runlog.warn(w)
            db.commit()
        store.deactivate_missing(crawled_ok)
        changes, st = store.finalize()
        stats["events_new"], stats["events_updated"], stats["events_removed"] = st["new"], st["updated"], st["removed"]
        stats["notifications"] = dispatch_changes(db, artist.id, changes)
        if crawled_ok:
            complete_baselines(db, artist.id)
        artist.last_crawled_at = now
        if stats["sources_ok"]:
            artist.last_success_at = now
        if stats["sources_total"] == 0:
            artist.crawl_status = "ok" if artist.last_success_at else "pending"
        elif stats["sources_failed"] == 0:
            artist.crawl_status = "ok"
        elif stats["sources_ok"]:
            artist.crawl_status = "partial"
        else:
            artist.crawl_status = "error"
        artist.last_error = first_error
        artist.next_crawl_at = next_crawl_time(now, interval)
    summary_footer(runlog, stats, recorder.errors)
    status = "success" if stats["sources_failed"] == 0 else ("partial" if stats["sources_ok"] else "failed")
    if stats["sources_total"] == 0:
        status = "success"
    recorder.finish(status, stats, runlog)
    return {"status": status, **stats}
