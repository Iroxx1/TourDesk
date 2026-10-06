"""/api/filters – personal filter profile and hierarchical location rules."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tourdesk.core.db import get_db
from tourdesk.models import City, Country, Region, UserCity, UserCountry, UserFilter, UserRegion, UserVenue, Venue
from tourdesk.schemas.geo import FilterOut, FilterUpdate, LocationRuleCreate, LocationRuleOut
from tourdesk.security.deps import AuthContext, get_context
from tourdesk.services.filters import get_default_filter, location_rules
from tourdesk.services.geo import rule_out

router = APIRouter(prefix="/filters", tags=["filters"])

_RULE_MODELS = {"country": UserCountry, "region": UserRegion, "city": UserCity, "venue": UserVenue}


def locations_out(db: Session, f: UserFilter) -> list[LocationRuleOut]:
    db.refresh(f)
    out: list[LocationRuleOut] = []
    by_key = {}
    for c in f.countries:
        by_key[("country", c.id)] = (None, c.country.code)
    for r in f.regions:
        by_key[("region", r.id)] = (r.region.country.name_de, r.region.country.code)
    for c in f.cities:
        city = c.city
        ctx = ", ".join(p for p in (city.region.display_name if city.region else None, city.country.name_de) if p)
        by_key[("city", c.id)] = (ctx, city.country.code)
    for v in f.venues:
        venue = v.venue
        city = venue.city
        ctx = ", ".join(p for p in (city.display_name if city else None, city.country.name_de if city else None) if p) or None
        by_key[("venue", v.id)] = (ctx, city.country.code if city else None)
    for rule in location_rules(f):
        context, code = by_key.get((rule.level, rule.id // 10), (None, None))
        out.append(rule_out(rule, context, code))
    order = {"country": 0, "region": 1, "city": 2, "venue": 3}
    out.sort(key=lambda r: (r.country_name or "", order[r.level], r.label))
    return out


def filter_out(db: Session, f: UserFilter) -> FilterOut:
    return FilterOut(
        id=f.id,
        name=f.name,
        date_mode=f.date_mode,  # type: ignore[arg-type]
        months_ahead=f.months_ahead,
        date_from=f.date_from,
        date_to=f.date_to,
        include_concerts=f.include_concerts,
        include_support=f.include_support,
        include_special=f.include_special,
        festival_mode=f.festival_mode,  # type: ignore[arg-type]
        festival_scope=f.festival_scope,  # type: ignore[arg-type]
        show_cancelled=f.show_cancelled,
        show_unconfirmed=f.show_unconfirmed,
        default_show_festivals=f.default_show_festivals,
        locations=locations_out(db, f),
    )


@router.get("", response_model=FilterOut)
def get_filter(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> FilterOut:
    f = get_default_filter(db, ctx.user.id)
    db.commit()
    return filter_out(db, f)


@router.put("", response_model=FilterOut)
def update_filter(payload: FilterUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> FilterOut:
    f = get_default_filter(db, ctx.user.id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key in ("months_ahead", "date_from", "date_to"):
            setattr(f, key, value)
        elif value is not None:
            setattr(f, key, value)
    if f.date_mode == "months" and not f.months_ahead:
        f.months_ahead = 12
    db.commit()
    return filter_out(db, f)


@router.get("/locations", response_model=list[LocationRuleOut])
def list_locations(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> list[LocationRuleOut]:
    return locations_out(db, get_default_filter(db, ctx.user.id))


@router.post("/locations", response_model=list[LocationRuleOut], status_code=status.HTTP_201_CREATED)
def add_location(
    payload: LocationRuleCreate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> list[LocationRuleOut]:
    target_model = {"country": Country, "region": Region, "city": City, "venue": Venue}[payload.level]
    if db.get(target_model, payload.target_id) is None:
        raise HTTPException(404, "Ziel nicht gefunden")
    f = get_default_filter(db, ctx.user.id)
    model = _RULE_MODELS[payload.level]
    column = getattr(model, f"{payload.level}_id")
    exists = db.execute(select(model.id).where(model.filter_id == f.id, column == payload.target_id)).first()
    if not exists:
        db.add(model(user_id=ctx.user.id, filter_id=f.id, **{f"{payload.level}_id": payload.target_id}))
        db.commit()
    return locations_out(db, f)


@router.delete("/locations/{key}", response_model=list[LocationRuleOut])
def delete_location(key: str, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> list[LocationRuleOut]:
    try:
        level, raw_id = key.split(":", 1)
        row_id = int(raw_id)
        model = _RULE_MODELS[level]
    except (ValueError, KeyError):
        raise HTTPException(404, "Regel nicht gefunden") from None
    row = db.get(model, row_id)
    if row is None or row.user_id != ctx.user.id:
        raise HTTPException(404, "Regel nicht gefunden")
    db.delete(row)
    db.commit()
    return locations_out(db, get_default_filter(db, ctx.user.id))
