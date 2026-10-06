"""/api/admin/crawler and /api/admin/sources – crawler monitoring and control."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from tourdesk.api.admin.system import artist_names, error_out, heartbeats, run_out
from tourdesk.core.constants import PROVIDERS
from tourdesk.core.db import get_db
from tourdesk.core.text import escape_like
from tourdesk.core.timeutil import utcnow
from tourdesk.models import Artist, CrawlerDomain, CrawlerError, CrawlerJob, CrawlerRun, Festival, Source, UserArtist, Venue
from tourdesk.schemas.artists import SourceOut
from tourdesk.schemas.common import ApiModel, HttpUrl, OkResponse
from tourdesk.security.deps import AuthContext, require_admin
from tourdesk.security.netsafety import UnsafeURLError, assert_public_url
from tourdesk.services import audit
from tourdesk.services.app_settings import public_crawler_settings, update_crawler_settings
from tourdesk.services.artists import source_out
from tourdesk.services.jobs import PRIORITY_CHECK, PRIORITY_MANUAL, enqueue_job

router = APIRouter()


def job_out(j: CrawlerJob, names: dict[int, str]) -> dict:
    return {
        "id": j.id,
        "job_type": j.job_type,
        "artist_id": j.artist_id,
        "artist_name": names.get(j.artist_id) if j.artist_id else None,
        "source_id": j.source_id,
        "status": j.status,
        "priority": j.priority,
        "reason": j.reason,
        "attempts": j.attempts,
        "max_attempts": j.max_attempts,
        "run_after": j.run_after,
        "created_at": j.created_at,
        "started_at": j.started_at,
        "finished_at": j.finished_at,
        "heartbeat_at": j.heartbeat_at,
        "worker_id": j.worker_id,
        "error": j.error,
        "result": j.result,
    }


@router.get("/crawler/status")
def status(ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    queue = db.execute(
        select(CrawlerJob.status, CrawlerJob.job_type, func.count(CrawlerJob.id))
        .where(CrawlerJob.status.in_(["queued", "running"]))
        .group_by(CrawlerJob.status, CrawlerJob.job_type)
    ).all()
    running = db.execute(select(CrawlerJob).where(CrawlerJob.status == "running").order_by(CrawlerJob.started_at)).scalars().all()
    names = artist_names(db, {j.artist_id for j in running})
    day_ago = utcnow() - timedelta(hours=24)
    run_stats = dict(
        db.execute(select(CrawlerRun.status, func.count(CrawlerRun.id)).where(CrawlerRun.started_at >= day_ago).group_by(CrawlerRun.status)).all()
    )
    monitored = select(UserArtist.artist_id).where(UserArtist.is_active.is_(True)).distinct()
    next_due = db.execute(select(func.min(Artist.next_crawl_at)).where(Artist.id.in_(monitored))).scalar()
    return {
        "queue": [{"status": s, "job_type": t, "count": c} for s, t, c in queue],
        "running": [job_out(j, names) for j in running],
        "runs_24h": run_stats,
        "heartbeats": heartbeats(db),
        "next_due": next_due,
        "settings": public_crawler_settings(db),
    }


@router.get("/crawler/runs")
def runs(
    status: str | None = Query(None, pattern="^(running|success|partial|failed)$"),
    artist_id: int | None = None,
    source_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(CrawlerRun)
    if status:
        stmt = stmt.where(CrawlerRun.status == status)
    if artist_id:
        stmt = stmt.where(CrawlerRun.artist_id == artist_id)
    if source_id:
        stmt = stmt.where(CrawlerRun.source_id == source_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(CrawlerRun.started_at.desc()).offset(offset).limit(limit)).scalars().all()
    names = artist_names(db, {r.artist_id for r in rows})
    return {"total": total, "items": [run_out(r, names) for r in rows]}


@router.get("/crawler/runs/{run_id}")
def run_detail(run_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    run = db.get(CrawlerRun, run_id)
    if run is None:
        raise HTTPException(404, "Lauf nicht gefunden")
    errors = db.execute(select(CrawlerError).where(CrawlerError.run_id == run_id).order_by(CrawlerError.occurred_at)).scalars().all()
    names = artist_names(db, {run.artist_id})
    data = run_out(run, names, with_log=True)
    data["errors"] = [error_out(e, names) for e in errors]
    return data


@router.get("/crawler/errors")
def errors(
    since_hours: int = Query(168, ge=1, le=24 * 90),
    source_id: int | None = None,
    artist_id: int | None = None,
    error_type: str | None = Query(None, max_length=32),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(CrawlerError).where(CrawlerError.occurred_at >= utcnow() - timedelta(hours=since_hours))
    if source_id:
        stmt = stmt.where(CrawlerError.source_id == source_id)
    if artist_id:
        stmt = stmt.where(CrawlerError.artist_id == artist_id)
    if error_type:
        stmt = stmt.where(CrawlerError.error_type == error_type)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(CrawlerError.occurred_at.desc()).offset(offset).limit(limit)).scalars().all()
    names = artist_names(db, {e.artist_id for e in rows})
    by_type = dict(
        db.execute(
            select(CrawlerError.error_type, func.count(CrawlerError.id))
            .where(CrawlerError.occurred_at >= utcnow() - timedelta(hours=since_hours))
            .group_by(CrawlerError.error_type)
        ).all()
    )
    return {"total": total, "by_type": by_type, "items": [error_out(e, names) for e in rows]}


@router.get("/crawler/jobs")
def jobs(
    status: str | None = Query(None, pattern="^(queued|running|succeeded|partial|failed|cancelled)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(CrawlerJob)
    if status:
        stmt = stmt.where(CrawlerJob.status == status)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(CrawlerJob.created_at.desc(), CrawlerJob.id.desc()).offset(offset).limit(limit)).scalars().all()
    names = artist_names(db, {j.artist_id for j in rows})
    return {"total": total, "items": [job_out(j, names) for j in rows]}


@router.get("/crawler/jobs/{job_id}")
def job_detail(job_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    job = db.get(CrawlerJob, job_id)
    if job is None:
        raise HTTPException(404, "Job nicht gefunden")
    return job_out(job, artist_names(db, {job.artist_id}))


class JobRequest(ApiModel):
    job_type: str = Field(pattern="^(artist_crawl|source_crawl|artist_enrich|maintenance|all_artists|all_sources)$")
    artist_id: int | None = None
    source_id: int | None = None


@router.post("/crawler/jobs")
def create_job(payload: JobRequest, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    created = 0
    if payload.job_type == "all_artists":
        monitored = db.execute(select(UserArtist.artist_id).where(UserArtist.is_active.is_(True)).distinct()).scalars().all()
        for artist_id in monitored:
            enqueue_job(db, "artist_crawl", artist_id=artist_id, priority=PRIORITY_MANUAL - 2, reason="manual", requested_by=ctx.actor.id)
            created += 1
    elif payload.job_type == "all_sources":
        ids = db.execute(select(Source.id).where(Source.is_enabled.is_(True), Source.scope != "artist")).scalars().all()
        for sid in ids:
            enqueue_job(db, "source_crawl", source_id=sid, priority=PRIORITY_MANUAL - 2, reason="manual", requested_by=ctx.actor.id,
                        payload={"force": True})
            created += 1
    else:
        if payload.job_type in ("artist_crawl", "artist_enrich") and not payload.artist_id:
            raise HTTPException(422, "artist_id fehlt")
        if payload.job_type == "source_crawl" and not payload.source_id:
            raise HTTPException(422, "source_id fehlt")
        enqueue_job(db, payload.job_type, artist_id=payload.artist_id, source_id=payload.source_id, priority=PRIORITY_MANUAL,
                    reason="manual", requested_by=ctx.actor.id, payload={"force": True})
        created = 1
    audit.record(db, "admin.crawler_job", actor=ctx.actor, request=request, target_type="job", details=payload.model_dump() | {"created": created})
    db.commit()
    return {"ok": True, "created": created}


@router.delete("/crawler/jobs/{job_id}", response_model=OkResponse)
def cancel_job(job_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> OkResponse:
    job = db.get(CrawlerJob, job_id)
    if job is None:
        raise HTTPException(404, "Job nicht gefunden")
    if job.status != "queued":
        raise HTTPException(422, "Nur wartende Jobs können abgebrochen werden")
    job.status = "cancelled"
    job.finished_at = utcnow()
    db.commit()
    return OkResponse()


@router.get("/crawler/settings")
def get_settings_(ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return public_crawler_settings(db)


@router.put("/crawler/settings")
def put_settings(request: Request, patch: dict[str, Any] = Body(...), ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        update_crawler_settings(db, patch, ctx.actor.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    safe = {k: ("***" if k == "api_keys" else v) for k, v in patch.items()}
    audit.record(db, "admin.crawler_settings", actor=ctx.actor, request=request, target_type="settings", details=safe)
    db.commit()
    return public_crawler_settings(db)


@router.get("/crawler/domains")
def domains(ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(CrawlerDomain).order_by(CrawlerDomain.last_request_at.desc().nulls_last()).limit(300)).scalars().all()
    return [
        {"domain": d.domain, "last_request_at": d.last_request_at, "request_count": d.request_count, "error_count": d.error_count,
         "last_error": d.last_error, "crawl_delay_s": d.crawl_delay_s, "robots_status": d.robots_status,
         "robots_fetched_at": d.robots_fetched_at, "blocked_until": d.blocked_until}
        for d in rows
    ]


# ----------------------------------------------------------------------------------- sources
def _source_rows_out(db: Session, rows: list[Source]) -> list[SourceOut]:
    a_names = artist_names(db, {s.artist_id for s in rows})
    v_ids = {s.venue_id for s in rows if s.venue_id}
    f_ids = {s.festival_id for s in rows if s.festival_id}
    v_names = dict(db.execute(select(Venue.id, Venue.name).where(Venue.id.in_(v_ids))).all()) if v_ids else {}
    f_names = dict(db.execute(select(Festival.id, Festival.name).where(Festival.id.in_(f_ids))).all()) if f_ids else {}
    return [
        source_out(s, can_delete=True, artist_name=a_names.get(s.artist_id), venue_name=v_names.get(s.venue_id),
                   festival_name=f_names.get(s.festival_id))
        for s in rows
    ]


@router.get("/sources")
def list_sources(
    scope: str | None = Query(None, pattern="^(artist|venue|festival|global)$"),
    status: str | None = Query(None, pattern="^(new|ok|warning|error|disabled)$"),
    provider: str | None = Query(None, max_length=50),
    q: str = Query("", max_length=100),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Source)
    if scope:
        stmt = stmt.where(Source.scope == scope)
    if status == "disabled":
        stmt = stmt.where(Source.is_enabled.is_(False))
    elif status:
        stmt = stmt.where(Source.status == status, Source.is_enabled.is_(True))
    if provider:
        stmt = stmt.where(Source.provider == provider)
    if q.strip():
        like = "%" + escape_like(q.strip().lower()) + "%"
        stmt = stmt.where(or_(func.lower(Source.name).like(like, escape="\\"), func.lower(Source.url).like(like, escape="\\")))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    # problems first: error → warning → new → ok → disabled
    severity = case(
        (Source.is_enabled.is_(False), 4),
        (Source.status == "error", 0),
        (Source.status == "warning", 1),
        (Source.status == "new", 2),
        else_=3,
    )
    rows = list(
        db.execute(
            stmt.order_by(severity, Source.consecutive_failures.desc(), Source.last_attempt_at.desc().nulls_last(), Source.id)
            .offset(offset)
            .limit(limit)
        ).scalars()
    )
    return {"total": total, "items": [s.model_dump(mode="json") for s in _source_rows_out(db, rows)],
            "providers": {k: v["label"] for k, v in PROVIDERS.items()}}


class SourceAdminCreate(ApiModel):
    scope: str = Field(pattern="^(artist|venue|festival|global)$")
    provider: str = Field(max_length=50)
    url: HttpUrl = None
    name: str = Field(min_length=1, max_length=200)
    artist_id: int | None = None
    venue_id: int | None = None
    festival_id: int | None = None
    trust_level: int = Field(default=6, ge=1, le=6)
    config: dict[str, Any] = Field(default_factory=dict)
    crawl_interval_minutes: int | None = Field(default=None, ge=10, le=10080)


class SourceAdminUpdate(ApiModel):
    url: HttpUrl = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    trust_level: int | None = Field(default=None, ge=1, le=6)
    is_enabled: bool | None = None
    config: dict[str, Any] | None = None
    crawl_interval_minutes: int | None = Field(default=None, ge=10, le=10080)


@router.post("/sources")
def create_source(payload: SourceAdminCreate, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    if payload.provider not in PROVIDERS:
        raise HTTPException(422, "Unbekannter Provider")
    if payload.url:
        try:
            assert_public_url(payload.url, resolve=False)
        except UnsafeURLError as exc:
            raise HTTPException(422, str(exc)) from exc
    fk = {"artist": payload.artist_id, "venue": payload.venue_id, "festival": payload.festival_id}
    if payload.scope != "global" and not fk[payload.scope]:
        raise HTTPException(422, f"Für den Bereich '{payload.scope}' fehlt die Zuordnung")
    source = Source(
        scope=payload.scope, provider=payload.provider, url=payload.url, name=payload.name,
        artist_id=payload.artist_id if payload.scope == "artist" else None,
        venue_id=payload.venue_id if payload.scope == "venue" else None,
        festival_id=payload.festival_id if payload.scope == "festival" else None,
        trust_level=payload.trust_level, is_enabled=True, is_auto=False, config=payload.config,
        crawl_interval_minutes=payload.crawl_interval_minutes, created_by_user_id=ctx.actor.id,
    )
    db.add(source)
    db.flush()
    audit.record(db, "admin.source_create", actor=ctx.actor, request=request, target_type="source", target_id=source.id, target_label=source.name)
    db.commit()
    return _source_rows_out(db, [source])[0].model_dump(mode="json")


@router.patch("/sources/{source_id}")
def update_source(source_id: int, payload: SourceAdminUpdate, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Quelle nicht gefunden")
    data = payload.model_dump(exclude_unset=True)
    if data.get("url"):
        try:
            assert_public_url(data["url"], resolve=False)
        except UnsafeURLError as exc:
            raise HTTPException(422, str(exc)) from exc
    for key, value in data.items():
        if key == "config" and value is not None:
            source.config = {**(source.config or {}), **value}
        elif value is not None or key == "crawl_interval_minutes":
            setattr(source, key, value)
    if data.get("is_enabled") is False:
        source.status = "disabled"
    elif data.get("is_enabled") is True and source.status == "disabled":
        source.status = "new"
    audit.record(db, "admin.source_update", actor=ctx.actor, request=request, target_type="source", target_id=source.id,
                 target_label=source.name, details={k: str(v) for k, v in data.items()})
    db.commit()
    return _source_rows_out(db, [source])[0].model_dump(mode="json")


@router.delete("/sources/{source_id}", response_model=OkResponse)
def delete_source(source_id: int, request: Request, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> OkResponse:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Quelle nicht gefunden")
    audit.record(db, "admin.source_delete", actor=ctx.actor, request=request, target_type="source", target_id=source.id, target_label=source.name)
    db.delete(source)
    db.commit()
    return OkResponse()


@router.post("/sources/{source_id}/reset", response_model=OkResponse)
def reset_source(source_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> OkResponse:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Quelle nicht gefunden")
    source.consecutive_failures = 0
    source.next_attempt_at = None
    if source.status == "error":
        source.status = "new"
    db.commit()
    return OkResponse()


@router.post("/sources/{source_id}/check")
def check_source(source_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Dry run: fetch & extract without saving events. Poll ``/crawler/jobs/{id}`` for the result."""
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Quelle nicht gefunden")
    job = enqueue_job(db, "source_check", source_id=source_id, artist_id=source.artist_id, priority=PRIORITY_CHECK,
                      reason="manual", requested_by=ctx.actor.id, max_attempts=1)
    db.commit()
    return {"job_id": job.id}


@router.post("/sources/{source_id}/run", response_model=OkResponse)
def run_source(source_id: int, ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)) -> OkResponse:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(404, "Quelle nicht gefunden")
    if source.scope == "artist" and source.artist_id:
        enqueue_job(db, "artist_crawl", artist_id=source.artist_id, priority=PRIORITY_MANUAL, reason="manual",
                    requested_by=ctx.actor.id, payload={"force": True})
    else:
        enqueue_job(db, "source_crawl", source_id=source.id, priority=PRIORITY_MANUAL, reason="manual",
                    requested_by=ctx.actor.id, payload={"force": True})
    db.commit()
    return OkResponse(detail="Crawl eingeplant")
