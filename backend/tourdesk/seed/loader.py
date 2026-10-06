"""Idempotent seed loader for geographic data, venues and festivals.

Seed files live in ``database/seed``. A checksum of all seed files is stored in
``app_settings['seed_version']`` so repeated starts are fast.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tourdesk.core.config import get_settings
from tourdesk.core.text import normalize_name, normalize_variants, slugify
from tourdesk.models import AppSetting, City, Country, Festival, Region, Role, Source, Venue

log = logging.getLogger("tourdesk.seed")

ROLES = [
    {"key": "user", "name": "Benutzer", "description": "Verwaltet eigene Künstler, Filter und Einstellungen", "permissions": []},
    {"key": "admin", "name": "Administrator", "description": "Vollzugriff auf Benutzer, Crawler und System", "permissions": ["*"]},
]


def _variants(*names: Iterable[str] | str | None) -> list[str]:
    out: set[str] = set()
    for item in names:
        if not item:
            continue
        if isinstance(item, str):
            out |= normalize_variants(item)
        else:
            for name in item:
                out |= normalize_variants(name)
    return sorted(out)


def _checksum(seed_dir: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(seed_dir.rglob("*")):
        if path.is_file():
            h.update(path.name.encode())
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


def ensure_roles(session: Session) -> None:
    for role in ROLES:
        if session.get(Role, role["key"]) is None:
            session.add(Role(**role))
    session.flush()


def seed_countries(session: Session, seed_dir: Path) -> dict[str, int]:
    data = json.loads((seed_dir / "geo" / "countries.json").read_text(encoding="utf-8"))
    rows = []
    for c in data:
        rows.append(
            {
                "code": c["code"],
                "code3": c.get("code3"),
                "name_de": c["name_de"],
                "name_en": c["name_en"],
                "name_norm": normalize_name(c["name_de"]),
                "aliases": c.get("aliases", []),
                "aliases_norm": _variants(c["name_de"], c["name_en"], c.get("aliases", []), c["code"], c.get("code3")),
                "continent": c.get("continent"),
                "priority": c.get("priority", 100),
            }
        )
    stmt = pg_insert(Country).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["code"],
        set_={k: stmt.excluded[k] for k in ("code3", "name_de", "name_en", "name_norm", "aliases", "aliases_norm", "continent", "priority")},
    )
    session.execute(stmt)
    return {code: cid for code, cid in session.execute(select(Country.code, Country.id))}


def seed_regions(session: Session, seed_dir: Path, countries: dict[str, int]) -> dict[str, int]:
    data = json.loads((seed_dir / "geo" / "regions.json").read_text(encoding="utf-8"))
    rows = []
    for r in data:
        if r["country"] not in countries:
            continue
        rows.append(
            {
                "country_id": countries[r["country"]],
                "code": r["code"],
                "geonames_code": r.get("geonames"),
                "name": r["name"],
                "name_de": r.get("name_de"),
                "name_norm": normalize_name(r["name"]),
                "kind": r.get("kind", "Region"),
                "aliases": r.get("aliases", []),
                "aliases_norm": _variants(r["name"], r.get("name_de"), r.get("aliases", [])),
                "is_auto": False,
            }
        )
    stmt = pg_insert(Region).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["code"],
        set_={k: stmt.excluded[k] for k in ("geonames_code", "name", "name_de", "name_norm", "kind", "aliases", "aliases_norm")},
    )
    session.execute(stmt)
    return {code: rid for code, rid in session.execute(select(Region.code, Region.id).where(Region.code.is_not(None)))}


def seed_cities(session: Session, seed_dir: Path, countries: dict[str, int], regions: dict[str, int]) -> int:
    path = seed_dir / "geo" / "cities.jsonl.gz"
    batch: list[dict[str, Any]] = []
    total = 0

    def flush() -> None:
        nonlocal batch
        if not batch:
            return
        stmt = pg_insert(City).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["geonames_id"],
            set_={
                "name": stmt.excluded.name,
                "name_de": stmt.excluded.name_de,
                "name_norm": stmt.excluded.name_norm,
                "aliases": stmt.excluded.aliases,
                "aliases_norm": stmt.excluded.aliases_norm,
                "latitude": stmt.excluded.latitude,
                "longitude": stmt.excluded.longitude,
                "population": stmt.excluded.population,
                "timezone": stmt.excluded.timezone,
                "region_id": func.coalesce(City.region_id, stmt.excluded.region_id),
            },
        )
        session.execute(stmt)
        batch = []

    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            c = json.loads(line)
            country_id = countries.get(c["cc"])
            if country_id is None:
                continue
            aliases = list(c.get("a") or [])
            if c.get("de") and c["de"] not in aliases:
                aliases.insert(0, c["de"])
            batch.append(
                {
                    "country_id": country_id,
                    "region_id": regions.get(c["r"]) if c.get("r") else None,
                    "name": c["n"],
                    "name_de": c.get("de"),
                    "name_norm": normalize_name(c["n"]),
                    "aliases": aliases,
                    "aliases_norm": _variants(c["n"], aliases),
                    "latitude": c.get("lat"),
                    "longitude": c.get("lon"),
                    "population": c.get("p") or 0,
                    "timezone": c.get("tz"),
                    "geonames_id": c["gid"],
                    "is_auto": False,
                    "needs_review": False,
                }
            )
            total += 1
            if len(batch) >= 2000:
                flush()
    flush()
    return total


def find_city(session: Session, name: str, country_id: int, region_id: int | None = None) -> City | None:
    variants = list(normalize_variants(name))
    if not variants:
        return None
    stmt = select(City).where(
        City.country_id == country_id,
        or_(City.name_norm.in_(variants), City.aliases_norm.overlap(variants)),
    )
    if region_id is not None:
        stmt = stmt.where(or_(City.region_id == region_id, City.region_id.is_(None)))
    # prefer primary-name matches, then population
    stmt = stmt.order_by(City.name_norm.in_(variants).desc(), City.population.desc()).limit(1)
    return session.execute(stmt).unique().scalars().first()


def default_timezone(session: Session, country_id: int) -> str | None:
    return session.execute(
        select(City.timezone)
        .where(City.country_id == country_id, City.timezone.is_not(None))
        .order_by(City.population.desc())
        .limit(1)
    ).scalar()


def get_or_create_city(
    session: Session, name: str, country_id: int, region_id: int | None = None, *, auto: bool = True
) -> City:
    city = find_city(session, name, country_id, region_id)
    if city:
        if city.region_id is None and region_id is not None:
            city.region_id = region_id
        return city
    city = City(
        country_id=country_id,
        region_id=region_id,
        name=name,
        name_norm=normalize_name(name),
        aliases=[],
        aliases_norm=_variants(name),
        population=0,
        timezone=default_timezone(session, country_id),
        is_auto=auto,
        needs_review=auto and region_id is None,
    )
    session.add(city)
    session.flush()
    return city


def seed_venues(session: Session, seed_dir: Path, countries: dict[str, int], regions: dict[str, int]) -> int:
    data = json.loads((seed_dir / "venues.json").read_text(encoding="utf-8"))
    count = 0
    for v in data:
        country_id = countries.get(v["country"])
        if country_id is None:
            continue
        region_id = regions.get(v.get("region")) if v.get("region") else None
        city = get_or_create_city(session, v["city"], country_id, region_id)
        name_norm = normalize_name(v["name"])
        venue = session.execute(
            select(Venue).where(Venue.city_id == city.id, Venue.name_norm == name_norm)
        ).unique().scalar_one_or_none()
        aliases = v.get("aliases", [])
        if venue is None:
            venue = Venue(city_id=city.id, name=v["name"], name_norm=name_norm, aliases=[], aliases_norm=[])
            session.add(venue)
        merged_aliases = list(dict.fromkeys([*(venue.aliases or []), *aliases]))
        venue.aliases = merged_aliases
        venue.aliases_norm = _variants(v["name"], merged_aliases)
        for field in ("address", "postal_code", "website", "kind", "capacity"):
            if v.get(field) and not getattr(venue, field):
                setattr(venue, field, v[field])
        venue.is_auto = False
        session.flush()
        if venue.website:
            _ensure_source(
                session,
                scope="venue",
                provider="venue_website",
                url=venue.website,
                name=f"{venue.name} – Programm",
                trust_level=2,
                venue_id=venue.id,
            )
        count += 1
    return count


def seed_festivals(session: Session, seed_dir: Path, countries: dict[str, int], regions: dict[str, int]) -> int:
    data = json.loads((seed_dir / "festivals.json").read_text(encoding="utf-8"))
    count = 0
    for f in data:
        country_id = countries.get(f["country"])
        if country_id is None:
            continue
        region_id = regions.get(f.get("region")) if f.get("region") else None
        city = get_or_create_city(session, f["city"], country_id, region_id)
        venue_id = None
        if f.get("venue"):
            venue_id = session.execute(
                select(Venue.id).where(Venue.city_id == city.id, Venue.name_norm == normalize_name(f["venue"]))
            ).scalar()
        slug = slugify(f["name"])
        festival = session.execute(select(Festival).where(Festival.slug == slug)).unique().scalar_one_or_none()
        if festival is None:
            festival = Festival(name=f["name"], name_norm=normalize_name(f["name"]), slug=slug, aliases=[], aliases_norm=[])
            session.add(festival)
        aliases = list(dict.fromkeys([*(festival.aliases or []), *f.get("aliases", [])]))
        festival.aliases = aliases
        festival.aliases_norm = _variants(f["name"], aliases)
        festival.city_id = festival.city_id or city.id
        festival.venue_id = festival.venue_id or venue_id
        festival.website = festival.website or f.get("website")
        festival.typical_month = festival.typical_month or f.get("month")
        session.flush()
        if festival.website:
            _ensure_source(
                session,
                scope="festival",
                provider="festival_lineup",
                url=festival.website,
                name=f"{festival.name} – Line-up",
                trust_level=3,
                festival_id=festival.id,
            )
        count += 1
    return count


def _ensure_source(session: Session, *, scope: str, provider: str, url: str, name: str, trust_level: int, **fks: int) -> None:
    stmt = select(Source).where(Source.scope == scope, Source.provider == provider)
    for key, value in fks.items():
        stmt = stmt.where(getattr(Source, key) == value)
    if session.execute(stmt).scalars().first() is not None:
        return
    session.add(
        Source(
            scope=scope,
            provider=provider,
            url=url,
            name=name,
            trust_level=trust_level,
            is_enabled=True,
            is_auto=True,
            # crawled only when relevant for at least one user (see scheduler)
            config={"auto_relevance": True, "discover": True},
            **fks,
        )
    )


def seed_all(session: Session, *, force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    seed_dir = settings.seed_dir
    ensure_roles(session)
    checksum = _checksum(seed_dir)
    current = session.get(AppSetting, "seed_version")
    if current is not None and current.value.get("checksum") == checksum and not force:
        return {"skipped": True, "checksum": checksum}

    log.info("loading seed data", extra={"event": "seed.start"})
    countries = seed_countries(session, seed_dir)
    regions = seed_regions(session, seed_dir, countries)
    cities = seed_cities(session, seed_dir, countries, regions)
    session.flush()
    venues = seed_venues(session, seed_dir, countries, regions)
    festivals = seed_festivals(session, seed_dir, countries, regions)

    if current is None:
        session.add(AppSetting(key="seed_version", value={"checksum": checksum}))
    else:
        current.value = {"checksum": checksum}
    session.flush()
    result = {
        "skipped": False,
        "checksum": checksum,
        "countries": len(countries),
        "regions": len(regions),
        "cities": cities,
        "venues": venues,
        "festivals": festivals,
    }
    log.info("seed data loaded", extra={"event": "seed.done", **result})
    return result
