"""Global search across artists, events, venues, cities, regions and countries."""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from tourdesk.core.text import escape_like, normalize_name, normalize_variants
from tourdesk.models import Artist, ArtistAlias, City, Country, Event, Festival, Region, User, UserArtist, Venue
from tourdesk.services.artists import artist_out, search_catalog
from tourdesk.services.events import event_out
from tourdesk.services.filter_engine import evaluate
from tourdesk.services.filters import artist_prefs, event_facts, load_profile
from tourdesk.services.geo import city_out, country_out, region_out, search_cities, search_regions, search_venues, venue_out


def global_search(db: Session, user: User, q: str) -> dict:
    q = q.strip()
    norm = normalize_name(q)
    if len(norm) < 2:
        return {"query": q, "artists": [], "catalog_artists": [], "events": [], "venues": [], "cities": [], "regions": [], "countries": []}
    variants = list(normalize_variants(q))
    like = "%" + escape_like(norm) + "%"

    # followed artists
    subs = db.execute(
        select(UserArtist)
        .join(Artist, Artist.id == UserArtist.artist_id)
        .outerjoin(ArtistAlias, ArtistAlias.artist_id == Artist.id)
        .where(UserArtist.user_id == user.id, or_(Artist.name_norm.like(like, escape="\\"), ArtistAlias.alias_norm.like(like, escape="\\")))
        .order_by(Artist.name)
    ).unique().scalars().all()
    followed_ids = {ua.artist_id for ua in subs}
    artists = [artist_out(ua.artist, ua).model_dump(mode="json") for ua in subs[:8]]
    catalog = [
        {"id": a.id, "name": a.name, "genre": a.genre}
        for a in search_catalog(db, q, limit=6)
        if a.id not in followed_ids
    ]

    # events of followed artists at matching places
    profile, _f = load_profile(db, user)
    prefs = artist_prefs(db, user.id)
    event_rows = []
    if prefs:
        stmt = (
            select(Event)
            .join(UserArtist, and_(UserArtist.artist_id == Event.artist_id, UserArtist.user_id == user.id))
            .join(Artist, Artist.id == Event.artist_id)
            .outerjoin(Venue, Venue.id == Event.venue_id)
            .outerjoin(City, City.id == Event.city_id)
            .outerjoin(Region, Region.id == Event.region_id)
            .outerjoin(Country, Country.id == Event.country_id)
            .outerjoin(Festival, Festival.id == Event.festival_id)
            .where(
                Event.event_date >= (profile.date_from or func.current_date()),
                Event.is_listed.is_(True),
                or_(
                    Artist.name_norm.like(like, escape="\\"),
                    Venue.name_norm.like(like, escape="\\"),
                    Venue.aliases_norm.overlap(variants),
                    City.name_norm.like(like, escape="\\"),
                    City.aliases_norm.overlap(variants),
                    Region.name_norm.like(like, escape="\\"),
                    Region.aliases_norm.overlap(variants),
                    Country.aliases_norm.overlap(variants),
                    Festival.name_norm.like(like, escape="\\"),
                    func.lower(func.coalesce(Event.title, "")).like("%" + escape_like(q.lower()) + "%", escape="\\"),
                ),
            )
            .order_by(Event.event_date)
            .limit(30)
        )
        event_rows = db.execute(stmt).unique().scalars().all()
    events = []
    for e in event_rows:
        decision = evaluate(event_facts(e), prefs.get(e.artist_id), profile)
        events.append(event_out(e, decision).model_dump(mode="json"))

    countries = db.execute(
        select(Country).where(or_(Country.name_norm.like(like, escape="\\"), Country.aliases_norm.overlap(variants))).order_by(Country.priority).limit(4)
    ).scalars().all()
    return {
        "query": q,
        "artists": artists,
        "catalog_artists": catalog,
        "events": events,
        "venues": [venue_out(v).model_dump(mode="json") for v in search_venues(db, q, limit=6)],
        "cities": [city_out(c).model_dump(mode="json") for c in search_cities(db, q, limit=6)],
        "regions": [region_out(r).model_dump(mode="json") for r in search_regions(db, q, limit=6)],
        "countries": [country_out(c).model_dump(mode="json") for c in countries],
    }
