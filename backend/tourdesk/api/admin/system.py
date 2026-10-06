"""/api/admin – overview, system status, logs, audit log, events, catalogue, geo review."""

from __future__ import annotations

import platform
import shutil
import sys
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from tourdesk import __version__
from tourdesk.api.auth import _me
from tourdesk.core.config import get_settings
from tourdesk.core.db import check_database, get_db
from tourdesk.core.logging import LOG_FILES, tail_log
from tourdesk.core.text import escape_like, normalize_name
from tourdesk.core.timeutil import utcnow
from tourdesk.models import (
    Artist,
    AuditLog,
    City,
    CrawlerError,
    CrawlerJob,
    CrawlerRun,
    Event,
    Source,
    SystemHeartbeat,
    User,
    UserArtist,
    Venue,
)
from tourdesk.schemas.common import OkResponse
from tourdesk.schemas.users import MeResponse
from tourdesk.security.deps import AuthContext, require_admin
from tourdesk.services import audit
from tourdesk.services.artists import artist_out, subscriber_count
from tourdesk.services.events import event_detail_out, event_out
from tourdesk.services.filter_engine import evaluate
from tourdesk.services.filters import artist_prefs, event_facts, load_profile
from tourdesk.services.geo import city_out, venue_out
from tourdesk.services.jobs import PRIORITY_MANUAL, enqueue_job
from tourdesk.services.media import delete_artist_images

router = APIRouter()

HEARTBEAT_STALE = timedelta(minutes=3)


def heartbeats(db: Session) -> list[dict]:
    now = utcnow()
    rows = db.execute(select(SystemHeartbeat).order_by(SystemHeartbeat.kind, SystemHeartbeat.component)).scalars().all()
    return [
        {
            "component": h.component,
            "kind": h.kind,
            "started_at": h.started_at,
            "last_seen_at": h.last_seen_at,
            "alive": now - h.last_seen_at < HEARTBEAT_STALE,
            "info": h.info,
        }
        for h in rows
        if now - h.last_seen_at < timedelta(days=1)
    ]


def run_out(r: CrawlerRun, names: dict[int, str] | None = None, *, with_log: bool = False) -> dict:
    data = {
        "id": r.id,
        "job_id": r.job_id,
        "job_type": r.job_type,
        "trigger": r.trigger,
        "artist_id": r.artist_id,
        "artist_name": (names or {}).get(r.artist_id) if r.artist_id else None,
        "source_id": r.source_id,
        "label": r.label,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "duration_ms": r.duration_ms,
        "status": r.status,
        "sources_total": r.sources_total,
        "sources_ok": r.sources_ok,
        "sources_failed": r.sources_failed,
        "events_found": r.events_found,
        "events_new": r.events_new,
        "events_updated": r.events_updated,
        "events_removed": r.events_removed,
        "errors_count": r.errors_count,
    }
    if with_log:
        data["log"] = r.log
        data["summary"] = r.summary
    return data


def error_out(e: CrawlerError, names: dict[int, str] | None = None) -> dict:
    return {
        "id": e.id,
        "run_id": e.run_id,
        "source_id": e.source_id,
        "artist_id": e.artist_id,
        "artist_name": (names or {}).get(e.artist_id) if e.artist_id else None,
        "occurred_at": e.occurred_at,
        "domain": e.domain,
        "url": e.url,
        "error_type": e.error_type,
        "status_code": e.status_code,
        "message": e.message,
        "retry_at": e.retry_at,
    }


def artist_names(db: Session, ids: set[int]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(Artist.id, Artist.name).where(Artist.id.in_(ids))).all())


