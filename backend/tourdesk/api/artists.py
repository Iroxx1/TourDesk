"""/api/artists – the user's artists (catalogue entries + personal subscription)."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tourdesk.core.db import get_db
from tourdesk.core.text import normalize_name
from tourdesk.core.timeutil import utcnow
from tourdesk.models import Artist, EventSource, Event, Source, UserArtist
from tourdesk.schemas.artists import (
    ArtistCreate,
    ArtistEventsOut,
    ArtistLookupItem,
    ArtistOut,
    ArtistUpdate,
    SourceCreate,
    SourceOut,
)
from tourdesk.schemas.common import OkResponse
from tourdesk.security.deps import AuthContext, get_context
from tourdesk.security.netsafety import UnsafeURLError, assert_public_url
from tourdesk.services import audit, musicbrainz
from tourdesk.services.app_settings import crawler_settings
from tourdesk.services.artists import (
    artist_out,
    create_catalog_artist,
    ensure_website_source,
    find_catalog_artist,
    follow_artist,
    schedule_initial_jobs,
    search_catalog,
    set_aliases,
    source_out,
    user_addable_providers,
)
from tourdesk.services.dashboard import build_artist_events
from tourdesk.services.filters import get_default_filter
from tourdesk.services.jobs import PRIORITY_MANUAL, enqueue_job, last_manual_request
from tourdesk.services.media import (
    MAX_UPLOAD_BYTES,
    ImageError,
    save_artist_image,
    save_fallback_artist_image,
)

router = APIRouter(prefix="/artists", tags=["artists"])

REFRESH_COOLDOWN = timedelta(minutes=5)


def _subscription(db: Session, ctx: AuthContext, artist_id: int) -> UserArtist:
    ua = db.execute(
        select(UserArtist).where(UserArtist.user_id == ctx.user.id, UserArtist.artist_id == artist_id)
    ).unique().scalar_one_or_none()
    if ua is None:
        raise HTTPException(404, "Künstler nicht gefunden")
    return ua


@router.get("", response_model=list[ArtistOut])
def list_artists(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> list[ArtistOut]:
    subs = db.execute(
        select(UserArtist).where(UserArtist.user_id == ctx.user.id).order_by(UserArtist.sort_order, UserArtist.id)
    ).unique().scalars().all()
    return [artist_out(ua.artist, ua) for ua in subs]


@router.get("/lookup", response_model=list[ArtistLookupItem])
def lookup(
    q: str = Query(..., min_length=1, max_length=100),
    external: bool = True,
    ctx: AuthContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> list[ArtistLookupItem]:
    followed = {
        r[0] for r in db.execute(select(UserArtist.artist_id).where(UserArtist.user_id == ctx.user.id)).all()
    }
    items = [
        ArtistLookupItem(
            source="catalog", name=a.name, genre=a.genre, country=a.country_code, artist_id=a.id,
            musicbrainz_id=(a.external_ids or {}).get("musicbrainz"), followed=a.id in followed,
        )
        for a in search_catalog(db, q, limit=8)
    ]
    settings = crawler_settings(db)
    if external and settings.get("musicbrainz_lookup") and len(q.strip()) >= 2:
        known = {i.musicbrainz_id for i in items if i.musicbrainz_id}
        ua = settings["user_agent"] + (f" ({settings['contact']})" if settings.get("contact") else "")
        for hit in musicbrainz.search_artists(q, ua, limit=8):
            if hit["mbid"] in known:
                continue
            items.append(
                ArtistLookupItem(
                    source="musicbrainz", name=hit["name"], disambiguation=hit["disambiguation"], country=hit["country"],
                    kind=hit["type"], musicbrainz_id=hit["mbid"], genre=hit["genre"], score=hit["score"],
                )
            )
    return items[:16]


@router.post("", response_model=ArtistOut, status_code=status.HTTP_201_CREATED)
def add_artist(
    payload: ArtistCreate, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> ArtistOut:
    if payload.official_website:
        try:
            assert_public_url(payload.official_website, resolve=False)
        except UnsafeURLError as exc:
            raise HTTPException(422, f"Website: {exc}") from exc
    artist: Artist | None = None
    if payload.artist_id is not None:
        artist = db.get(Artist, payload.artist_id)
        if artist is None:
            raise HTTPException(404, "Künstler nicht gefunden")
    else:
        artist = find_catalog_artist(db, payload.name, payload.musicbrainz_id)
    created = artist is None
    if artist is None:
        artist = create_catalog_artist(
            db,
            name=payload.name,
            website=payload.official_website,
            genre=payload.genre,
            aliases=payload.aliases,
            search_terms=payload.search_terms,
            musicbrainz_id=payload.musicbrainz_id,
            created_by=ctx.actor,
        )
    else:
        # complete missing catalogue data with what the user entered
        if payload.official_website and not artist.official_website:
            artist.official_website = payload.official_website
            ensure_website_source(db, artist, created_by=ctx.actor.id)
        if payload.genre and not artist.genre:
            artist.genre = payload.genre
        if payload.musicbrainz_id and not (artist.external_ids or {}).get("musicbrainz"):
            artist.external_ids = {**(artist.external_ids or {}), "musicbrainz": payload.musicbrainz_id}
        if payload.search_terms:
            artist.search_terms = list(dict.fromkeys([*(artist.search_terms or []), *payload.search_terms]))
        if payload.aliases:
            from tourdesk.services.artists import add_aliases

            add_aliases(db, artist, payload.aliases, "user")
    show_festivals = payload.show_festivals
    if show_festivals is None:
        show_festivals = get_default_filter(db, ctx.user.id).default_show_festivals
    ua, new_subscription = follow_artist(db, ctx.user, artist, show_festivals=show_festivals)
    if not new_subscription and not created:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{artist.name} ist bereits in deiner Liste.")
    if created or artist.last_success_at is None:
        schedule_initial_jobs(db, artist, ctx.actor.id)
    audit.record(db, "artist.follow", actor=ctx.actor, request=request, target_type="artist", target_id=artist.id,
                 target_label=artist.name, details={"created": created})
    db.commit()
    return artist_out(artist, ua)


@router.post("/reorder", response_model=OkResponse)
def reorder(ids: list[int] = Body(..., embed=True), ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> OkResponse:
    subs = {
        ua.artist_id: ua
        for ua in db.execute(select(UserArtist).where(UserArtist.user_id == ctx.user.id)).unique().scalars()
    }
    for order, artist_id in enumerate(ids):
        if artist_id in subs:
            subs[artist_id].sort_order = order
    db.commit()
    return OkResponse()


@router.get("/{artist_id}", response_model=ArtistOut)
def get_artist(artist_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> ArtistOut:
    ua = _subscription(db, ctx, artist_id)
    return artist_out(ua.artist, ua)


@router.patch("/{artist_id}", response_model=ArtistOut)
def update_artist(
    artist_id: int, payload: ArtistUpdate, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> ArtistOut:
    ua = _subscription(db, ctx, artist_id)
    artist = ua.artist
    data = payload.model_dump(exclude_unset=True)
    recrawl = False
    for key in ("is_active", "show_festivals", "notify", "pinned", "sort_order"):
        if key in data and data[key] is not None:
            setattr(ua, key, data[key])
    catalog_changes: dict[str, str] = {}
    if data.get("name") and normalize_name(data["name"]) != artist.name_norm:
        catalog_changes["name"] = f"{artist.name} → {data['name']}"
        artist.name = " ".join(data["name"].split())
        artist.name_norm = normalize_name(artist.name)
        if artist.image_source == "fallback":
            artist.image_path = save_fallback_artist_image(artist.id, artist.name)
            artist.image_version += 1
        recrawl = True
    if "genre" in data:
        artist.genre = data["genre"]
    if "official_website" in data and data["official_website"] != artist.official_website:
        if data["official_website"]:
            try:
                assert_public_url(data["official_website"], resolve=False)
            except UnsafeURLError as exc:
                raise HTTPException(422, f"Website: {exc}") from exc
        catalog_changes["official_website"] = data["official_website"] or "entfernt"
        artist.official_website = data["official_website"]
        ensure_website_source(db, artist, created_by=ctx.actor.id)
        recrawl = True
    if data.get("aliases") is not None:
        set_aliases(db, artist, data["aliases"], "user")
        recrawl = True
    if data.get("search_terms") is not None:
        artist.search_terms = data["search_terms"]
        recrawl = True
    if catalog_changes:
        audit.record(db, "artist.update", actor=ctx.actor, request=request, target_type="artist", target_id=artist.id,
                     target_label=artist.name, details=catalog_changes)
    if recrawl:
        enqueue_job(db, "artist_crawl", artist_id=artist.id, priority=PRIORITY_MANUAL, reason="manual", requested_by=ctx.actor.id)
    db.commit()
    return artist_out(artist, ua)


@router.delete("/{artist_id}", response_model=OkResponse)
def unfollow(artist_id: int, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> OkResponse:
    ua = _subscription(db, ctx, artist_id)
    name = ua.artist.name
    db.delete(ua)
    audit.record(db, "artist.unfollow", actor=ctx.actor, request=request, target_type="artist", target_id=artist_id, target_label=name)
    db.commit()
    return OkResponse(detail=f"{name} wurde entfernt.")


@router.get("/{artist_id}/events", response_model=ArtistEventsOut)
def artist_events(artist_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> ArtistEventsOut:
    ua = _subscription(db, ctx, artist_id)
    return build_artist_events(db, ctx.user, ua, artist_id)


@router.get("/{artist_id}/sources")
def artist_sources(artist_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> dict:
    ua = _subscription(db, ctx, artist_id)
    own = db.execute(select(Source).where(Source.artist_id == artist_id).order_by(Source.trust_level, Source.id)).scalars().all()
    contributing = db.execute(
        select(Source)
        .join(EventSource, EventSource.source_id == Source.id)
        .join(Event, Event.id == EventSource.event_id)
        .where(Event.artist_id == artist_id, Source.artist_id.is_(None))
        .distinct()
    ).scalars().all()
    return {
        "artist": artist_out(ua.artist, ua).model_dump(mode="json"),
        "sources": [
            source_out(s, can_delete=(not s.is_auto) and (ctx.is_admin or s.created_by_user_id == ctx.actor.id)).model_dump(mode="json")
            for s in own
        ],
        "contributing": [source_out(s).model_dump(mode="json") for s in contributing],
        "addable_providers": user_addable_providers(),
    }


@router.post("/{artist_id}/sources", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def add_source(
    artist_id: int, payload: SourceCreate, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> SourceOut:
    ua = _subscription(db, ctx, artist_id)
    if payload.provider not in user_addable_providers():
        raise HTTPException(422, "Dieser Quellentyp kann nicht manuell angelegt werden")
    try:
        assert_public_url(payload.url or "", resolve=False)
    except UnsafeURLError as exc:
        raise HTTPException(422, str(exc)) from exc
    exists = db.execute(select(Source).where(Source.artist_id == artist_id, Source.url == payload.url)).scalars().first()
    if exists:
        raise HTTPException(409, "Diese Quelle ist bereits eingetragen")
    trust = {"tour_page": 1, "ical_feed": 2, "generic_web": 6}.get(payload.provider, 6)
    source = Source(
        scope="artist",
        provider=payload.provider,
        name=payload.name or payload.url or "Quelle",
        url=payload.url,
        artist_id=artist_id,
        trust_level=trust,
        is_enabled=True,
        is_auto=False,
        config={},
        created_by_user_id=ctx.actor.id,
    )
    db.add(source)
    db.flush()
    enqueue_job(db, "artist_crawl", artist_id=artist_id, priority=PRIORITY_MANUAL, reason="manual", requested_by=ctx.actor.id)
    audit.record(db, "source.create", actor=ctx.actor, request=request, target_type="source", target_id=source.id,
                 target_label=source.url, details={"artist": ua.artist.name})
    db.commit()
    return source_out(source, can_delete=True)


@router.delete("/{artist_id}/sources/{source_id}", response_model=OkResponse)
def delete_source(
    artist_id: int, source_id: int, request: Request, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> OkResponse:
    _subscription(db, ctx, artist_id)
    source = db.get(Source, source_id)
    if source is None or source.artist_id != artist_id:
        raise HTTPException(404, "Quelle nicht gefunden")
    if source.is_auto or not (ctx.is_admin or source.created_by_user_id == ctx.actor.id):
        raise HTTPException(403, "Diese Quelle kann nur von einem Administrator entfernt werden")
    audit.record(db, "source.delete", actor=ctx.actor, request=request, target_type="source", target_id=source.id, target_label=source.url)
    db.delete(source)
    db.commit()
    return OkResponse()


@router.post("/{artist_id}/refresh", response_model=OkResponse)
def refresh(artist_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> OkResponse:
    ua = _subscription(db, ctx, artist_id)
    last = last_manual_request(db, artist_id)
    if not ctx.is_admin and last and utcnow() - last < REFRESH_COOLDOWN:
        raise HTTPException(429, "Dieser Künstler wurde gerade erst aktualisiert. Bitte einige Minuten warten.")
    enqueue_job(db, "artist_crawl", artist_id=artist_id, priority=PRIORITY_MANUAL, reason="manual", requested_by=ctx.actor.id)
    db.commit()
    return OkResponse(detail=f"Aktualisierung für {ua.artist.name} wurde eingeplant.")


@router.post("/{artist_id}/image", response_model=ArtistOut)
async def upload_image(
    artist_id: int,
    request: Request,
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> ArtistOut:
    ua = _subscription(db, ctx, artist_id)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        path = save_artist_image(artist_id, data)
    except ImageError as exc:
        raise HTTPException(422, str(exc)) from exc
    artist = ua.artist
    artist.image_path = path
    artist.image_source = "upload"
    artist.image_source_url = None
    artist.image_locked = True
    artist.image_version += 1
    artist.image_updated_at = utcnow()
    audit.record(db, "artist.image_upload", actor=ctx.actor, request=request, target_type="artist", target_id=artist.id, target_label=artist.name)
    db.commit()
    return artist_out(artist, ua)


@router.post("/{artist_id}/image/refresh", response_model=OkResponse)
def refresh_image(artist_id: int, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> OkResponse:
    ua = _subscription(db, ctx, artist_id)
    ua.artist.image_locked = False
    enqueue_job(db, "artist_enrich", artist_id=artist_id, priority=PRIORITY_MANUAL, reason="manual",
                requested_by=ctx.actor.id, payload={"force_image": True})
    db.commit()
    return OkResponse(detail="Bildsuche wurde eingeplant.")
