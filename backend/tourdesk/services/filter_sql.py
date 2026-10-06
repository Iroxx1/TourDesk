"""SQL version of the filter rules for paginated event queries.

Must stay in sync with :func:`tourdesk.services.filter_engine.evaluate`
(see ``tests/api/test_filter_sql_equivalence.py``).
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, false, or_, select, true
from sqlalchemy.sql import Select

from tourdesk.models import Event, UserArtist
from tourdesk.services.filter_engine import HIDE_STATUSES, FilterProfile


def event_predicate(profile: FilterProfile) -> ColumnElement[bool]:
    """Predicate over ``Event`` joined with the user's ``UserArtist`` row."""
    conds: list[ColumnElement[bool]] = [Event.is_listed.is_(True), UserArtist.is_active.is_(True)]
    if not profile.show_unconfirmed:
        conds.append(Event.is_confirmed.is_(True))
    if profile.date_from:
        conds.append(Event.event_date >= profile.date_from)
    if profile.date_to:
        conds.append(Event.event_date <= profile.date_to)
    if not profile.show_cancelled:
        conds.append(Event.status.notin_(sorted(HIDE_STATUSES)))

    types = []
    if profile.include_concerts:
        types.append("concert")
    if profile.include_support:
        types.append("support")
    if profile.include_special:
        types.append("special")
    type_cond: ColumnElement[bool] = Event.event_type.in_(types) if types else false()
    if profile.festival_mode == "never":
        festival_cond: ColumnElement[bool] = false()
    elif profile.festival_mode == "always":
        festival_cond = Event.event_type == "festival"
    else:
        festival_cond = and_(Event.event_type == "festival", UserArtist.show_festivals.is_(True))
    conds.append(or_(type_cond, festival_cond))

    if profile.has_location_rules:
        loc_parts: list[ColumnElement[bool]] = []
        venues, cities, regions, countries = (profile.ids(lvl) for lvl in ("venue", "city", "region", "country"))
        if venues:
            loc_parts.append(Event.venue_id.in_(venues))
        if cities:
            loc_parts.append(Event.city_id.in_(cities))
        if regions:
            loc_parts.append(Event.region_id.in_(regions))
        if countries:
            loc_parts.append(Event.country_id.in_(countries))
        loc: ColumnElement[bool] = or_(*loc_parts) if loc_parts else false()
        if profile.festival_scope == "anywhere":
            loc = or_(loc, Event.event_type == "festival")
        conds.append(loc)
    return and_(*conds) if conds else true()


def matching_events_query(user_id: int, profile: FilterProfile) -> Select:
    return (
        select(Event)
        .join(UserArtist, and_(UserArtist.artist_id == Event.artist_id, UserArtist.user_id == user_id))
        .where(event_predicate(profile))
    )