@router.get("/overview")
def overview(ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    now = utcnow()
    today = now.date()
    day_ago = now - timedelta(hours=24)
    followed_artist_ids = select(UserArtist.artist_id).where(UserArtist.is_active.is_(True)).distinct()
    status_counts = dict(
        db.execute(
            select(Artist.crawl_status, func.count(Artist.id)).where(Artist.id.in_(followed_artist_ids)).group_by(Artist.crawl_status)
        ).all()
    )
    runs = db.execute(select(CrawlerRun).order_by(CrawlerRun.started_at.desc()).limit(12)).scalars().all()
    errors = db.execute(select(CrawlerError).order_by(CrawlerError.occurred_at.desc()).limit(10)).scalars().all()
    names = artist_names(db, {r.artist_id for r in runs} | {e.artist_id for e in errors})
    problem_sources = db.execute(
        select(Source).where(Source.status == "error").order_by(Source.consecutive_failures.desc(), Source.last_error_at.desc()).limit(10)
    ).scalars().all()
    new_events = db.execute(
        select(Event).where(Event.first_seen_at >= now - timedelta(days=7)).order_by(Event.first_seen_at.desc()).limit(10)
    ).unique().scalars().all()
    recent_users = db.execute(select(User).order_by(User.created_at.desc()).limit(5)).unique().scalars().all()
    queue = dict(db.execute(select(CrawlerJob.status, func.count(CrawlerJob.id)).where(CrawlerJob.status.in_(["queued", "running"])).group_by(CrawlerJob.status)).all())
    return {
        "counts": {
            "users": db.execute(select(func.count(User.id))).scalar_one(),
            "active_users": db.execute(select(func.count(User.id)).where(User.is_active.is_(True))).scalar_one(),
            "artists": db.execute(select(func.count(Artist.id))).scalar_one(),
            "monitored_artists": db.execute(select(func.count()).select_from(followed_artist_ids.subquery())).scalar_one(),
            "events": db.execute(select(func.count(Event.id))).scalar_one(),
            "upcoming_events": db.execute(select(func.count(Event.id)).where(Event.event_date >= today, Event.is_listed.is_(True))).scalar_one(),
            "sources": db.execute(select(func.count(Source.id)).where(Source.is_enabled.is_(True))).scalar_one(),
            "crawler_jobs_queued": queue.get("queued", 0),
            "crawler_jobs_running": queue.get("running", 0),
            "errors_24h": db.execute(select(func.count(CrawlerError.id)).where(CrawlerError.occurred_at >= day_ago)).scalar_one(),
            "runs_24h": db.execute(select(func.count(CrawlerRun.id)).where(CrawlerRun.started_at >= day_ago)).scalar_one(),
            "new_events_24h": db.execute(select(func.count(Event.id)).where(Event.first_seen_at >= day_ago)).scalar_one(),
        },
        "crawler_status": {
            "ok": status_counts.get("ok", 0),
            "partial": status_counts.get("partial", 0),
            "error": status_counts.get("error", 0),
            "pending": status_counts.get("pending", 0),
        },
        "recent_runs": [run_out(r, names) for r in runs],
        "recent_errors": [error_out(e, names) for e in errors],
        "problem_sources": [
            {"id": s.id, "name": s.name, "url": s.url, "provider": s.provider, "consecutive_failures": s.consecutive_failures,
             "last_error": s.last_error, "last_error_at": s.last_error_at, "last_success_at": s.last_success_at,
             "next_attempt_at": s.next_attempt_at}
            for s in problem_sources
        ],
        "new_events": [event_out(e).model_dump(mode="json") for e in new_events],
        "recent_users": [
            {"id": u.id, "username": u.username, "email": u.email, "role": u.role_key, "created_at": u.created_at, "is_active": u.is_active}
            for u in recent_users
        ],
        "heartbeats": heartbeats(db),
    }


def _dir_size(path) -> int:
    total = 0
    if path.exists():
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    return total


@router.get("/system")
def system(ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    try:
        database = check_database()
    except Exception as exc:  # pragma: no cover
        database = {"ok": False, "error": str(exc)}
    usage = shutil.disk_usage(settings.data_dir if settings.data_dir.exists() else settings.home)
    counts = {
        name: db.execute(select(func.count()).select_from(model)).scalar_one()
        for name, model in (("users", User), ("artists", Artist), ("events", Event), ("sources", Source), ("venues", Venue), ("cities", City))
    }
    logs = []
    for name in LOG_FILES:
        path = settings.log_dir / f"{name}.log"
        logs.append({"name": name, "exists": path.is_file(), "size": path.stat().st_size if path.is_file() else 0})
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "env": settings.env,
        "public_url": settings.public_url,
        "trusted_proxies": settings.trusted_proxies,
        "cookie_secure": settings.cookie_secure,
        "frontend": str(settings.resolved_frontend_dist) if settings.resolved_frontend_dist else None,
        "database": database,
        "disk": {"total": usage.total, "used": usage.used, "free": usage.free, "media_bytes": _dir_size(settings.media_dir)},
        "counts": counts,
        "heartbeats": heartbeats(db),
        "logs": logs,
    }


@router.get("/logs")
def logs(
    file: str = Query("api"),
    level: str | None = Query(None, pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"),
    q: str | None = Query(None, max_length=100),
    lines: int = Query(200, ge=10, le=2000),
    ctx: AuthContext = Depends(require_admin),
) -> dict:
    if file not in LOG_FILES:
        raise HTTPException(404, "Unbekannte Logdatei")
    return {"file": file, "entries": tail_log(file, lines=lines, level=level, contains=q)}


@router.get("/audit")
def audit_log(
    action: str | None = Query(None, max_length=64),
    q: str | None = Query(None, max_length=100),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.like(escape_like(action) + "%", escape="\\"))
    if q:
        like = "%" + escape_like(q.casefold()) + "%"
        stmt = stmt.where(or_(func.lower(AuditLog.actor_username).like(like, escape="\\"), func.lower(AuditLog.target_label).like(like, escape="\\")))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit)).scalars().all()
    return {
        "total": total,
        "items": [
            {"id": a.id, "created_at": a.created_at, "action": a.action, "actor": a.actor_username, "target_type": a.target_type,
             "target_id": a.target_id, "target": a.target_label, "success": a.success, "details": a.details, "ip": a.ip}
            for a in rows
        ],
    }


