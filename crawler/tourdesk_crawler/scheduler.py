"""Scheduler: plans crawl jobs (about hourly per artist), source crawls, enrichment and maintenance.

Separate process (``tourdesk-scheduler``). It only writes jobs into the queue –
the worker executes them.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import exists, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tourdesk.core.config import get_settings
from tourdesk.core.db import get_session_factory
from tourdesk.core.logging import setup_logging
from tourdesk.core.timeutil import DEFAULT_TZ, utcnow
from tourdesk.models import (
    AppSetting,
    Artist,
    City,
    CrawlerJob,
    Festival,
    Source,
    SystemHeartbeat,
    User,
    UserArtist,
    UserCity,
    UserCountry,
    UserFilter,
    UserRegion,
    UserVenue,
    Venue,
)
from tourdesk.services.app_settings import crawler_settings
from tourdesk.services.filters import region_coverage
from tourdesk.services.jobs import enqueue_job, requeue_stale_jobs
from tourdesk_crawler.jobs.common import monitored_artist_query
from tourdesk_crawler.jobs.source_crawl import DEFAULT_INTERVALS

log = logging.getLogger("tourdesk.scheduler")

MAINTENANCE_HOUR = 3
MAX_ENQUEUE_PER_TICK = 200


def schedule_artists(db: Session, now: datetime, interval: int) -> int:
    rows = db.execute(
        monitored_artist_query()
        .where(or_(Artist.next_crawl_at.is_(None), Artist.next_crawl_at <= now))
        .where(~exists(select(CrawlerJob.id).where(
            CrawlerJob.artist_id == Artist.id, CrawlerJob.job_type == "artist_crawl", CrawlerJob.status.in_(["queued", "running"])
        )))
        .order_by(Artist.next_crawl_at.nulls_first())
        .limit(MAX_ENQUEUE_PER_TICK)
    ).unique().scalars().all()
    for artist in rows:
        enqueue_job(db, "artist_crawl", artist_id=artist.id, reason="schedule")
        # placeholder until the worker sets the real next run (prevents duplicates)
        artist.next_crawl_at = now + timedelta(minutes=interval)
    db.commit()
    return len(rows)


def relevant_scope(db: Session) -> dict[str, Any]:
    """What venue/festival sources are relevant for at least one active user."""
    active_users = select(User.id).where(User.is_active.is_(True))
    venue_ids = set(db.execute(select(UserVenue.venue_id).where(UserVenue.user_id.in_(active_users))).scalars())
    city_ids = set(db.execute(select(UserCity.city_id).where(UserCity.user_id.in_(active_users))).scalars())
    region_ids = set(db.execute(select(UserRegion.region_id).where(UserRegion.user_id.in_(active_users))).scalars())
    country_ids = set(db.execute(select(UserCountry.country_id).where(UserCountry.user_id.in_(active_users))).scalars())
    covered_regions: set[int] = set()
    for ids in region_coverage(db, region_ids).values():
        covered_regions |= ids
    festival_users = db.execute(
        select(UserArtist.user_id).join(User, User.id == UserArtist.user_id)
        .where(UserArtist.is_active.is_(True), User.is_active.is_(True), UserArtist.show_festivals.is_(True))
    ).scalars().all()
    always = db.execute(select(UserFilter.user_id).where(UserFilter.festival_mode == "always")).scalars().all()
    anywhere = db.execute(
        select(UserFilter.user_id).where(UserFilter.festival_scope == "anywhere", UserFilter.user_id.in_(set(festival_users) | set(always)))
    ).first() is not None
    return {
        "venues": venue_ids, "cities": city_ids, "regions": covered_regions, "countries": country_ids,
        "festivals_wanted": bool(festival_users or always), "festivals_anywhere": anywhere,
    }


def _location_relevant(scope: dict[str, Any], venue_id: int | None, city: City | None) -> bool:
    if venue_id is not None and venue_id in scope["venues"]:
        return True
    if city is None:
        return False
    return city.id in scope["cities"] or (city.region_id in scope["regions"]) or city.country_id in scope["countries"]


def source_is_relevant(db: Session, source: Source, scope: dict[str, Any]) -> bool:
    if not (source.config or {}).get("auto_relevance"):
        return True
    if source.scope == "venue" and source.venue_id:
        venue = db.get(Venue, source.venue_id)
        city = db.get(City, venue.city_id) if venue and venue.city_id else None
        return _location_relevant(scope, source.venue_id, city)
    if source.scope == "festival" and source.festival_id:
        if not scope["festivals_wanted"]:
            return False
        if scope["festivals_anywhere"]:
            return True
        festival = db.get(Festival, source.festival_id)
        city = db.get(City, festival.city_id) if festival and festival.city_id else None
        return _location_relevant(scope, festival.venue_id if festival else None, city)
    return True


def schedule_sources(db: Session, now: datetime) -> int:
    sources = db.execute(
        select(Source).where(
            Source.is_enabled.is_(True),
            Source.scope != "artist",
            or_(Source.next_attempt_at.is_(None), Source.next_attempt_at <= now),
            ~exists(select(CrawlerJob.id).where(
                CrawlerJob.source_id == Source.id, CrawlerJob.job_type == "source_crawl", CrawlerJob.status.in_(["queued", "running"])
            )),
        )
    ).scalars().all()
    if not sources:
        return 0
    has_artists = db.execute(monitored_artist_query().limit(1)).first() is not None
    if not has_artists:
        return 0
    scope = relevant_scope(db)
    count = 0
    for source in sources:
        interval = source.crawl_interval_minutes or DEFAULT_INTERVALS.get(source.scope, 60)
        if source.last_attempt_at and source.last_attempt_at > now - timedelta(minutes=interval):
            continue
        if not source_is_relevant(db, source, scope):
            continue
        enqueue_job(db, "source_crawl", source_id=source.id, reason="schedule")
        source.last_attempt_at = now  # placeholder, worker updates
        count += 1
        if count >= MAX_ENQUEUE_PER_TICK:
            break
    db.commit()
    return count


def schedule_enrichment(db: Session, now: datetime, days: int) -> int:
    rows = db.execute(
        monitored_artist_query()
        .where(or_(Artist.enriched_at.is_(None), Artist.enriched_at <= now - timedelta(days=days)))
        .where(~exists(select(CrawlerJob.id).where(
            CrawlerJob.artist_id == Artist.id, CrawlerJob.job_type == "artist_enrich", CrawlerJob.status.in_(["queued", "running"])
        )))
        .limit(50)
    ).unique().scalars().all()
    for artist in rows:
        enqueue_job(db, "artist_enrich", artist_id=artist.id, priority=-1, reason="schedule")
    db.commit()
    return len(rows)


def maybe_maintenance(db: Session, now: datetime) -> bool:
    local = now.astimezone(ZoneInfo(DEFAULT_TZ))
    if local.hour != MAINTENANCE_HOUR:
        return False
    row = db.get(AppSetting, "maintenance_last_run")
    today = local.date().isoformat()
    if row is not None and row.value.get("date") == today:
        return False
    enqueue_job(db, "maintenance", priority=-2, reason="schedule")
    if row is None:
        db.add(AppSetting(key="maintenance_last_run", value={"date": today}))
    else:
        row.value = {"date": today}
    db.commit()
    return True


def heartbeat(db: Session, info: dict[str, Any]) -> None:
    stmt = pg_insert(SystemHeartbeat).values(component="scheduler", kind="scheduler", started_at=utcnow(), last_seen_at=utcnow(), info=info)
    stmt = stmt.on_conflict_do_update(index_elements=["component"], set_={"last_seen_at": utcnow(), "info": stmt.excluded.info})
    db.execute(stmt)
    db.commit()


def tick(db: Session) -> dict[str, Any]:
    now = utcnow()
    settings = crawler_settings(db, fresh=True)
    out: dict[str, Any] = {"at": now.isoformat(), "enabled": bool(settings.get("enabled", True))}
    out["requeued"] = requeue_stale_jobs(db)
    if settings.get("enabled", True):
        out["artists"] = schedule_artists(db, now, int(settings.get("interval_minutes", 60)))
        out["sources"] = schedule_sources(db, now)
        out["enrich"] = schedule_enrichment(db, now, int(settings.get("enrich_interval_days", 14)))
    out["maintenance"] = maybe_maintenance(db, now)
    heartbeat(db, {k: v for k, v in out.items() if k != "at"})
    return out


def main(argv: list[str] | None = None) -> int:
    setup_logging("scheduler")
    stop = threading.Event()

    def _shutdown(signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    tick_seconds = max(5, get_settings().scheduler_tick_seconds)
    sf = get_session_factory()
    log.info("Scheduler startet (Takt %ss)", tick_seconds, extra={"event": "scheduler.start"})
    while not stop.is_set():
        try:
            with sf() as db:
                result = tick(db)
            if any(result.get(k) for k in ("artists", "sources", "enrich", "requeued")) or result.get("maintenance"):
                log.info(
                    "geplant: %s Künstler, %s Quellen, %s Anreicherungen",
                    result.get("artists", 0), result.get("sources", 0), result.get("enrich", 0),
                    extra={"event": "scheduler.tick", **{k: v for k, v in result.items() if k != "at"}},
                )
        except Exception:
            log.exception("scheduler tick failed", extra={"event": "scheduler.error"})
        stop.wait(tick_seconds)
    log.info("Scheduler beendet", extra={"event": "scheduler.stop"})
    return 0


__all__ = ["main", "tick", "relevant_scope", "source_is_relevant"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
