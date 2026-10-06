"""Executes crawler jobs (used by the worker, the CLI and tests)."""

from __future__ import annotations

import logging
import traceback
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from tourdesk.core.db import get_session_factory
from tourdesk.core.timeutil import utcnow
from tourdesk.models import CrawlerJob
from tourdesk.services.jobs import finish_job, retry_job
from tourdesk_crawler.jobs.artist_crawl import run_artist_crawl
from tourdesk_crawler.jobs.check import run_source_check
from tourdesk_crawler.jobs.enrich import run_enrich
from tourdesk_crawler.jobs.maintenance import run_maintenance
from tourdesk_crawler.jobs.source_crawl import run_source_crawl

log = logging.getLogger("tourdesk.crawler")


def dispatch(db: Session, sf: sessionmaker[Session], job: CrawlerJob) -> dict[str, Any]:
    payload = job.payload or {}
    force = bool(payload.get("force"))
    if job.job_type == "artist_crawl":
        return run_artist_crawl(db, sf, job, job.artist_id, force=force)  # type: ignore[arg-type]
    if job.job_type == "source_crawl":
        return run_source_crawl(db, sf, job, job.source_id, force=force)  # type: ignore[arg-type]
    if job.job_type == "artist_enrich":
        return run_enrich(db, sf, job, job.artist_id, force_image=bool(payload.get("force_image")))  # type: ignore[arg-type]
    if job.job_type == "source_check":
        return run_source_check(db, sf, job.source_id)  # type: ignore[arg-type]
    if job.job_type == "maintenance":
        return run_maintenance(db)
    raise ValueError(f"Unbekannter Jobtyp {job.job_type}")


def execute_job(job_id: int, sf: sessionmaker[Session] | None = None) -> tuple[str, dict[str, Any]]:
    """Run a claimed job and store its outcome. Never raises."""
    sf = sf or get_session_factory()
    with sf() as db:
        job = db.get(CrawlerJob, job_id)
        if job is None:
            return "failed", {"error": "Job verschwunden"}
        try:
            result = dispatch(db, sf, job)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.exception("job %s failed", job_id, extra={"event": "crawler.job_error", "job_type": job.job_type})
            job = db.get(CrawlerJob, job_id)
            msg = f"{exc.__class__.__name__}: {exc}"[:2000]
            if job is not None and not retry_job(db, job, msg + "\n" + traceback.format_exc()[-2000:]):
                return "failed", {"error": msg}
            return "retry", {"error": msg}
        status = {"success": "succeeded", "partial": "partial", "failed": "failed", "skipped": "succeeded"}.get(
            str(result.get("status")), "succeeded"
        )
        if job.job_type == "source_check":
            status = "succeeded" if result.get("ok") else "failed"
        finish_job(db, job, status, result=_jsonable(result))
        return status, result


def run_job_inline(job_type: str, *, artist_id: int | None = None, source_id: int | None = None,
                   payload: dict[str, Any] | None = None, sf: sessionmaker[Session] | None = None) -> dict[str, Any]:
    """Create and immediately execute a job (CLI and tests)."""
    sf = sf or get_session_factory()
    with sf() as db:
        job = CrawlerJob(job_type=job_type, artist_id=artist_id, source_id=source_id, payload=payload or {"force": True},
                         status="running", priority=9, reason="manual", attempts=1, max_attempts=1,
                         started_at=utcnow(), heartbeat_at=utcnow(), worker_id="inline")
        db.add(job)
        db.commit()
        job_id = job.id
    _status, result = execute_job(job_id, sf)
    return result


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
