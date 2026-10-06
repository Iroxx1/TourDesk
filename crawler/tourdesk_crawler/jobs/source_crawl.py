"""VenueCrawler / FestivalCrawler / global sources: one source, all monitored artists."""

from __future__ import annotations

import copy
import time
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tourdesk.core.timeutil import utcnow
from tourdesk.models import CrawlerJob, Event, EventSource, Source
from tourdesk.services.notifications import dispatch_changes
from tourdesk_crawler.jobs.common import (
    RunRecorder,
    as_crawl_error,
    mark_source_failure,
    mark_source_success,
    monitored_artists,
    source_spec,
    summary_footer,
    summary_header,
)
from tourdesk_crawler.jobs.context import provider_context
from tourdesk_crawler.pipeline.matcher import ArtistMatcher
from tourdesk_crawler.pipeline.normalizer import NormalizeContext, normalize
from tourdesk_crawler.pipeline.store import EventStore
from tourdesk_crawler.providers.base import RunLog, get_provider

DEFAULT_INTERVALS = {"venue": 60, "festival": 360, "global": 120}


def run_source_crawl(db: Session, session_factory: sessionmaker[Session], job: CrawlerJob | None, source_id: int,
                     *, force: bool = False) -> dict[str, Any]:
    source = db.get(Source, source_id)
    if source is None:
        return {"status": "skipped", "reason": "Quelle existiert nicht mehr"}
    if not source.is_enabled and not force:
        return {"status": "skipped", "reason": "Quelle ist deaktiviert"}
    provider = get_provider(source.provider)
    if provider is None:
        return {"status": "failed", "reason": f"Unbekannter Provider {source.provider}"}
    artists = monitored_artists(db)
    if not artists:
        return {"status": "skipped", "reason": "Keine überwachten Künstler"}

    now = utcnow()
    runlog = RunLog()
    summary_header(runlog, f"Quelle: {source.name}", now)
    recorder = RunRecorder(db, job, job_type="source_crawl", label=source.name, source_id=source.id)
    stats: dict[str, Any] = {"sources_total": 1, "sources_ok": 0, "sources_failed": 0, "events_found": 0,
                             "events_new": 0, "events_updated": 0, "events_removed": 0, "artists_matched": 0}
    manual = force or (job is not None and job.reason == "manual")
    with provider_context(db, session_factory, runlog=runlog, manual=manual) as ctx:
        reason = provider.unavailable_reason(ctx)
        if reason:
            runlog.info(f"  – übersprungen: {reason}")
            summary_footer(runlog, stats, 0)
            recorder.finish("success", stats, runlog)
            return {"status": "skipped", "reason": reason}
        spec = source_spec(db, source)
        interval = source.crawl_interval_minutes or DEFAULT_INTERVALS.get(source.scope, 60)
        t0 = time.perf_counter()
        try:
            result = provider.fetch(ctx, spec, None)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            ce = as_crawl_error(exc)
            retry_at = mark_source_failure(source, ce, now=now, interval_minutes=interval,
                                           backoff_max_hours=int(ctx.settings.get("source_backoff_max_hours", 24)))
            recorder.error(exc, source=source, retry_at=retry_at)
            runlog.fail(f"{source.name}: {ce}")
            stats["sources_failed"] = 1
            db.commit()
            summary_footer(runlog, stats, recorder.errors)
            recorder.finish("failed", stats, runlog)
            return {"status": "failed", "error": str(ce)}
        duration = int((time.perf_counter() - t0) * 1000)

        matcher = ArtistMatcher(artists)
        by_id = {a.id: a for a in artists}
        normalized: dict[int, list] = defaultdict(list)
        for raw in result.events:
            for match in matcher.match(raw):
                # festival line-ups: only exact performer matches count as confirmation
                if spec.scope == "festival" and match.via != "performer":
                    continue
                artist = by_id[match.artist_id]
                clone = copy.copy(raw)
                clone.extra = dict(raw.extra)
                n, _why = normalize(clone, NormalizeContext(artist, spec, ctx.today, ctx.geo, role=match.role))
                if n is not None:
                    normalized[artist.id].append(n)
        # artists that had observations from this source before (to detect removals)
        previous = set(
            db.execute(
                select(Event.artist_id)
                .join(EventSource, EventSource.event_id == Event.id)
                .where(EventSource.source_id == source.id, EventSource.is_active.is_(True))
                .distinct()
            ).scalars()
        )
        found = sum(len(v) for v in normalized.values())
        suspicious = not result.events and (source.last_event_count or 0) >= 3
        mark_source_success(source, result, duration_ms=duration, events=found, now=now)
        stats["sources_ok"] = 1
        stats["events_found"] = found
        stats["artists_matched"] = len(normalized)
        runlog.info("")
        runlog.ok(f"{len(result.events)} Einträge gelesen [{result.method or '-'}], {duration} ms")
        if result.lineup:
            runlog.info(f"  Line-up: {len(result.lineup)} Namen")
        for artist_id in sorted(set(normalized) | previous):
            artist = by_id.get(artist_id)
            if artist is None:
                continue
            store = EventStore(db, artist_id, today=ctx.today, now=now)
            for n in normalized.get(artist_id, []):
                store.add(n, spec)
            if not suspicious:
                store.deactivate_missing({source.id})
            changes, st = store.finalize()
            stats["events_new"] += st["new"]
            stats["events_updated"] += st["updated"]
            stats["events_removed"] += st["removed"]
            dispatch_changes(db, artist_id, changes)
            if normalized.get(artist_id):
                runlog.ok(f"{artist.name}: {len(normalized[artist_id])} Termine (neu {st['new']}, geändert {st['updated']})")
            db.commit()
        if suspicious:
            source.status = "warning"
            source.last_error = "Quelle lieferte plötzlich keine Termine mehr – bestehende Termine bleiben erhalten"
        for w in result.warnings[:5]:
            runlog.warn(w)
        db.commit()
    summary_footer(runlog, stats, recorder.errors)
    recorder.finish("success", stats, runlog)
    return {"status": "success", **stats}