@router.post("/impersonation/stop", response_model=MeResponse)
def stop_impersonation(request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> MeResponse:
    target = ctx.user
    if ctx.impersonating:
        audit.record(db, "admin.impersonation_stop", actor=ctx.actor, request=request, target_type="user",
                     target_id=target.id, target_label=target.username)
    ctx.session.impersonated_user_id = None
    ctx.session.impersonation_started_at = None
    db.commit()
    return _me(db, AuthContext(session=ctx.session, actor=ctx.actor, user=ctx.actor))


# ----------------------------------------------------------------------------------- events
@router.get("/events")
def all_events(
    q: str = Query("", max_length=100),
    artist_id: int | None = None,
    upcoming: bool = True,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Event).join(Artist, Artist.id == Event.artist_id)
    if artist_id:
        stmt = stmt.where(Event.artist_id == artist_id)
    if upcoming:
        stmt = stmt.where(Event.event_date >= utcnow().date())
    if q.strip():
        like = "%" + escape_like(normalize_name(q)) + "%"
        stmt = stmt.outerjoin(Venue, Venue.id == Event.venue_id).outerjoin(City, City.id == Event.city_id).where(
            or_(Artist.name_norm.like(like, escape="\\"), Venue.name_norm.like(like, escape="\\"), City.name_norm.like(like, escape="\\"))
        )
    total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Event.event_date, Event.id).offset(offset).limit(limit)).unique().scalars().all()
    return {"total": total, "items": [event_out(e).model_dump(mode="json") for e in rows]}


