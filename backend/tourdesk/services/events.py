"""Event serialisation and maintenance helpers."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tourdesk.core.constants import provider_label
from tourdesk.models import City, Event, Venue
from tourdesk.models.enums import TRUST_LABELS
from tourdesk.schemas.artists import CountryRef, EventDetailOut, EventOut, EventSourceOut, NamedRef, TicketOut
from tourdesk.services.filter_engine import Decision


def event_out(e: Event, decision: Decision | None = None) -> EventOut:
    venue_name = e.venue.name if e.venue else e.venue_name
    city_name = e.city.display_name if e.city else e.city_name
    return EventOut(
        id=e.id,
        artist_id=e.artist_id,
        artist_name=e.artist.name,
        title=e.title,
        date=e.event_date,
        end_date=e.end_date,
        start_time=e.start_time,
        doors_time=e.doors_time,
        timezone=e.timezone,
        event_type=e.event_type,
        status=e.status,
        ticket_status=e.ticket_status,
        ticket_url=e.ticket_url,
        ticket_provider=e.ticket_provider,
        onsale_at=e.onsale_at,
        venue=NamedRef(id=e.venue.id, name=e.venue.name) if e.venue else None,
        venue_name=venue_name,
        city=NamedRef(id=e.city.id, name=e.city.display_name) if e.city else None,
        city_name=city_name,
        region=NamedRef(id=e.region.id, name=e.region.display_name) if e.region else None,
        country=CountryRef(id=e.country.id, code=e.country.code, name=e.country.name_de) if e.country else None,
        tour=NamedRef(id=e.tour.id, name=e.tour.name) if e.tour else None,
        festival=NamedRef(id=e.festival.id, name=e.festival.name) if e.festival else None,
        is_confirmed=e.is_confirmed,
        confidence=round(e.confidence, 2),
        source_count=e.source_count,
        best_trust=e.best_trust,
        is_listed=e.is_listed,
        primary_source_url=e.primary_source_url,
        first_seen_at=e.first_seen_at,
        last_seen_at=e.last_seen_at,
        last_checked_at=e.last_checked_at,
        updated_at=e.updated_at,
        matches=decision.shown if decision else None,
        hidden_reason=decision.hidden_reason if decision else None,
    )


def event_detail_out(e: Event, decision: Decision | None, *, include_explanation: bool = True) -> EventDetailOut:
    base = event_out(e, decision).model_dump()
    sources = []
    for obs in sorted(e.observations, key=lambda o: (not o.is_active, o.trust_level, o.first_seen_at)):
        sources.append(
            EventSourceOut(
                provider=obs.provider,
                provider_label=provider_label(obs.provider),
                source_name=obs.source.name if obs.source else obs.provider,
                url=obs.url,
                domain=obs.domain,
                trust_level=obs.trust_level,
                trust_label=TRUST_LABELS.get(obs.trust_level, "Quelle"),
                is_active=obs.is_active,
                first_seen_at=obs.first_seen_at,
                last_seen_at=obs.last_seen_at,
            )
        )
    tickets = [
        TicketOut(
            provider=t.provider,
            url=t.url,
            status=t.status,
            trust_level=t.trust_level,
            price_min=float(t.price_min) if t.price_min is not None else None,
            price_max=float(t.price_max) if t.price_max is not None else None,
            currency=t.currency,
            is_active=t.is_active,
        )
        for t in sorted(e.tickets, key=lambda t: (not t.is_active, t.trust_level))
    ]
    from tourdesk.services.media import artist_image_url

    return EventDetailOut(
        **base,
        sources=sources,
        tickets=tickets,
        explanation=decision.as_dict() if (decision and include_explanation) else None,
        artist_image=artist_image_url(e.artist.image_path, e.artist.image_source, e.artist.image_version, "hero"),
    )


def refresh_event_regions_for_city(db: Session, city: City) -> None:
    """After a city's region changed, update the denormalised event columns."""
    db.execute(
        update(Event)
        .where(Event.city_id == city.id)
        .values(region_id=city.region_id, country_id=city.country_id)
    )


def refresh_event_locations_for_venue(db: Session, venue: Venue) -> None:
    city = db.get(City, venue.city_id) if venue.city_id else None
    db.execute(
        update(Event)
        .where(Event.venue_id == venue.id)
        .values(
            city_id=city.id if city else None,
            region_id=city.region_id if city else None,
            country_id=city.country_id if city else None,
        )
    )


def events_for_artist(db: Session, artist_id: int) -> list[Event]:
    return list(
        db.execute(select(Event).where(Event.artist_id == artist_id).order_by(Event.event_date, Event.start_time))
        .unique()
        .scalars()
    )
