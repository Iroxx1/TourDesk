"""Builds the desktop tiles and the per-artist event views."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tourdesk.core.timeutil import utcnow
from tourdesk.models import CrawlerRun, Event, Tour, User, UserArtist
from tourdesk.schemas.artists import ArtistEventsOut, DashboardOut, NamedRef, TileOut, TourStatusOut
from tourdesk.services.artists import artist_out
from tourdesk.services.events import event_out
from tourdesk.services.filter_engine import ArtistPref, FilterProfile, evaluate
from tourdesk.services.filters import event_facts, load_profile
from tourdesk.services.tour_status import TourEvent, compute_tour_status

PAST_WINDOW_DAYS = 120


def _tour_event(e: Event) -> TourEvent:
    return TourEvent(
        event_date=e.event_date,
        tour_id=e.tour_id,
        tour_name=e.tour.name if e.tour else None,
        event_type=e.event_type,
        status=e.status,
        is_listed=e.is_listed,
        is_confirmed=e.is_confirmed,
        city_name=e.city.display_name if e.city else e.city_name,
    )


def _pref(ua: UserArtist) -> ArtistPref:
    return ArtistPref(
        artist_id=ua.artist_id, artist_name=ua.artist.name, followed=True, active=ua.is_active, show_festivals=ua.show_festivals
    )


def _sort_key(e: Event) -> tuple:
    minutes = e.start_time.hour * 60 + e.start_time.minute if e.start_time else 0
    return (e.event_date, minutes, e.id)


def build_dashboard(db: Session, user: User, *, tile_events: int = 3, today: date | None = None) -> DashboardOut:
    profile, _f = load_profile(db, user, today)
    today = profile.date_from or today or utcnow().date()
    subscriptions = db.execute(
        select(UserArtist).where(UserArtist.user_id == user.id).order_by(UserArtist.sort_order, UserArtist.id)
    ).unique().scalars().all()
    artist_ids = [ua.artist_id for ua in subscriptions]
    events_by_artist: dict[int, list[Event]] = defaultdict(list)
    if artist_ids:
        rows = db.execute(
            select(Event).where(
                Event.artist_id.in_(artist_ids), Event.event_date >= today - timedelta(days=PAST_WINDOW_DAYS)
            )
        ).unique().scalars().all()
        for e in rows:
            events_by_artist[e.artist_id].append(e)

    tiles: list[TileOut] = []
    total_matching = 0
    for ua in subscriptions:
        events = sorted(events_by_artist.get(ua.artist_id, []), key=_sort_key)
        tile = _tile(ua, events, profile, today, tile_events)
        total_matching += tile.matching_count
        tiles.append(tile)

    last_run = db.execute(select(func.max(CrawlerRun.finished_at))).scalar()
    return DashboardOut(
        tiles=tiles,
        total_matching=total_matching,
        generated_at=utcnow(),
        has_location_rules=profile.has_location_rules,
        crawler_last_run=last_run,
    )


def _tile(ua: UserArtist, events: list[Event], profile: FilterProfile, today: date, tile_events: int) -> TileOut:
    pref = _pref(ua)
    status = compute_tour_status([_tour_event(e) for e in events], today)
    upcoming = [e for e in events if e.event_date >= today and e.is_listed]
    matching = []
    hidden_festivals = 0
    outside = 0
    for e in upcoming:
        decision = evaluate(event_facts(e), pref, profile)
        if decision.shown:
            matching.append((e, decision))
        else:
            if e.event_type == "festival" and decision.hidden_reason == "Festival ausgeblendet":
                hidden_festivals += 1
            elif decision.hidden_reason == "Außerhalb deiner Filter":
                outside += 1
    return TileOut(
        artist=artist_out(ua.artist, ua),
        tour_status=TourStatusOut(**status.as_dict()),
        matching_events=[event_out(e, d) for e, d in matching[:tile_events]],
        matching_count=len(matching),
        more_count=max(0, len(matching) - tile_events),
        total_upcoming=len([e for e in upcoming if e.is_confirmed]),
        festival_upcoming=len([e for e in upcoming if e.event_type == "festival" and e.is_confirmed]),
        hidden_festivals=hidden_festivals,
        outside_filters=outside,
        last_updated=ua.artist.last_success_at,
    )


def build_artist_events(db: Session, user: User, ua: UserArtist | None, artist_id: int, *, include_past: bool = True) -> ArtistEventsOut:
    profile, _f = load_profile(db, user)
    today = profile.date_from or utcnow().date()
    events = sorted(
        db.execute(select(Event).where(Event.artist_id == artist_id)).unique().scalars().all(),
        key=_sort_key,
    )
    pref = _pref(ua) if ua else ArtistPref(artist_id=artist_id, artist_name="", followed=False, active=False)
    status = compute_tour_status([_tour_event(e) for e in events], today)
    matching, all_events, past = [], [], []
    for e in events:
        decision = evaluate(event_facts(e), pref, profile)
        out = event_out(e, decision)
        if e.event_date < today:
            if include_past and e.event_date >= today - timedelta(days=365):
                past.append(out)
            continue
        if not e.is_listed and e.event_date >= today:
            all_events.append(out)
            continue
        all_events.append(out)
        if decision.shown:
            matching.append(out)
    tours = db.execute(select(Tour).where(Tour.artist_id == artist_id).order_by(Tour.start_date)).scalars().all()
    return ArtistEventsOut(
        artist_id=artist_id,
        tour_status=TourStatusOut(**status.as_dict()),
        matching=matching,
        all_events=all_events,
        past_events=list(reversed(past))[:50],
        tours=[NamedRef(id=t.id, name=t.name) for t in tours],
    )
