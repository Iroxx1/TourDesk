"""/api/search, /api/notifications, /api/crawler (user scope)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from tourdesk.core.db import get_db
from tourdesk.core.timeutil import utcnow
from tourdesk.models import CrawlerJob, CrawlerRun, Notification, UserArtist
from tourdesk.models.enums import NOTIFICATION_LABELS
from tourdesk.schemas.common import ApiModel, OkResponse
from tourdesk.security.deps import AuthContext, get_context
from tourdesk.services.search import global_search

router = APIRouter(tags=["misc"])


@router.get("/search")
def search(q: str = Query(..., min_length=1, max_length=100), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> dict:
    return global_search(db, ctx.user, q)


class NotificationOut(ApiModel):
    id: int
    type: str
    type_label: str
    title: str
    body: str | None = None
    artist_id: int | None = None
    event_id: int | None = None
    created_at: datetime
    read_at: datetime | None = None


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id, type=n.type, type_label=NOTIFICATION_LABELS.get(n.type, n.type), title=n.title, body=n.body,
        artist_id=n.artist_id, event_id=n.event_id, created_at=n.created_at, read_at=n.read_at,
    )


@router.get("/notifications")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Notification).where(Notification.user_id == ctx.user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.execute(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)).scalars().all()
    unread = db.execute(
        select(func.count(Notification.id)).where(Notification.user_id == ctx.user.id, Notification.read_at.is_(None))
    ).scalar_one()
    return {"items": [_out(n).model_dump(mode="json") for n in rows], "unread": unread}


@router.get("/notifications/unread-count")
def unread_count(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> dict:
    unread = db.execute(
        select(func.count(Notification.id)).where(Notification.user_id == ctx.user.id, Notification.read_at.is_(None))
    ).scalar_one()
    return {"unread": unread}


@router.post("/notifications/{notification_id}/read", response_model=OkResponse)
def mark_read(notification_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> OkResponse:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != ctx.user.id:
        raise HTTPException(404, "Benachrichtigung nicht gefunden")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return OkResponse()


@router.post("/notifications/read-all", response_model=OkResponse)
def mark_all_read(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> OkResponse:
    db.execute(
        update(Notification)
        .where(Notification.user_id == ctx.user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    return OkResponse()


@router.delete("/notifications", response_model=OkResponse)
def clear_notifications(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> OkResponse:
    db.execute(delete(Notification).where(Notification.user_id == ctx.user.id, Notification.read_at.is_not(None)))
    db.commit()
    return OkResponse()


@router.get("/crawler/status")
def crawler_status(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> dict:
    artist_ids = [r[0] for r in db.execute(select(UserArtist.artist_id).where(UserArtist.user_id == ctx.user.id)).all()]
    jobs = []
    if artist_ids:
        jobs = db.execute(
            select(CrawlerJob.artist_id, CrawlerJob.status, CrawlerJob.job_type).where(
                CrawlerJob.artist_id.in_(artist_ids), CrawlerJob.status.in_(["queued", "running"])
            )
        ).all()
    last_run = db.execute(select(func.max(CrawlerRun.finished_at))).scalar()
    return {
        "last_run_at": last_run,
        "running": sorted({j.artist_id for j in jobs if j.status == "running"}),
        "queued": sorted({j.artist_id for j in jobs if j.status == "queued"}),
    }
