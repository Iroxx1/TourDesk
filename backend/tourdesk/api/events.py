"""/api/events, /api/tours, /api/festivals, /api/dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from tourdesk.core.db import get_db
from tourdesk.core.text import escape_like, normalize_name
from tourdesk.core.timeutil import utcnow
from tourdesk.models import City, Event, Festival, Tour, UserArtist, Venue
from tourdesk.schemas.artists import DashboardOut, EventDetailOut, EventOut, NamedRef
from tourdesk.schemas.common import Page
from tourdesk.security.deps import AuthContext, get_context
from tourdesk.services.dashboard import build_dashboard
from tourdesk.services.events import event_detail_out, event_out
from tourdesk.services.filter_engine import ArtistPref, evaluate
from tourdesk.services.filter_sql import matching_events_query
from tourdesk.services.filters import artist_prefs, event_facts, load_profile

router = APIRouter(tags=["events"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> DashboardOut:
    view = (ctx.user.settings.view if ctx.user.settings else None) or {}
    count = view.get("tile_event_count", 3)
    return build_dashboard(db, ctx.user, tile_events=count if isinstance(count, int) and 1 <= count <= 10 else 3)


@router.get("/events", response_model=Page[EventOut])
def list_events(
    scope: str = Query("matching", pattern="^(matching|all)$"),
    artist_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    event_type: str | None = Query(None, pattern="^(concert|festival|support|special)$"),
    q: str = Query("", max_length=100),
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> Page[EventOut]:
    profile, _f = load_profile(db, ctx.user)
    if scope == "matching":
        stmt = matching_events_query(ctx.user.id, profile)
    else:
        stmt = (
            select(Event)
            .join(UserArtist, and_(UserArtist.artist_id == Event.artist_id, UserArtist.user_id == ctx.user.id))
            .where(Event.event_date >= (profile.date_from or date.today()))
        )
    if artist_id:
        stmt = stmt.where(Event.artist_id == artist_id)
    if date_from:
        stmt = stmt.where(Event.event_date >= date_from)
    if date_to:
        stmt = stmt.where(Event.event_date <= date_to)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if q.strip():
        pattern = "%" + escape_like(normalize_name(q)) + "%"
        stmt = (
            stmt.outerjoin(Venue, Venue.id == Event.venue_id)
            .outerjoin(City, City.id == Event.city_id)
            .where(
                or_(
                    func.lower(func.coalesce(Event.title, "")).like("%" + escape_like(q.lower()) + "%", escape="\\"),
                    Venue.name_norm.like(pattern, escape="\\"),
                    City.name_norm.like(pattern, escape="\\"),
                )
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(Event.event_date, Event.start_time.nulls_last(), Event.id).offset(offset).limit(limit)
    ).unique().scalars().all()
    prefs = artist_prefs(db, ctx.user.id)
    items = [event_out(e, evaluate(event_facts(e), prefs.get(e.artist_id), profile)) for e in rows]
    return Page[EventOut](items=items, total=total, offset=offset, limit=limit)


def _event_for_user(db: Session, ctx: AuthContext, event_id: int) -> tuple[Event, ArtistPref | None]:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(404, "Event nicht gefunden")
    prefs = artist_prefs(db, ctx.user.id)
    pref = prefs.get(event.artist_id)
    if pref is None and not ctx.is_admin:
        raise HTTPException(404, "Event nicht gefunden")
    return event, pref


@router.get("/events/{event_id}", response_model=EventDetailOut)
def get_event(event_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> EventDetailOut:
    event, pref = _event_for_user(db, ctx, event_id)
    profile, _f = load_profile(db, ctx.user)
    decision = evaluate(event_facts(event), pref, profile)
    return event_detail_out(event, decision)


@router.get("/events/{event_id}/explain")
def explain_event(event_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> dict:
    event, pref = _event_for_user(db, ctx, event_id)
    profile, _f = load_profile(db, ctx.user)
    return evaluate(event_facts(event), pref, profile).as_dict()


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@router.get("/events/{event_id}/ical")
def event_ical(event_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> Response:
    event, _pref = _event_for_user(db, ctx, event_id)
    out = event_out(event)
    summary = f"{out.artist_name} – {out.venue_name or out.city_name or 'Konzert'}"
    location = ", ".join(p for p in (out.venue_name, out.city_name, out.country.name if out.country else None) if p)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TourDesk//DE", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
             f"UID:tourdesk-event-{event.id}@tourdesk", f"DTSTAMP:{utcnow():%Y%m%dT%H%M%SZ}"]
    if event.start_time and event.timezone:
        start = datetime.combine(event.event_date, event.start_time)
        lines.append(f"DTSTART;TZID={event.timezone}:{start:%Y%m%dT%H%M%S}")
        lines.append(f"DTEND;TZID={event.timezone}:{start + timedelta(hours=3):%Y%m%dT%H%M%S}")
    else:
        lines.append(f"DTSTART;VALUE=DATE:{event.event_date:%Y%m%d}")
        lines.append(f"DTEND;VALUE=DATE:{(event.end_date or event.event_date) + timedelta(days=1):%Y%m%d}")
    lines.append(f"SUMMARY:{_ics_escape(summary)}")
    if location:
        lines.append(f"LOCATION:{_ics_escape(location)}")
    url = event.ticket_url or event.primary_source_url
    if url:
        lines.append(f"URL:{url}")
    if event.status == "cancelled":
        lines.append("STATUS:CANCELLED")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return Response(
        "\r\n".join(lines) + "\r\n",
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="tourdesk-{event.id}.ics"'},
    )


@router.get("/tours/{tour_id}")
def get_tour(tour_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> dict:
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(404, "Tour nicht gefunden")
    prefs = artist_prefs(db, ctx.user.id)
    if tour.artist_id not in prefs and not ctx.is_admin:
        raise HTTPException(404, "Tour nicht gefunden")
    profile, _f = load_profile(db, ctx.user)
    events = db.execute(select(Event).where(Event.tour_id == tour_id).order_by(Event.event_date)).unique().scalars().all()
    return {
        "id": tour.id,
        "name": tour.name,
        "artist_id": tour.artist_id,
        "start_date": tour.start_date,
        "end_date": tour.end_date,
        "events": [event_out(e, evaluate(event_facts(e), prefs.get(e.artist_id), profile)).model_dump(mode="json") for e in events],
    }


@router.get("/festivals", response_model=list[NamedRef])
def list_festivals(q: str = Query("", max_length=100), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> list[NamedRef]:
    stmt = select(Festival)
    if q.strip():
        stmt = stmt.where(Festival.name_norm.like("%" + escape_like(normalize_name(q)) + "%", escape="\\"))
    return [NamedRef(id=f.id, name=f.name) for f in db.execute(stmt.order_by(Festival.name).limit(100)).unique().scalars()]


@router.get("/festivals/{festival_id}")
def get_festival(festival_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> dict:
    festival = db.get(Festival, festival_id)
    if festival is None:
        raise HTTPException(404, "Festival nicht gefunden")
    prefs = artist_prefs(db, ctx.user.id)
    profile, _f = load_profile(db, ctx.user)
    events = db.execute(
        select(Event).where(Event.festival_id == festival_id, Event.artist_id.in_(list(prefs) or [-1])).order_by(Event.event_date)
    ).unique().scalars().all()
    return {
        "id": festival.id,
        "name": festival.name,
        "website": festival.website,
        "city": festival.city.display_name if festival.city else None,
        "venue": festival.venue.name if festival.venue else None,
        "events": [event_out(e, evaluate(event_facts(e), prefs.get(e.artist_id), profile)).model_dump(mode="json") for e in events],
    }
