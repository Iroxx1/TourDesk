"""Shared helpers for crawl jobs: specs, source health, run records, summaries."""

from __future__ import annotations

import logging
import random
import time
import traceback
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from tourdesk.core.timeutil import utcnow
from tourdesk.models import Artist, City, Country, CrawlerError, CrawlerJob, CrawlerRun, Festival, Source, User, UserArtist, Venue
from tourdesk_crawler.http.errors import CrawlError
from tourdesk_crawler.pipeline.models import ArtistSpec, FestivalSpec, ProviderResult, SourceSpec, VenueSpec
from tourdesk_crawler.providers.base import RunLog

log = logging.getLogger("tourdesk.crawler")
summary_log = logging.getLogger("tourdesk.crawler.summary")

PERMANENT_ERRORS = {"robots_blocked", "ssrf_blocked", "config", "auth", "unsupported"}


def artist_spec(a: Artist) -> ArtistSpec:
    return ArtistSpec(
        id=a.id,
        name=a.name,
        aliases=tuple(a.alias_names),
        search_terms=tuple(a.search_terms or ()),
        official_website=a.official_website,
        external_ids=dict(a.external_ids or {}),
        is_demo=a.is_demo,
    )


def source_spec(db: Session, s: Source) -> SourceSpec:
    venue_spec = festival_spec = None
    if s.venue_id:
        v = db.get(Venue, s.venue_id)
        if v is not None:
            city = db.get(City, v.city_id) if v.city_id else None
            country = db.get(Country, city.country_id) if city else None
            venue_spec = VenueSpec(v.id, v.name, v.city_id, city.display_name if city else None, country.code if country else None, v.website)
    if s.festival_id:
        f = db.get(Festival, s.festival_id)
        if f is not None:
            city = db.get(City, f.city_id) if f.city_id else None
            country = db.get(Country, city.country_id) if city else None
            venue = db.get(Venue, f.venue_id) if f.venue_id else None
            festival_spec = FestivalSpec(
                f.id, f.name, tuple(f.aliases or ()), f.city_id, city.name if city else None, f.venue_id,
                venue.name if venue else None, country.code if country else None, f.website, f.typical_month,
            )
    return SourceSpec(
        id=s.id, scope=s.scope, provider=s.provider, name=s.name, url=s.url, trust_level=s.trust_level,
        config=dict(s.config or {}), artist_id=s.artist_id, venue=venue_spec, festival=festival_spec,
    )


def monitored_artist_query():
    return (
        select(Artist)
        .where(
            exists(
                select(UserArtist.id)
                .join(User, User.id == UserArtist.user_id)
                .where(UserArtist.artist_id == Artist.id, UserArtist.is_active.is_(True), User.is_active.is_(True))
            )
        )
    )


def monitored_artists(db: Session) -> list[ArtistSpec]:
    return [artist_spec(a) for a in db.execute(monitored_artist_query()).unique().scalars()]


def is_monitored(db: Session, artist_id: int) -> bool:
    return db.execute(monitored_artist_query().where(Artist.id == artist_id)).first() is not None


# ----------------------------------------------------------------------------------- health
def _apply_discovered(source: Source, result: ProviderResult) -> None:
    if not result.discovered:
        return
    cfg = dict(source.config or {})
    for key, value in result.discovered.items():
        if value is None:
            cfg.pop(key, None)
        else:
            cfg[key] = value
    source.config = cfg


def mark_source_success(source: Source, result: ProviderResult, *, duration_ms: int, events: int, now: datetime) -> None:
    source.total_runs += 1
    source.last_attempt_at = now
    source.last_success_at = now
    source.consecutive_failures = 0
    source.next_attempt_at = None
    source.last_http_status = result.http_status
    source.last_duration_ms = duration_ms
    source.last_event_count = events
    source.last_method = result.method
    source.status = "ok" if events or not result.warnings else "warning"
    source.last_error = "; ".join(result.warnings)[:1000] if result.warnings else None
    source.last_error_type = "no_events" if not events and result.warnings else None
    _apply_discovered(source, result)


