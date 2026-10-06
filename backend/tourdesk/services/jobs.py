"""Crawler job queue helpers (PostgreSQL based, used by API, scheduler and worker)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tourdesk.core.timeutil import utcnow
from tourdesk.models import CrawlerJob

PRIORITY_SCHEDULE = 0
PRIORITY_NEW = 5
PRIORITY_MANUAL = 8
PRIORITY_CHECK = 9


def dedupe_key(job_type: str, artist_id: int | None = None, source_id: int | None = None) -> str:
    return f"{job_type}:a{artist_id or 0}:s{source_id or 0}"


def enqueue_job(
    db: Session,
    job_type: str,
    *,
    artist_id: int | None = None,
    source_id: int | None = None,
    payload: dict[str, Any] | None = None,
    priority: int = PRIORITY_SCHEDULE,
    reason: str = "schedule",
    requested_by: int | None = None,
    run_after: datetime | None = None,
    max_attempts: int = 3,
    dedupe: bool = True,
) -> CrawlerJob:
    """Insert a job unless an identical one is already queued/running.

    Returns the new or the already existing job (whose priority is raised if needed).
    """
    key = dedupe_key(job_type, artist_id, source_id) if dedupe else None
    values = {
        "job_type": job_type,
        "artist_id": artist_id,
        "source_id": source_id,
        "payload": payload or {},
        "status": "queued",
        "priority": priority,
        "run_after": run_after or utcnow(),
        "attempts": 0,
        "max_attempts": max_attempts,
        "dedupe_key": key,
        "reason": reason,
        "requested_by_user_id": requested_by,
    }
    stmt = pg_insert(CrawlerJob).values(**values)
    if key is not None:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["dedupe_key"], index_where=text("status IN ('queued', 'running')")
        )
    job_id = db.execute(stmt.returning(CrawlerJob.id)).scalar()
    if job_id is not None:
        db.flush()
        return db.get(CrawlerJob, job_id)  # type: ignore[return-value]
    existing = db.execute(
        select(CrawlerJob).where(CrawlerJob.dedupe_key == key, CrawlerJob.status.in_(["queued", "running"]))
    ).scalars().first()
    if existing is None:  # race: finished meanwhile -> try once more without conflict
        return enqueue_job(db, job_type, artist_id=artist_id, source_id=source_id, payload=payload, priority=priority,
                           reason=reason, requested_by=requested_by, run_after=run_after, max_attempts=max_attempts,
                           dedupe=False)
    if existing.status == "queued" and priority > existing.priority:
        existing.priority = priority
        existing.reason = reason
        existing.run_after = min(existing.run_after, run_after or utcnow())
        if payload:
            existing.payload = {**(existing.payload or {}), **payload}
    return existing


def claim_next_job(db: Session, worker_id: str, job_types: list[str] | None = None) -> CrawlerJob | None:
    """Atomically claim the next runnable job (``FOR UPDATE SKIP LOCKED``)."""
    type_filter = "AND job_type = ANY(:types)" if job_types else ""
    row = db.execute(
        text(
            f"""
            UPDATE crawler_jobs SET status = 'running', started_at = now(), heartbeat_at = now(),
                   attempts = attempts + 1, worker_id = :worker
            WHERE id = (
                SELECT id FROM crawler_jobs
                WHERE status = 'queued' AND run_after <= now() {type_filter}
                ORDER BY priority DESC, run_after, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id
            """
        ),
        {"worker": worker_id, "types": job_types} if job_types else {"worker": worker_id},
    ).first()
    db.commit()
    if row is None:
        return None
    return db.get(CrawlerJob, row[0])


def heartbeat(db: Session, job_id: int) -> None:
    db.execute(update(CrawlerJob).where(CrawlerJob.id == job_id).values(heartbeat_at=func.now()))
    db.commit()


def finish_job(db: Session, job: CrawlerJob, status: str, *, result: dict | None = None, error: str | None = None) -> None:
    job.status = status
    job.finished_at = utcnow()
    job.result = result
    job.error = error
    db.commit()


def retry_job(db: Session, job: CrawlerJob, error: str) -> bool:
    """Requeue a failed job with exponential backoff. Returns False if exhausted."""
    if job.attempts >= job.max_attempts:
        finish_job(db, job, "failed", error=error)
        return False
    delay = timedelta(minutes=2 ** job.attempts)
    job.status = "queued"
    job.run_after = utcnow() + delay
    job.error = error
    job.worker_id = None
    db.commit()
    return True


def requeue_stale_jobs(db: Session, stale_after: timedelta = timedelta(minutes=15)) -> int:
    """Jobs whose worker died (no heartbeat) are requeued or failed."""
    cutoff = utcnow() - stale_after
    stale = db.execute(
        select(CrawlerJob).where(CrawlerJob.status == "running", CrawlerJob.heartbeat_at < cutoff)
    ).scalars().all()
    for job in stale:
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.finished_at = utcnow()
            job.error = "Worker antwortet nicht mehr (Timeout)"
        else:
            job.status = "queued"
            job.run_after = utcnow()
            job.worker_id = None
            job.error = "Neu eingeplant nach Worker-Timeout"
    db.commit()
    return len(stale)


def last_manual_request(db: Session, artist_id: int) -> datetime | None:
    return db.execute(
        select(func.max(CrawlerJob.created_at)).where(
            CrawlerJob.artist_id == artist_id, CrawlerJob.reason == "manual", CrawlerJob.job_type == "artist_crawl"
        )
    ).scalar()