@router.get("/events/{event_id}")
def admin_event(event_id: int, user_id: int | None = None, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(404, "Event nicht gefunden")
    decision = None
    if user_id:
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(404, "Benutzer nicht gefunden")
        profile, _f = load_profile(db, user)
        decision = evaluate(event_facts(event), artist_prefs(db, user.id).get(event.artist_id), profile)
    out = event_detail_out(event, decision).model_dump(mode="json")
    out["observations"] = [
        {"source_id": o.source_id, "provider": o.provider, "url": o.url, "trust_level": o.trust_level, "is_active": o.is_active,
         "raw_title": o.raw_title, "raw_venue": o.raw_venue, "raw_city": o.raw_city, "raw_date": o.raw_date, "data": o.data,
         "first_seen_at": o.first_seen_at, "last_seen_at": o.last_seen_at}
        for o in event.observations
    ]
    return out


@router.get("/events/{event_id}/explain")
def explain_for_user(event_id: int, user_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    event = db.get(Event, event_id)
    user = db.get(User, user_id)
    if event is None or user is None:
        raise HTTPException(404, "Nicht gefunden")
    profile, _f = load_profile(db, user)
    return evaluate(event_facts(event), artist_prefs(db, user.id).get(event.artist_id), profile).as_dict()


# ----------------------------------------------------------------------------------- catalogue
@router.get("/artists")
def catalog_artists(
    q: str = Query("", max_length=100),
    status: str | None = Query(None, pattern="^(pending|ok|partial|error|disabled)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Artist)
    if q.strip():
        stmt = stmt.where(Artist.name_norm.like("%" + escape_like(normalize_name(q)) + "%", escape="\\"))
    if status:
        stmt = stmt.where(Artist.crawl_status == status)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Artist.name).offset(offset).limit(limit)).unique().scalars().all()
    subs = dict(db.execute(select(UserArtist.artist_id, func.count(UserArtist.id)).group_by(UserArtist.artist_id)).all())
    today = utcnow().date()
    upcoming = dict(
        db.execute(
            select(Event.artist_id, func.count(Event.id)).where(Event.event_date >= today, Event.is_listed.is_(True)).group_by(Event.artist_id)
        ).all()
    )
    items = []
    for a in rows:
        data = artist_out(a).model_dump(mode="json")
        data["subscribers"] = subs.get(a.id, 0)
        data["upcoming_events"] = upcoming.get(a.id, 0)
        items.append(data)
    return {"total": total, "items": items}


@router.post("/artists/{artist_id}/crawl", response_model=OkResponse)
def crawl_artist(artist_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> OkResponse:
    if db.get(Artist, artist_id) is None:
        raise HTTPException(404, "Künstler nicht gefunden")
    enqueue_job(db, "artist_crawl", artist_id=artist_id, priority=PRIORITY_MANUAL, reason="manual", requested_by=ctx.actor.id)
    db.commit()
    return OkResponse(detail="Crawl eingeplant")


@router.post("/artists/{artist_id}/enrich", response_model=OkResponse)
def enrich_artist(artist_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> OkResponse:
    if db.get(Artist, artist_id) is None:
        raise HTTPException(404, "Künstler nicht gefunden")
    enqueue_job(db, "artist_enrich", artist_id=artist_id, priority=PRIORITY_MANUAL, reason="manual", requested_by=ctx.actor.id,
                payload={"force_image": True})
    db.commit()
    return OkResponse(detail="Metadaten-/Bildsuche eingeplant")


@router.delete("/artists/{artist_id}", response_model=OkResponse)
def delete_catalog_artist(artist_id: int, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> OkResponse:
    artist = db.get(Artist, artist_id)
    if artist is None:
        raise HTTPException(404, "Künstler nicht gefunden")
    subs = subscriber_count(db, artist_id)
    name = artist.name
    audit.record(db, "admin.artist_delete", actor=ctx.actor, request=request, target_type="artist", target_id=artist_id,
                 target_label=name, details={"subscribers": subs})
    db.delete(artist)
    db.commit()
    delete_artist_images(artist_id)
    return OkResponse(detail=f"{name} wurde aus dem Katalog gelöscht ({subs} Abos entfernt).")


# ----------------------------------------------------------------------------------- geo review
@router.get("/geo/review")
def geo_review(ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    cities = db.execute(select(City).where(City.needs_review.is_(True)).order_by(City.created_at.desc()).limit(200)).unique().scalars().all()
    venues = db.execute(select(Venue).where(Venue.needs_review.is_(True)).order_by(Venue.created_at.desc()).limit(200)).unique().scalars().all()
    return {
        "cities": [city_out(c).model_dump(mode="json") for c in cities],
        "venues": [venue_out(v).model_dump(mode="json") for v in venues],
    }

