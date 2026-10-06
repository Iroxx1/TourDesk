"""/api/venues – venue catalogue (shared), personal favourites live in the filter profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tourdesk.core.db import get_db
from tourdesk.core.text import normalize_name, normalize_variants
from tourdesk.core.timeutil import local_today
from tourdesk.models import City, Event, Source, UserVenue, Venue
from tourdesk.schemas.geo import VenueCreate, VenueOut, VenueUpdate
from tourdesk.security.deps import AuthContext, get_context
from tourdesk.services import audit
from tourdesk.services.filters import get_default_filter
from tourdesk.services.geo import search_venues, venue_out, venues_with_agenda

router = APIRouter(prefix="/venues", tags=["venues"])


def _favorites(db: Session, user_id: int) -> set[int]:
    return {r[0] for r in db.execute(select(UserVenue.venue_id).where(UserVenue.user_id == user_id)).all()}


def _upcoming_counts(db: Session, venue_ids: list[int]) -> dict[int, int]:
    if not venue_ids:
        return {}
    today = local_today()
    return dict(
        db.execute(
            select(Event.venue_id, func.count(Event.id))
            .where(Event.venue_id.in_(venue_ids), Event.event_date >= today, Event.is_listed.is_(True))
            .group_by(Event.venue_id)
        ).all()
    )


def _serialize(db: Session, venues: list[Venue], user_id: int) -> list[VenueOut]:
    ids = [v.id for v in venues]
    fav = _favorites(db, user_id)
    agenda = venues_with_agenda(db, ids)
    counts = _upcoming_counts(db, ids)
    return [venue_out(v, upcoming=counts.get(v.id, 0), has_agenda=v.id in agenda, favorite=v.id in fav) for v in venues]


@router.get("", response_model=list[VenueOut])
def list_venues(
    q: str = Query("", max_length=100),
    city_id: int | None = None,
    country_id: int | None = None,
    favorites: bool = False,
    limit: int = Query(30, ge=1, le=200),
    ctx: AuthContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> list[VenueOut]:
    if favorites:
        ids = _favorites(db, ctx.user.id)
        venues = list(db.execute(select(Venue).where(Venue.id.in_(ids)).order_by(Venue.name)).unique().scalars()) if ids else []
    else:
        venues = search_venues(db, q, city_id=city_id, country_id=country_id, limit=limit)
    return _serialize(db, venues, ctx.user.id)


@router.get("/{venue_id}", response_model=VenueOut)
def get_venue(venue_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> VenueOut:
    venue = db.get(Venue, venue_id)
    if venue is None:
        raise HTTPException(404, "Veranstaltungsort nicht gefunden")
    return _serialize(db, [venue], ctx.user.id)[0]


def _ensure_agenda_source(db: Session, venue: Venue, url: str, user_id: int) -> None:
    exists = db.execute(select(Source.id).where(Source.venue_id == venue.id, Source.url == url)).first()
    if exists:
        return
    db.add(
        Source(
            scope="venue",
            provider="venue_website",
            name=f"{venue.name} – Programm",
            url=url,
            venue_id=venue.id,
            trust_level=2,
            is_enabled=True,
            is_auto=False,
            config={"auto_relevance": True, "discover": True},
            created_by_user_id=user_id,
        )
    )


@router.post("", response_model=VenueOut, status_code=status.HTTP_201_CREATED)
def create_venue(
    payload: VenueCreate, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> VenueOut:
    city = db.get(City, payload.city_id)
    if city is None:
        raise HTTPException(422, "Unbekannte Stadt")
    name_norm = normalize_name(payload.name)
    venue = db.execute(select(Venue).where(Venue.city_id == city.id, Venue.name_norm == name_norm)).unique().scalar_one_or_none()
    created = venue is None
    if venue is None:
        aliases = [a.strip() for a in payload.aliases if a and a.strip()][:20]
        venue = Venue(
            city_id=city.id,
            name=payload.name.strip(),
            name_norm=name_norm,
            aliases=aliases,
            aliases_norm=sorted(set().union(*(normalize_variants(a) for a in [payload.name, *aliases]))),
            address=payload.address,
            postal_code=payload.postal_code,
            website=payload.website,
            is_auto=False,
            created_by_user_id=ctx.actor.id,
        )
        db.add(venue)
        db.flush()
    agenda = payload.agenda_url or payload.website
    if agenda:
        _ensure_agenda_source(db, venue, agenda, ctx.actor.id)
    if payload.add_to_filters:
        f = get_default_filter(db, ctx.user.id)
        exists = db.execute(select(UserVenue.id).where(UserVenue.filter_id == f.id, UserVenue.venue_id == venue.id)).first()
        if not exists:
            db.add(UserVenue(user_id=ctx.user.id, filter_id=f.id, venue_id=venue.id))
    if created:
        audit.record(db, "venue.create", actor=ctx.actor, request=request, target_type="venue", target_id=venue.id, target_label=venue.name)
    db.commit()
    return _serialize(db, [venue], ctx.user.id)[0]


@router.patch("/{venue_id}", response_model=VenueOut)
def update_venue(
    venue_id: int, payload: VenueUpdate, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> VenueOut:
    venue = db.get(Venue, venue_id)
    if venue is None:
        raise HTTPException(404, "Veranstaltungsort nicht gefunden")
    if not (ctx.is_admin or venue.created_by_user_id == ctx.actor.id):
        raise HTTPException(403, "Nur Administratoren oder der Ersteller können diesen Ort bearbeiten")
    data = payload.model_dump(exclude_unset=True)
    if data.get("name"):
        venue.name = data["name"].strip()
        venue.name_norm = normalize_name(venue.name)
    if "city_id" in data and data["city_id"]:
        city = db.get(City, data["city_id"])
        if city is None:
            raise HTTPException(422, "Unbekannte Stadt")
        venue.city_id = city.id
        from tourdesk.services.events import refresh_event_locations_for_venue

        refresh_event_locations_for_venue(db, venue)
    for field in ("address", "postal_code", "website", "kind", "needs_review"):
        if field in data:
            setattr(venue, field, data[field])
    if data.get("aliases") is not None:
        venue.aliases = [a.strip() for a in data["aliases"] if a and a.strip()][:30]
    venue.aliases_norm = sorted(set().union(*(normalize_variants(a) for a in [venue.name, *(venue.aliases or [])])))
    audit.record(db, "venue.update", actor=ctx.actor, request=request, target_type="venue", target_id=venue.id,
                 target_label=venue.name, details={k: str(v) for k, v in data.items()})
    db.commit()
    return _serialize(db, [venue], ctx.user.id)[0]
