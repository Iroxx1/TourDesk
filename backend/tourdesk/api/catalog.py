"""/api/catalog – Künstlerkatalog zum Blättern (Genre, Herkunft, Register A–Z)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from tourdesk.core.config import get_settings
from tourdesk.core.db import get_db
from tourdesk.models import CatalogEntry
from tourdesk.schemas.catalog import CatalogDetailOut, CatalogMetaOut, CatalogPageOut
from tourdesk.security.deps import AuthContext, get_context
from tourdesk.services import catalog
from tourdesk.services.app_settings import crawler_settings
from tourdesk.services.catalog_genres import GENRES_BY_KEY, ORIGINS

router = APIRouter(prefix="/catalog", tags=["catalog"])

MBID = Path(..., pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _user_agent(db: Session) -> str:
    settings = crawler_settings(db)
    return settings["user_agent"] + (f" ({settings['contact']})" if settings.get("contact") else "")


def _images_enabled(db: Session) -> bool:
    return get_settings().catalog_images and "deezer" in (crawler_settings(db).get("image_providers") or [])


def _entry(db: Session, mbid: str) -> CatalogEntry:
    entry = db.get(CatalogEntry, mbid)
    if entry is None:
        raise HTTPException(404, "Nicht im Katalog")
    return entry


@router.get("/meta", response_model=CatalogMetaOut)
def meta(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> dict:
    out = catalog.catalog_meta(db)
    if not _images_enabled(db):
        out["images"]["pending"] = 0  # es wird nichts gesammelt – keinen Fortschritt anzeigen
    return out


@router.get("/pages", response_model=CatalogPageOut)
def pages(
    genre: str | None = Query(None, max_length=32),
    origin: str = Query("all", max_length=8),
    page: int = Query(0, ge=0, le=100_000),
    per_page: int = Query(12, ge=4, le=48),
    ctx: AuthContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> dict:
    if genre and genre not in GENRES_BY_KEY:
        raise HTTPException(422, "Unbekanntes Genre")
    if origin not in ORIGINS:
        raise HTTPException(422, "Unbekannte Herkunft")
    images = _user_agent(db) if _images_enabled(db) else None
    return catalog.catalog_page(db, ctx.user.id, genre=genre or None, origin=origin, page=page, per_page=per_page, images=images)


@router.get("/entries/{mbid}", response_model=CatalogDetailOut)
def detail(mbid: str = MBID, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> dict:
    entry = _entry(db, mbid)
    user_id = ctx.user.id
    if crawler_settings(db).get("musicbrainz_lookup", True):
        entry, details = catalog.ensure_details(db, entry, _user_agent(db))
    else:
        details = entry.details or {}
    return catalog.detail_out(db, entry, user_id, details, images=_images_enabled(db))


@router.get("/entries/{mbid}/image")
def image(mbid: str = MBID, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> FileResponse:
    """Serves an already fetched picture (the search runs in the background, see ``catalog_page``)."""
    entry = _entry(db, mbid)
    file = catalog.entry_image_file(entry.mbid)
    if entry.image_status != "ok" or not file.is_file():
        raise HTTPException(404, "Kein Bild")
    return FileResponse(file, media_type="image/webp", headers={"Cache-Control": "private, max-age=604800"})