def mark_source_failure(source: Source, exc: CrawlError, *, now: datetime, interval_minutes: int, backoff_max_hours: int) -> datetime:
    source.total_runs += 1
    source.total_failures += 1
    source.consecutive_failures += 1
    source.last_attempt_at = now
    source.last_error_at = now
    source.last_error = str(exc)[:1000]
    source.last_error_type = exc.error_type
    source.last_http_status = exc.status_code
    source.status = "error"
    if exc.error_type in PERMANENT_ERRORS:
        delay = timedelta(hours=backoff_max_hours)
    else:
        delay = timedelta(minutes=interval_minutes * (2 ** (source.consecutive_failures - 1)))
        delay = min(delay, timedelta(hours=backoff_max_hours))
    if exc.retry_after:
        delay = max(delay, timedelta(seconds=exc.retry_after))
    source.next_attempt_at = now + delay
    return source.next_attempt_at


def next_crawl_time(now: datetime, interval_minutes: int) -> datetime:
    jitter = random.uniform(-0.1, 0.1) * interval_minutes
    return now + timedelta(minutes=interval_minutes + jitter)


def as_crawl_error(exc: BaseException) -> CrawlError:
    if isinstance(exc, CrawlError):
        return exc
    return CrawlError("parse_error", f"{exc.__class__.__name__}: {str(exc)[:300]}")


# ----------------------------------------------------------------------------------- runs
class RunRecorder:
    def __init__(self, db: Session, job: CrawlerJob | None, *, job_type: str, label: str,
                 artist_id: int | None = None, source_id: int | None = None) -> None:
        self.db = db
        self.started = time.perf_counter()
        self.errors = 0
        self.run = CrawlerRun(
            job_id=job.id if job else None,
            job_type=job_type,
            trigger=job.reason if job else "manual",
            artist_id=artist_id,
            source_id=source_id,
            label=label[:255],
            started_at=utcnow(),
            status="running",
        )
        db.add(self.run)
        db.commit()

    def error(self, exc: BaseException, *, source: Source | None = None, artist_id: int | None = None, retry_at: datetime | None = None) -> None:
        ce = as_crawl_error(exc)
        details = None
        if not isinstance(exc, CrawlError):
            details = "".join(traceback.format_exception(exc))[-4000:]
        from tourdesk.core.text import url_domain

        url = ce.url or (source.url if source else None)
        self.db.add(
            CrawlerError(
                run_id=self.run.id,
                job_id=self.run.job_id,
                source_id=source.id if source else None,
                artist_id=artist_id if artist_id is not None else self.run.artist_id,
                domain=url_domain(url) if url and "://" in url else url,
                url=(url or "")[:1000] or None,
                error_type=ce.error_type,
                status_code=ce.status_code,
                message=ce.message[:2000],
                details=details,
                retry_at=retry_at,
            )
        )
        self.errors += 1

    def finish(self, status: str, stats: dict[str, Any], runlog: RunLog) -> CrawlerRun:
        run = self.run
        run.finished_at = utcnow()
        run.duration_ms = int((time.perf_counter() - self.started) * 1000)
        run.status = status
        for key in ("sources_total", "sources_ok", "sources_failed", "events_found", "events_new", "events_updated", "events_removed"):
            setattr(run, key, int(stats.get(key, 0)))
        run.errors_count = self.errors
        run.summary = {k: v for k, v in stats.items() if isinstance(v, (int, float, str, bool, type(None)))}
        run.log = runlog.text()
        self.db.commit()
        summary_log.info(runlog.text())
        log.info(
            "crawl finished: %s", run.label,
            extra={"event": "crawler.run", "job_type": run.job_type, "status": status, "duration_ms": run.duration_ms,
                   **{k: stats.get(k) for k in ("events_found", "events_new", "events_updated", "events_removed")}, "errors": self.errors},
        )
        return run


def summary_header(runlog: RunLog, title: str, now: datetime | None = None) -> None:
    from tourdesk.core.timeutil import DEFAULT_TZ
    from zoneinfo import ZoneInfo

    local = (now or utcnow()).astimezone(ZoneInfo(DEFAULT_TZ))
    runlog.info(local.strftime("%d.%m.%Y %H:%M"))
    runlog.info("Crawler gestartet")
    runlog.info("")
    runlog.info(title)


def summary_footer(runlog: RunLog, stats: dict[str, Any], errors: int) -> None:
    runlog.info("")
    runlog.info(f"Sources: {stats.get('sources_total', 0)}")
    runlog.info(f"Events gefunden: {stats.get('events_found', 0)}")
    runlog.info(f"Neue Events: {stats.get('events_new', 0)}")
    runlog.info(f"Geänderte Events: {stats.get('events_updated', 0)}")
    runlog.info(f"Entfernte Events: {stats.get('events_removed', 0)}")
    runlog.info(f"Fehler: {errors}")
    runlog.info("")
    runlog.info("Crawler abgeschlossen")
