"""Geography queries and serialisation."""

from __future__ import annotations

from sqlalchemy import case, false, func, or_, select
from sqlalchemy.orm import Session

from tourdesk.core.text import escape_like, normalize_name, normalize_variants
from tourdesk.models import City, Country, Region, Source, Venue
from tourdesk.schemas.geo import CityOut, CountryOut, LocationRuleOut, RegionOut, VenueOut
from tourdesk.services.filter_engine import LocationRule


def country_out(c: Country, region_count: int = 0) -> CountryOut:
    return CountryOut(id=c.id, code=c.code, name=c.name_de, name_en=c.name_en, priority=c.priority, region_count=region_count)


def region_out(r: Region, city_count: int | None = None) -> RegionOut:
    return RegionOut(
        id=r.id,
        country_id=r.country_id,
        country_code=r.country.code,
        country_name=r.country.name_de,
        code=r.code,
        name=r.display_name,
        local_name=r.name,
        kind=r.kind,
        parent_id=r.parent_id,
        city_count=city_count,
    )


def city_out(c: City) -> CityOut:
    return CityOut(
        id=c.id,
        name=c.display_name,
        local_name=c.name,
        country_id=c.country_id,
        country_code=c.country.code,
        country_name=c.country.name_de,
        region_id=c.region_id,
        region_name=c.region.display_name if c.region else None,
        population=c.population,
        latitude=c.latitude,
        longitude=c.longitude,
        timezone=c.timezone,
        is_auto=c.is_auto,
        needs_review=c.needs_review,
    )


def venue_out(v: Venue, *, upcoming: int | None = None, has_agenda: bool = False, favorite: bool = False) -> VenueOut:
    city = v.city
    return VenueOut(
        id=v.id,
        name=v.name,
        aliases=list(v.aliases or []),
        city_id=v.city_id,
        city_name=city.display_name if city else None,
        region_id=city.region_id if city else None,
        region_name=city.region.display_name if city and city.region else None,
        country_id=city.country_id if city else None,
        country_code=city.country.code if city else None,
        country_name=city.country.name_de if city else None,
        address=v.address,
        postal_code=v.postal_code,
        website=v.website,
        kind=v.kind,
        capacity=v.capacity,
        is_auto=v.is_auto,
        needs_review=v.needs_review,
        upcoming_event_count=upcoming,
        has_agenda_source=has_agenda,
        is_favorite=favorite,
    )


def search_cities(db: Session, q: str, *, country_id: int | None = None, region_id: int | None = None, limit: int = 20) -> list[City]:
    stmt = select(City)
    if country_id:
        stmt = stmt.where(City.country_id == country_id)
    if region_id:
        stmt = stmt.where(City.region_id == region_id)
    q = q.strip()
    if q:
        norm = normalize_name(q)
        variants = list(normalize_variants(q))
        pattern = escape_like(norm) + "%"
        stmt = stmt.where(
            or_(
                City.name_norm.like(pattern, escape="\\"),
                City.aliases_norm.overlap(variants),
                City.name_norm.like("%" + escape_like(norm) + "%", escape="\\") if len(norm) >= 4 else false(),
            )
        ).order_by(
            case(
                (or_(City.name_norm.in_(variants), City.aliases_norm.overlap(variants)), 0),
                (City.name_norm.like(pattern, escape="\\"), 1),
                else_=2,
            ),
            City.population.desc(),
        )
    else:
        stmt = stmt.order_by(City.population.desc())
    return list(db.execute(stmt.limit(limit)).unique().scalars())


def search_venues(db: Session, q: str, *, city_id: int | None = None, country_id: int | None = None, limit: int = 20) -> list[Venue]:
    stmt = select(Venue).outerjoin(City, Venue.city_id == City.id)
    if city_id:
        stmt = stmt.where(Venue.city_id == city_id)
    if country_id:
        stmt = stmt.where(City.country_id == country_id)
    q = q.strip()
    if q:
        norm = normalize_name(q)
        variants = list(normalize_variants(q))
        stmt = stmt.where(
            or_(
                Venue.name_norm.like("%" + escape_like(norm) + "%", escape="\\"),
                Venue.aliases_norm.overlap(variants),
                func.array_to_string(Venue.aliases_norm, " ").like("%" + escape_like(norm) + "%", escape="\\"),
            )
        ).order_by(
            case(
                (or_(Venue.name_norm == norm, Venue.aliases_norm.overlap(variants)), 0),
                (Venue.name_norm.like(escape_like(norm) + "%", escape="\\"), 1),
                else_=2,
            ),
            Venue.name,
        )
    else:
        stmt = stmt.order_by(Venue.name)
    return list(db.execute(stmt.limit(limit)).unique().scalars())


def search_regions(db: Session, q: str, *, country_id: int | None = None, limit: int = 20) -> list[Region]:
    stmt = select(Region)
    if country_id:
        stmt = stmt.where(Region.country_id == country_id)
    q = q.strip()
    if q:
        norm = normalize_name(q)
        variants = list(normalize_variants(q))
        stmt = stmt.where(
            or_(Region.name_norm.like("%" + escape_like(norm) + "%", escape="\\"), Region.aliases_norm.overlap(variants))
        )
    stmt = stmt.order_by(Region.name)
    return list(db.execute(stmt.limit(limit)).unique().scalars())


def venues_with_agenda(db: Session, venue_ids: list[int]) -> set[int]:
    if not venue_ids:
        return set()
    rows = db.execute(
        select(Source.venue_id).where(Source.venue_id.in_(venue_ids), Source.scope == "venue", Source.is_enabled.is_(True))
    ).all()
    return {r[0] for r in rows}


LEVEL_DESCRIPTIONS = {
    "country": "ganzes Land",
    "region": "komplette Region inkl. aller Städte und Veranstaltungsorte",
    "city": "alle Veranstaltungsorte dieser Stadt",
    "venue": "nur dieser Veranstaltungsort",
}


def rule_out(rule: LocationRule, context: str | None, country_code: str | None) -> LocationRuleOut:
    level, row_id = rule.level, rule.id // 10
    return LocationRuleOut(
        key=f"{level}:{row_id}",
        level=level,  # type: ignore[arg-type]
        target_id=rule.target_id,
        label=rule.label,
        context=context,
        country_code=country_code,
        country_name=rule.country_label,
        description=LEVEL_DESCRIPTIONS[level],
    )
