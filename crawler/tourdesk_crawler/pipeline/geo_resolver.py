"""Resolve raw location strings to catalogue entries (country → region → city → venue)."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tourdesk.core.text import normalize_name, normalize_variants
from tourdesk.models import City, Country, Festival, Region, Venue
from tourdesk.seed.loader import default_timezone

_POSTAL_PREFIX = re.compile(r"^(?:[A-Z]{1,2}[-\s])?\d{4,5}\s+")
_CITY_SUFFIX = re.compile(r"\s*\((?:[A-Z]{2}|[A-Za-zäöüÄÖÜ\s.-]{2,30})\)\s*$")


@dataclass
class ResolvedLocation:
    venue: Venue | None = None
    city: City | None = None
    region_id: int | None = None
    country: Country | None = None
    venue_name: str | None = None
    city_name: str | None = None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(max(0.0, a)))


def clean_city_name(raw: str) -> str:
    value = raw.strip()
    value = _POSTAL_PREFIX.sub("", value)
    value = _CITY_SUFFIX.sub("", value)
    return value.strip(" ,;-")


class GeoResolver:
    def __init__(
        self,
        db: Session,
        *,
        geocode: Callable[[str, str | None], dict | None] | None = None,
        create: bool = True,
    ) -> None:
        self.db = db
        self.geocode = geocode
        self.create = create
        self._countries: dict[str, Country | None] = {}
        self._regions: dict[tuple[int, str], int | None] = {}
        self._cities: dict[tuple, City | None] = {}
        self._city_exists: dict[str, bool] = {}
        self._country_by_id: dict[int, Country] = {}

    # ------------------------------------------------------------------ countries
    def country(self, value: str | None) -> Country | None:
        if not value:
            return None
        key = normalize_name(value)
        if not key:
            return None
        if key in self._countries:
            return self._countries[key]
        variants = list(normalize_variants(value))
        stmt = select(Country).where(or_(Country.name_norm.in_(variants), Country.aliases_norm.overlap(variants)))
        found = self.db.execute(stmt.order_by(Country.priority)).scalars().first()
        self._countries[key] = found
        return found

    def country_by_id(self, country_id: int) -> Country | None:
        if country_id not in self._country_by_id:
            c = self.db.get(Country, country_id)
            if c is not None:
                self._country_by_id[country_id] = c
        return self._country_by_id.get(country_id)

    def is_country(self, value: str) -> bool:
        return len(value) <= 40 and self.country(value) is not None

    # ------------------------------------------------------------------ regions
    def region_id(self, value: str | None, country_id: int | None) -> int | None:
        if not value or country_id is None:
            return None
        key = (country_id, normalize_name(value))
        if key in self._regions:
            return self._regions[key]
        variants = list(normalize_variants(value))
        code_like = value.strip().upper()
        stmt = select(Region.id).where(
            Region.country_id == country_id,
            or_(Region.name_norm.in_(variants), Region.aliases_norm.overlap(variants), Region.code == code_like),
        )
        rid = self.db.execute(stmt).scalars().first()
        self._regions[key] = rid
        return rid

    # ------------------------------------------------------------------ cities
    def is_city(self, value: str) -> bool:
        """Cheap check used by the text heuristics: is this string a known city name?"""
        value = clean_city_name(value)
        if not (2 <= len(value) <= 60) or any(ch.isdigit() for ch in value):
            return False
        key = normalize_name(value)
        if key in self._city_exists:
            return self._city_exists[key]
        variants = list(normalize_variants(value))
        exists = self.db.execute(
            select(City.id).where(or_(City.name_norm.in_(variants), City.aliases_norm.overlap(variants)), City.population >= 1000).limit(1)
        ).first() is not None
        self._city_exists[key] = exists
        return exists

    def city(
        self,
        raw: str | None,
        *,
        country_id: int | None = None,
        region_id: int | None = None,
        lat: float | None = None,
        lon: float | None = None,
    ) -> City | None:
        if not raw:
            return None
        name = clean_city_name(raw)
        # "Esch-sur-Alzette, Luxembourg" -> city + country hint
        if "," in name:
            first, *rest = [p.strip() for p in name.split(",") if p.strip()]
            if rest and country_id is None:
                c = self.country(rest[-1])
                if c is not None:
                    country_id = c.id
            name = first
        if not name or len(name) > 160:
            return None
        key = (normalize_name(name), country_id, region_id, round(lat, 2) if lat else None, round(lon, 2) if lon else None)
        if key in self._cities:
            return self._cities[key]
        variants = list(normalize_variants(name))
        stmt = select(City).where(or_(City.name_norm.in_(variants), City.aliases_norm.overlap(variants)))
        if country_id is not None:
            stmt = stmt.where(City.country_id == country_id)
        candidates = list(self.db.execute(stmt.limit(50)).unique().scalars())
        city: City | None = None
        if candidates:
            if region_id is not None:
                in_region = [c for c in candidates if c.region_id == region_id]
                candidates = in_region or candidates
            if lat is not None and lon is not None:
                with_coords = [c for c in candidates if c.latitude is not None and c.longitude is not None]
                if with_coords:
                    nearest = min(with_coords, key=lambda c: _distance_km(lat, lon, c.latitude, c.longitude))
                    if _distance_km(lat, lon, nearest.latitude, nearest.longitude) <= 60:
                        city = nearest
            if city is None:
                primary = [c for c in candidates if c.name_norm in variants]
                pool = primary or candidates
                city = max(pool, key=lambda c: c.population)
        elif country_id is not None and self.create:
            city = self._create_city(name, country_id, region_id, lat, lon)
        self._cities[key] = city
        return city

    def _create_city(self, name: str, country_id: int, region_id: int | None, lat: float | None, lon: float | None) -> City:
        country = self.country_by_id(country_id)
        if region_id is None and self.geocode is not None:
            info = self.geocode(name, country.code if country else None)
            if info:
                lat = lat if lat is not None else info.get("lat")
                lon = lon if lon is not None else info.get("lon")
                for candidate in (info.get("state"), info.get("county")):
                    region_id = self.region_id(candidate, country_id) if candidate else None
                    if region_id:
                        break
        city = City(
            country_id=country_id,
            region_id=region_id,
            name=name,
            name_norm=normalize_name(name),
            aliases=[],
            aliases_norm=sorted(normalize_variants(name)),
            latitude=lat,
            longitude=lon,
            population=0,
            timezone=default_timezone(self.db, country_id),
            is_auto=True,
            needs_review=region_id is None,
        )
        self.db.add(city)
        self.db.flush()
        return city

    # ------------------------------------------------------------------ venues
    def venue(
        self,
        raw: str | None,
        city: City | None,
        *,
        lat: float | None = None,
        lon: float | None = None,
        address: str | None = None,
        postal_code: str | None = None,
    ) -> Venue | None:
        if not raw:
            return None
        name = raw.strip()
        if len(name) < 2 or len(name) > 200:
            return None
        norm = normalize_name(name)
        variants = list(normalize_variants(name))
        if city is not None:
            candidates = list(self.db.execute(select(Venue).where(Venue.city_id == city.id)).unique().scalars())
        else:
            candidates = list(
                self.db.execute(
                    select(Venue).where(or_(Venue.name_norm.in_(variants), Venue.aliases_norm.overlap(variants))).limit(10)
                ).unique().scalars()
            )
            if len(candidates) > 1:
                return None  # ambiguous without a city
        best: Venue | None = None
        for v in candidates:
            names = {v.name_norm, *(v.aliases_norm or [])}
            if norm in names or names & set(variants):
                return v
        # "Rockhal Club" -> "Rockhal"; "Den Atelier Luxembourg" -> "den Atelier"
        for v in candidates:
            for known in {v.name_norm, *(v.aliases_norm or [])}:
                if len(known) >= 4 and (norm.startswith(known + " ") or known.startswith(norm + " ")):
                    return v
        score = 0.0
        for v in candidates:
            s = max(fuzz.token_set_ratio(norm, k) for k in {v.name_norm, *(v.aliases_norm or [])})
            if s > score:
                best, score = v, s
        if best is not None and score >= 90:
            return best
        if lat is not None and lon is not None:
            for v in candidates:
                if v.latitude is not None and v.longitude is not None and _distance_km(lat, lon, v.latitude, v.longitude) <= 0.15:
                    return v
        if city is None or not self.create:
            return None
        venue = Venue(
            city_id=city.id,
            name=name,
            name_norm=norm,
            aliases=[],
            aliases_norm=sorted(variants),
            address=address[:300] if address else None,
            postal_code=postal_code[:20] if postal_code else None,
            latitude=lat,
            longitude=lon,
            is_auto=True,
        )
        self.db.add(venue)
        self.db.flush()
        return venue

    # ------------------------------------------------------------------ festivals
    def festival(self, raw: str | None, *, city: City | None = None, venue: Venue | None = None, create: bool = True) -> Festival | None:
        if not raw:
            return None
        name = re.sub(r"\s+(19|20)\d\d$", "", raw.strip())  # "Rock am Ring 2027" -> "Rock am Ring"
        variants = list(normalize_variants(name))
        found = self.db.execute(
            select(Festival).where(or_(Festival.name_norm.in_(variants), Festival.aliases_norm.overlap(variants)))
        ).unique().scalars().first()
        if found is not None or not create or not self.create:
            return found
        slug = _festival_slug(self.db, name)
        festival = Festival(
            name=name[:200], name_norm=normalize_name(name), slug=slug, aliases=[raw.strip()[:200]] if raw.strip() != name else [],
            aliases_norm=sorted(normalize_variants(raw)), city_id=city.id if city else None, venue_id=venue.id if venue else None,
            is_auto=True,
        )
        self.db.add(festival)
        self.db.flush()
        return festival

    # ------------------------------------------------------------------ all together
    def resolve(
        self,
        *,
        venue_name: str | None,
        city_name: str | None,
        region_name: str | None,
        country_value: str | None,
        lat: float | None = None,
        lon: float | None = None,
        address: str | None = None,
        postal_code: str | None = None,
    ) -> ResolvedLocation:
        country = self.country(country_value) if country_value else None
        region_id = self.region_id(region_name, country.id) if (region_name and country) else None
        city = self.city(city_name, country_id=country.id if country else None, region_id=region_id, lat=lat, lon=lon) if city_name else None
        venue = None
        if venue_name:
            venue = self.venue(venue_name, city, lat=lat, lon=lon, address=address, postal_code=postal_code)
            if venue is not None and city is None and venue.city_id:
                city = self.db.get(City, venue.city_id)
        if city is not None and country is None:
            country = self.country_by_id(city.country_id)
        if city is not None and city.region_id:
            region_id = city.region_id
        return ResolvedLocation(
            venue=venue,
            city=city,
            region_id=region_id,
            country=country,
            venue_name=venue.name if venue else venue_name,
            city_name=city.display_name if city else city_name,
        )


def _festival_slug(db: Session, name: str) -> str:
    from tourdesk.core.text import slugify

    base = slugify(name, max_length=100)
    slug, n = base, 2
    while db.execute(select(Festival.id).where(Festival.slug == slug)).first():
        slug = f"{base}-{n}"
        n += 1
    return slug
