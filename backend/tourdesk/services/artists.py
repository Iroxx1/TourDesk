"""Artist catalogue, subscriptions and artist sources."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from tourdesk.core.constants import PROVIDERS, provider_label
from tourdesk.core.text import normalize_name, normalize_variants, slugify, url_domain
from tourdesk.core.timeutil import utcnow
from tourdesk.models import Artist, ArtistAlias, Source, User, UserArtist
from tourdesk.models.enums import TRUST_LABELS
from tourdesk.schemas.artists import ArtistImages, ArtistOut, SourceOut, SubscriptionOut
from tourdesk.services.jobs import PRIORITY_NEW, enqueue_job
from tourdesk.services.media import artist_image_url, save_fallback_artist_image

DEMO_ARTIST_NAMES = {"beispielband", "tourdesk demo band", "example band"}


def artist_images(a: Artist) -> ArtistImages:
    return ArtistImages(
        thumb=artist_image_url(a.image_path, a.image_source, a.image_version, "thumb"),
        tile=artist_image_url(a.image_path, a.image_source, a.image_version, "tile"),
        hero=artist_image_url(a.image_path, a.image_source, a.image_version, "hero"),
        source=a.image_source,
        source_url=a.image_source_url,
    )


def subscription_out(ua: UserArtist) -> SubscriptionOut:
    return SubscriptionOut(
        is_active=ua.is_active,
        show_festivals=ua.show_festivals,
        notify=ua.notify,
        pinned=ua.pinned,
        sort_order=ua.sort_order,
        created_at=ua.created_at,
    )


_PUBLIC_EXTERNAL_IDS = {"musicbrainz", "wikidata", "ticketmaster", "bandsintown", "songkick", "deezer", "spotify", "discogs"}


def artist_out(a: Artist, ua: UserArtist | None = None, *, can_edit: bool = True) -> ArtistOut:
    return ArtistOut(
        id=a.id,
        name=a.name,
        slug=a.slug,
        genre=a.genre,
        country_code=a.country_code,
        official_website=a.official_website,
        aliases=a.alias_names,
        search_terms=list(a.search_terms or []),
        external_ids={k: v for k, v in (a.external_ids or {}).items() if k in _PUBLIC_EXTERNAL_IDS},
        images=artist_images(a),
        is_demo=a.is_demo,
        crawl_status=a.crawl_status,
        last_crawled_at=a.last_crawled_at,
        last_success_at=a.last_success_at,
        next_crawl_at=a.next_crawl_at,
        last_error=a.last_error,
        subscription=subscription_out(ua) if ua else None,
        can_edit=can_edit,
    )


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name, max_length=100)
    slug = base
    n = 2
    while db.execute(select(Artist.id).where(Artist.slug == slug)).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


def find_catalog_artist(db: Session, name: str, musicbrainz_id: str | None = None) -> Artist | None:
    if musicbrainz_id:
        found = db.execute(
            select(Artist).where(Artist.external_ids["musicbrainz"].astext == musicbrainz_id)
        ).unique().scalars().first()
        if found:
            return found
    variants = list(normalize_variants(name))
    if not variants:
        return None
    found = db.execute(
        select(Artist).where(Artist.name_norm.in_(variants)).order_by(Artist.id)
    ).unique().scalars().first()
    if found:
        return found
    return db.execute(
        select(Artist).join(ArtistAlias, ArtistAlias.artist_id == Artist.id).where(ArtistAlias.alias_norm.in_(variants))
    ).unique().scalars().first()


def set_aliases(db: Session, artist: Artist, aliases: list[str], origin: str = "user") -> None:
    wanted: dict[str, str] = {}
    for alias in aliases:
        key = normalize_name(alias)
        if key and key != artist.name_norm:
            wanted.setdefault(key, alias.strip())
    for existing in list(artist.aliases):
        if existing.alias_norm not in wanted and existing.origin == origin:
            artist.aliases.remove(existing)
    present = {a.alias_norm for a in artist.aliases}
    for key, alias in wanted.items():
        if key not in present:
            artist.aliases.append(ArtistAlias(alias=alias, alias_norm=key, origin=origin))
    db.flush()


def add_aliases(db: Session, artist: Artist, aliases: list[str], origin: str) -> None:
    present = {a.alias_norm for a in artist.aliases} | {artist.name_norm}
    for alias in aliases:
        key = normalize_name(alias)
        if key and key not in present:
            artist.aliases.append(ArtistAlias(alias=alias.strip()[:200], alias_norm=key[:200], origin=origin))
            present.add(key)
    db.flush()


def ensure_website_source(db: Session, artist: Artist, *, created_by: int | None = None) -> None:
    if not artist.official_website:
        return
    existing = db.execute(
        select(Source).where(Source.artist_id == artist.id, Source.provider == "official_website")
    ).scalars().first()
    if existing is None:
        db.add(
            Source(
                scope="artist",
                provider="official_website",
                name=f"Offizielle Website ({url_domain(artist.official_website) or artist.official_website})",
                url=artist.official_website,
                artist_id=artist.id,
                trust_level=1,
                is_enabled=True,
                is_auto=True,
                config={"discover": True},
                created_by_user_id=created_by,
            )
        )
    elif existing.url != artist.official_website:
        existing.url = artist.official_website
        existing.name = f"Offizielle Website ({url_domain(artist.official_website) or artist.official_website})"
        existing.status = "new"
        existing.consecutive_failures = 0
        existing.next_attempt_at = None
    db.flush()


def ensure_demo_source(db: Session, artist: Artist) -> None:
    if not artist.is_demo:
        return
    exists = db.execute(select(Source.id).where(Source.artist_id == artist.id, Source.provider == "demo")).first()
    if not exists:
        db.add(
            Source(scope="artist", provider="demo", name="Demo-Tourdaten", url=None, artist_id=artist.id,
                   trust_level=1, is_enabled=True, is_auto=True, config={})
        )
        db.flush()


def create_catalog_artist(
    db: Session,
    *,
    name: str,
    website: str | None,
    genre: str | None,
    aliases: list[str],
    search_terms: list[str],
    musicbrainz_id: str | None,
    created_by: User | None,
) -> Artist:
    artist = Artist(
        name=name,
        name_norm=normalize_name(name),
        slug=unique_slug(db, name),
        genre=genre,
        official_website=website,
        search_terms=search_terms,
        external_ids={"musicbrainz": musicbrainz_id} if musicbrainz_id else {},
        is_demo=normalize_name(name) in DEMO_ARTIST_NAMES,
        crawl_status="pending",
        next_crawl_at=utcnow(),
        created_by_user_id=created_by.id if created_by else None,
    )
    db.add(artist)
    db.flush()
    add_aliases(db, artist, aliases, "user")
    artist.image_path = save_fallback_artist_image(artist.id, artist.name)
    artist.image_source = "fallback"
    artist.image_version = 1
    ensure_website_source(db, artist, created_by=created_by.id if created_by else None)
    ensure_demo_source(db, artist)
    return artist


def follow_artist(db: Session, user: User, artist: Artist, *, show_festivals: bool) -> tuple[UserArtist, bool]:
    ua = db.execute(
        select(UserArtist).where(UserArtist.user_id == user.id, UserArtist.artist_id == artist.id)
    ).unique().scalar_one_or_none()
    if ua is not None:
        return ua, False
    max_order = db.execute(select(func.max(UserArtist.sort_order)).where(UserArtist.user_id == user.id)).scalar() or 0
    ua = UserArtist(user_id=user.id, artist_id=artist.id, show_festivals=show_festivals, sort_order=max_order + 1)
    db.add(ua)
    db.flush()
    return ua, True


def schedule_initial_jobs(db: Session, artist: Artist, requested_by: int | None) -> None:
    enqueue_job(db, "artist_enrich", artist_id=artist.id, priority=PRIORITY_NEW, reason="new_artist", requested_by=requested_by)
    enqueue_job(db, "artist_crawl", artist_id=artist.id, priority=PRIORITY_NEW, reason="new_artist", requested_by=requested_by)


def subscriber_count(db: Session, artist_id: int) -> int:
    return db.execute(select(func.count(UserArtist.id)).where(UserArtist.artist_id == artist_id)).scalar_one()


def source_out(s: Source, *, can_delete: bool = False, artist_name: str | None = None,
               venue_name: str | None = None, festival_name: str | None = None) -> SourceOut:
    return SourceOut(
        id=s.id,
        scope=s.scope,
        provider=s.provider,
        provider_label=provider_label(s.provider),
        name=s.name,
        url=s.url,
        trust_level=s.trust_level,
        trust_label=TRUST_LABELS.get(s.trust_level, "Quelle"),
        is_enabled=s.is_enabled,
        is_auto=s.is_auto,
        status=s.status,
        artist_id=s.artist_id,
        artist_name=artist_name,
        venue_id=s.venue_id,
        venue_name=venue_name,
        festival_id=s.festival_id,
        festival_name=festival_name,
        last_attempt_at=s.last_attempt_at,
        last_success_at=s.last_success_at,
        last_error_at=s.last_error_at,
        last_error=s.last_error,
        last_error_type=s.last_error_type,
        consecutive_failures=s.consecutive_failures,
        total_failures=s.total_failures,
        total_runs=s.total_runs,
        next_attempt_at=s.next_attempt_at,
        last_http_status=s.last_http_status,
        last_duration_ms=s.last_duration_ms,
        last_event_count=s.last_event_count,
        last_method=s.last_method,
        config={k: v for k, v in (s.config or {}).items() if k not in ("api_key", "token")},
        can_delete=can_delete,
    )


def user_addable_providers() -> list[str]:
    return [k for k, v in PROVIDERS.items() if v.get("user_addable")]


def search_catalog(db: Session, q: str, limit: int = 10) -> list[Artist]:
    norm = normalize_name(q)
    if not norm:
        return []
    from tourdesk.core.text import escape_like

    pattern = "%" + escape_like(norm) + "%"
    stmt = (
        select(Artist)
        .outerjoin(ArtistAlias, ArtistAlias.artist_id == Artist.id)
        .where(or_(Artist.name_norm.like(pattern, escape="\\"), ArtistAlias.alias_norm.like(pattern, escape="\\")))
        .order_by((Artist.name_norm == norm).desc(), Artist.name_norm.like(escape_like(norm) + "%", escape="\\").desc(), Artist.name)
        .limit(limit)
    )
    return list(dict.fromkeys(db.execute(stmt).unique().scalars()))
