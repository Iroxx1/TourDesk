"""Loading filter profiles from the database and converting events to engine facts."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tourdesk.core.timeutil import local_today
from tourdesk.models import Event, User, UserArtist, UserCity, UserCountry, UserFilter, UserRegion, UserSettings, UserVenue
from tourdesk.services.filter_engine import ArtistPref, EventFacts, FilterProfile, LocationRule


def get_default_filter(db: Session, user_id: int) -> UserFilter:
    row = db.execute(
        select(UserFilter).where(UserFilter.user_id == user_id).order_by(UserFilter.is_default.desc(), UserFilter.id)
    ).scalars().first()
    if row is None:
        row = UserFilter(user_id=user_id, name="Standard", is_default=True)
        db.add(row)
        db.flush()
    return row


def user_today(db: Session, user_id: int) -> date:
    row = db.get(UserSettings, user_id)
    return local_today(row.timezone if row else "Europe/Berlin")


def resolve_date_range(f: UserFilter, today: date) -> tuple[date | None, date | None]:
    if f.date_mode == "months" and f.months_ahead:
        return today, today + timedelta(days=int(f.months_ahead) * 31)
    if f.date_mode == "range":
        return f.date_from or today, f.date_to
    return today, None


def region_coverage(db: Session, region_ids: set[int]) -> dict[int, frozenset[int]]:
    """Map each region to itself plus all descendant regions (recursive)."""
    if not region_ids:
        return {}
    rows = db.execute(
        text(
            """
            WITH RECURSIVE tree(root, id) AS (
                SELECT r.id, r.id FROM regions r WHERE r.id = ANY(:ids)
                UNION
                SELECT t.root, c.id FROM regions c JOIN tree t ON c.parent_id = t.id
            )
            SELECT root, id FROM tree
            """
        ),
        {"ids": list(region_ids)},
    ).all()
    out: dict[int, set[int]] = {rid: {rid} for rid in region_ids}
    for root, rid in rows:
        out.setdefault(root, {root}).add(rid)
    return {k: frozenset(v) for k, v in out.items()}


def location_rules(f: UserFilter) -> list[LocationRule]:
    rules: list[LocationRule] = []
    for c in f.countries:
        rules.append(LocationRule(c.id * 10 + 1, "country", c.country_id, c.country.name_de, c.country_id, c.country.name_de))
    for r in f.regions:
        region = r.region
        rules.append(LocationRule(r.id * 10 + 2, "region", r.region_id, region.display_name, region.country_id, region.country.name_de))
    for c in f.cities:
        city = c.city
        rules.append(LocationRule(c.id * 10 + 3, "city", c.city_id, city.display_name, city.country_id, city.country.name_de))
    for v in f.venues:
        venue = v.venue
        country_id = venue.city.country_id if venue.city else None
        country_label = venue.city.country.name_de if venue.city else None
        rules.append(LocationRule(v.id * 10 + 4, "venue", v.venue_id, venue.name, country_id, country_label))
    return rules


def rule_public_id(rule: LocationRule) -> tuple[str, int]:
    """Location rules get compound ids (row id * 10 + level digit)."""
    return rule.level, rule.id // 10


def build_profile(db: Session, f: UserFilter, today: date) -> FilterProfile:
    rules = tuple(location_rules(f))
    coverage = region_coverage(db, {r.target_id for r in rules if r.level == "region"})
    date_from, date_to = resolve_date_range(f, today)
    return FilterProfile(
        rules=rules,
        region_coverage=coverage,
        date_from=date_from,
        date_to=date_to,
        include_concerts=f.include_concerts,
        include_support=f.include_support,
        include_special=f.include_special,
        festival_mode=f.festival_mode,
        festival_scope=f.festival_scope,
        show_cancelled=f.show_cancelled,
        show_unconfirmed=f.show_unconfirmed,
    )


def load_profile(db: Session, user: User, today: date | None = None) -> tuple[FilterProfile, UserFilter]:
    f = get_default_filter(db, user.id)
    return build_profile(db, f, today or user_today(db, user.id)), f


def artist_prefs(db: Session, user_id: int) -> dict[int, ArtistPref]:
    rows = db.execute(select(UserArtist).where(UserArtist.user_id == user_id)).unique().scalars().all()
    return {
        ua.artist_id: ArtistPref(
            artist_id=ua.artist_id,
            artist_name=ua.artist.name,
            followed=True,
            active=ua.is_active,
            show_festivals=ua.show_festivals,
        )
        for ua in rows
    }


def event_facts(e: Event) -> EventFacts:
    return EventFacts(
        id=e.id,
        artist_id=e.artist_id,
        event_date=e.event_date,
        event_type=e.event_type,
        status=e.status,
        is_confirmed=e.is_confirmed,
        is_listed=e.is_listed,
        source_count=e.source_count,
        best_trust=e.best_trust,
        venue_id=e.venue_id,
        venue_name=e.venue.name if e.venue else e.venue_name,
        city_id=e.city_id,
        city_name=e.city.display_name if e.city else e.city_name,
        region_id=e.region_id,
        region_name=e.region.display_name if e.region else None,
        country_id=e.country_id,
        country_name=e.country.name_de if e.country else None,
        festival_name=e.festival.name if e.festival else None,
    )


def location_rule_count(db: Session, user_id: int) -> int:
    total = 0
    for model in (UserCountry, UserRegion, UserCity, UserVenue):
        total += len(db.execute(select(model.id).where(model.user_id == user_id)).all())
    return total
