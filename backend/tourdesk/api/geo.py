"""/api/countries, /api/regions, /api/cities – geographic catalogue."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tourdesk.core.db import get_db
from tourdesk.core.text import normalize_name, normalize_variants
from tourdesk.models import City, Country, Region
from tourdesk.schemas.geo import CityCreate, CityOut, CityUpdate, CountryOut, RegionOut
from tourdesk.security.deps import AuthContext, get_context
from tourdesk.seed.loader import default_timezone, find_city
from tourdesk.services import audit
from tourdesk.services.geo import city_out, country_out, region_out, search_cities, search_regions

router = APIRouter(tags=["geo"])


@router.get("/countries", response_model=list[CountryOut])
def list_countries(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> list[CountryOut]:
    counts = dict(db.execute(select(Region.country_id, func.count(Region.id)).group_by(Region.country_id)).all())
    countries = db.execute(select(Country).order_by(Country.priority, Country.name_de)).scalars().all()
    return [country_out(c, counts.get(c.id, 0)) for c in countries]


@router.get("/regions", response_model=list[RegionOut])
def list_regions(
    country_id: int | None = None,
    q: str = Query("", max_length=100),
    ctx: AuthContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> list[RegionOut]:
    if q:
        return [region_out(r) for r in search_regions(db, q, country_id=country_id, limit=50)]
    stmt = select(Region)
    if country_id:
        stmt = stmt.where(Region.country_id == country_id)
    regions = db.execute(stmt.order_by(Region.name_de, Region.name)).unique().scalars().all()
    counts = dict(
        db.execute(
            select(City.region_id, func.count(City.id)).where(City.region_id.in_([r.id for r in regions])).group_by(City.region_id)
        ).all()
    ) if regions else {}
    return [region_out(r, counts.get(r.id, 0)) for r in regions]


@router.get("/regions/{region_id}", response_model=RegionOut)
def get_region(region_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> RegionOut:
    region = db.get(Region, region_id)
    if region is None:
        raise HTTPException(404, "Region nicht gefunden")
    count = db.execute(select(func.count(City.id)).where(City.region_id == region_id)).scalar_one()
    return region_out(region, count)


@router.get("/cities", response_model=list[CityOut])
def list_cities(
    q: str = Query("", max_length=100),
    country_id: int | None = None,
    region_id: int | None = None,
    limit: int = Query(30, ge=1, le=200),
    ctx: AuthContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> list[CityOut]:
    return [city_out(c) for c in search_cities(db, q, country_id=country_id, region_id=region_id, limit=limit)]


@router.get("/cities/{city_id}", response_model=CityOut)
def get_city(city_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> CityOut:
    city = db.get(City, city_id)
    if city is None:
        raise HTTPException(404, "Stadt nicht gefunden")
    return city_out(city)


@router.post("/cities", response_model=CityOut, status_code=status.HTTP_201_CREATED)
def create_city(
    payload: CityCreate, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> CityOut:
    country = db.get(Country, payload.country_id)
    if country is None:
        raise HTTPException(422, "Unbekanntes Land")
    if payload.region_id is not None:
        region = db.get(Region, payload.region_id)
        if region is None or region.country_id != country.id:
            raise HTTPException(422, "Die Region gehört nicht zum gewählten Land")
    existing = find_city(db, payload.name, country.id, payload.region_id)
    if existing is not None and normalize_name(existing.name) == normalize_name(payload.name):
        return city_out(existing)
    city = City(
        country_id=country.id,
        region_id=payload.region_id,
        name=payload.name.strip(),
        name_norm=normalize_name(payload.name),
        aliases=[],
        aliases_norm=sorted(normalize_variants(payload.name)),
        population=0,
        timezone=default_timezone(db, country.id),
        is_auto=False,
        needs_review=payload.region_id is None,
    )
    db.add(city)
    db.flush()
    audit.record(db, "geo.city_create", actor=ctx.actor, request=request, target_type="city", target_id=city.id, target_label=city.name)
    db.commit()
    return city_out(city)


@router.patch("/cities/{city_id}", response_model=CityOut)
def update_city(
    city_id: int, payload: CityUpdate, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> CityOut:
    if not ctx.is_admin:
        raise HTTPException(403, "Nur Administratoren können Städte bearbeiten")
    city = db.get(City, city_id)
    if city is None:
        raise HTTPException(404, "Stadt nicht gefunden")
    data = payload.model_dump(exclude_unset=True)
    if "region_id" in data:
        if data["region_id"] is not None:
            region = db.get(Region, data["region_id"])
            if region is None or region.country_id != city.country_id:
                raise HTTPException(422, "Die Region gehört nicht zum Land der Stadt")
        city.region_id = data["region_id"]
        # keep denormalised event locations consistent
        from tourdesk.services.events import refresh_event_regions_for_city

        refresh_event_regions_for_city(db, city)
        city.needs_review = False
    if data.get("name"):
        city.name = data["name"].strip()
        city.name_norm = normalize_name(city.name)
        city.aliases_norm = sorted(set(city.aliases_norm or []) | normalize_variants(city.name))
    if data.get("needs_review") is not None:
        city.needs_review = data["needs_review"]
    audit.record(db, "geo.city_update", actor=ctx.actor, request=request, target_type="city", target_id=city.id,
                 target_label=city.name, details={k: str(v) for k, v in data.items()})
    db.commit()
    return city_out(city)
