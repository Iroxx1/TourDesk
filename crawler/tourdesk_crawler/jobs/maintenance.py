"""Daily maintenance: prune old runs/errors/jobs/cache/sessions/notifications."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from tourdesk.core.timeutil import utcnow
from tourdesk.models import CrawlerError, CrawlerJob, CrawlerRun, HttpCacheEntry, Notification
from tourdesk.security.sessions import cleanup_expired_sessions
from tourdesk.services.app_settings import crawler_settings


def run_maintenance(db: Session) -> dict[str, Any]:
    settings = crawler_settings(db, fresh=True)
    keep = timedelta(days=int(settings.get("keep_runs_days", 30)))
    now = utcnow()
    out: dict[str, Any] = {}
    out["errors"] = db.execute(delete(CrawlerError).where(CrawlerError.occurred_at < now - keep)).rowcount
    out["runs"] = db.execute(delete(CrawlerRun).where(CrawlerRun.started_at < now - keep)).rowcount
    out["jobs"] = db.execute(
        delete(CrawlerJob).where(CrawlerJob.status.in_(["succeeded", "partial", "failed", "cancelled"]), CrawlerJob.created_at < now - timedelta(days=7))
    ).rowcount
    out["http_cache"] = db.execute(delete(HttpCacheEntry).where(HttpCacheEntry.fetched_at < now - timedelta(days=7))).rowcount
    out["notifications"] = db.execute(
        delete(Notification).where(Notification.read_at.is_not(None), Notification.read_at < now - timedelta(days=90))
    ).rowcount
    out["sessions"] = cleanup_expired_sessions(db)
    db.commit()
    return out
