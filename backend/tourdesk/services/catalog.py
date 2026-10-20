"""Künstlerkatalog: Import aus MusicBrainz, Seiten zum Blättern, Bilder und Detaildaten.

* Der Import (Crawler-Job ``catalog_import``) lädt pro Genre die bekanntesten Künstler weltweit
  (je Schlagwort bis zu 500) und aus DE/AT/CH (bis zu 500) über die MusicBrainz-Suche. MusicBrainz
  sortiert nach Relevanz – das entspricht grob der Bekanntheit.
* Der Katalog ist alphabetisch nach dem MusicBrainz-Sortiernamen geordnet („Kinks, The“ steht
  unter K). ``sort_key`` beginnt mit ``0`` für das Register „#“ (Ziffern, andere Schriften) und
  mit ``1`` für A–Z, damit die Register-Reihenfolge einer einfachen Sortierung entspricht.
* Bilder (Deezer) und Detaildaten (Website, Wikipedia) werden erst geladen, wenn sie gebraucht
  werden, und dann in der Datenbank bzw. im Medienordner zwischengespeichert.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import httpx
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from tourdesk.core.text import normalize_name, strip_accents
from tourdesk.core.timeutil import utcnow
from tourdesk.models import Artist, CatalogEntry, CatalogGenre, UserArtist
from tourdesk.services import musicbrainz
from tourdesk.services.catalog_genres import (
    DACH_COUNTRIES,
    GENRES,
    GENRES_BY_KEY,
    SEARCH_MAX,
    TOP_TAGS,
    Genre,
    genre_label,
    tag_query,
)
from tourdesk.services.media import ImageError, _encode_webp, _open, _square, media_root

log = logging.getLogger("tourdesk.catalog")

PAGE_SIZE = 100
LETTERS = ["#", *[chr(c) for c in range(ord("A"), ord("Z") + 1)]]
REFRESH_DAYS = 30
RETRY_HOURS = 6
IMAGE_SIZE = 160
IMAGE_RETRY_DAYS = 30
DETAILS_DAYS = 30

# MusicBrainz' Sonderkünstler („Various Artists“, „[unknown]“, …)
SPECIAL_MBIDS = {
    "89ad4ac3-39f7-470e-963a-56509c546377",  # Various Artists
    "125ec42a-7229-4250-afc5-e057484327fe",  # [unknown]
    "eec63d3c-3b81-4ad4-b1e4-7c147d4d2b61",  # [no artist]
    "33cf029c-63b0-41a0-9855-be2a3665fb3b",  # [data]
    "314e1c25-dde7-4e4d-b2f4-0a7b9f7c56dc",  # [anonymous]
    "f731ccc4-e22a-43af-a747-64213329e088",  # [traditional]
    "9be7f096-97ec-4615-8957-8d40b5dcbc41",  # [dialogue]
}
_YEAR_RE = re.compile(r"^(\d{4})")
# Latin letters that Unicode does not decompose into base letter + accent
_FOLD = str.maketrans({"Ø": "O", "ø": "o", "Æ": "AE", "æ": "ae", "Œ": "OE", "œ": "oe", "Ł": "L", "ł": "l",
                       "Đ": "D", "đ": "d", "Ð": "D", "ð": "d", "Þ": "Th", "þ": "th", "ß": "ss", "ı": "i"})


# --------------------------------------------------------------------------- helpers
def letter_of(sort_name: str) -> str:
    for ch in strip_accents((sort_name or "").translate(_FOLD)).upper():
        if ch.isalnum():
            return ch if "A" <= ch <= "Z" else "#"
    return "#"


def sort_key_of(sort_name: str, letter: str) -> str:
    folded = (sort_name or "").translate(_FOLD)
    # normalize_name drops non-latin scripts – those keep their own (casefolded) spelling
    return ("0" if letter == "#" else "1") + (normalize_name(folded) or folded.casefold())[:290]


def _year(value: str | None) -> int | None:
    m = _YEAR_RE.match(value or "")
    return int(m.group(1)) if m else None


def _top_tags(raw: dict[str, Any]) -> list[str]:
    tags = sorted(raw.get("tags") or [], key=lambda t: -int(t.get("count") or 0))
    return [str(t.get("name") or "").strip().lower() for t in tags if t.get("name")]


def parse_artist(raw: dict[str, Any], genre: Genre) -> dict[str, Any] | None:
    """Map one MusicBrainz search hit to catalogue fields, or ``None`` if it does not belong."""
    mbid = raw.get("id")
    name = (raw.get("name") or "").strip()
    if not mbid or not name or mbid in SPECIAL_MBIDS or name.startswith("["):
        return None
    tags = _top_tags(raw)
    if not any(t in genre.tags for t in tags[:TOP_TAGS]):
        return None
    sort_name = (raw.get("sort-name") or name).strip()
    letter = letter_of(sort_name)
    span = raw.get("life-span") or {}
    country = (raw.get("country") or "").upper()[:2] or None
    return {
        "mbid": mbid,
        "name": name[:300],
        "sort_name": sort_name[:300],
        "sort_key": sort_key_of(sort_name, letter),
        "letter": letter,
        "kind": (raw.get("type") or None),
        "country": country,
        "is_dach": country in DACH_COUNTRIES,
        "begin_year": _year(span.get("begin")),
        "end_year": _year(span.get("end")),
        "ended": bool(span.get("ended")),
        "disambiguation": (raw.get("disambiguation") or None),
        "tags": tags[:8],
    }


# --------------------------------------------------------------------------- import
Search = Callable[..., tuple[int, list[dict[str, Any]]]]


def _collect(genre: Genre, query: str, limit: int, ua: str, search: Search, found: dict[str, dict[str, Any]],
             ranks: dict[str, int]) -> None:
    offset = 0
    while offset < limit:
        total, artists = search(query, ua, offset=offset, limit=min(PAGE_SIZE, limit - offset))
        for i, raw in enumerate(artists):
            parsed = parse_artist(raw, genre)
            if parsed is None:
                continue
            rank = offset + i + 1
            found.setdefault(parsed["mbid"], parsed)
            ranks[parsed["mbid"]] = min(ranks.get(parsed["mbid"], rank), rank)
        offset += PAGE_SIZE
        if not artists or offset >= total:
            break


def import_genre(db: Session, genre: Genre, ua: str, *, search: Search = musicbrainz.search_page) -> dict[str, Any]:
    """Load one genre list from MusicBrainz and merge it into the catalogue (commits)."""
    now = utcnow()
    state = db.get(CatalogGenre, genre.key) or CatalogGenre(key=genre.key)
    state.status = "running"
    state.last_attempt_at = now
    db.add(state)
    db.commit()

    found: dict[str, dict[str, Any]] = {}
    ranks: dict[str, int] = {}
    try:
        # weltweit: jedes Schlagwort einzeln (MusicBrainz liefert pro Suche höchstens 500 Treffer)
        for tag in genre.tags:
            _collect(genre, tag_query(genre, tag), SEARCH_MAX, ua, search, found, ranks)
        # die bekanntesten aus DE/AT/CH – sonst wäre z. B. die Rock-Liste fast nur international
        dach = tag_query(genre) + " AND (" + " OR ".join(f"country:{c}" for c in DACH_COUNTRIES) + ")"
        _collect(genre, dach, SEARCH_MAX, ua, search, found, ranks)
    except Exception as exc:  # noqa: BLE001 - recorded on the genre, retried later
        db.rollback()
        state = db.get(CatalogGenre, genre.key)
        assert state is not None
        state.status = "error"
        state.last_error = f"{exc.__class__.__name__}: {exc}"[:1000]
        db.commit()
        log.warning("Katalog-Import %s fehlgeschlagen: %s", genre.key, exc, extra={"event": "catalog.import_error"})
        return {"genre": genre.key, "status": "error", "error": state.last_error}

    existing = {
        e.mbid: e for e in db.execute(select(CatalogEntry).where(CatalogEntry.mbid.in_(list(found)))).scalars()
    } if found else {}
    added = 0
    for mbid, data in found.items():
        entry = existing.get(mbid)
        if entry is None:
            entry = CatalogEntry(mbid=mbid, genres=[], genre_ranks={})
            db.add(entry)
            added += 1
        for field, value in data.items():
            if field != "mbid":
                setattr(entry, field, value)
        if genre.key not in (entry.genres or []):
            entry.genres = [*(entry.genres or []), genre.key]
        entry.genre_ranks = {**(entry.genre_ranks or {}), genre.key: ranks[mbid]}
        entry.seen_at = now
    db.flush()

    # artists that dropped out of this genre list lose the genre; entries without any genre go
    removed = 0
    stale = db.execute(
        select(CatalogEntry).where(CatalogEntry.genres.any(genre.key), CatalogEntry.mbid.not_in(list(found) or [""]))
    ).scalars().all()
    for entry in stale:
        entry.genres = [g for g in entry.genres if g != genre.key]
        entry.genre_ranks = {k: v for k, v in (entry.genre_ranks or {}).items() if k != genre.key}
        if not entry.genres:
            delete_entry_image(entry)
            db.delete(entry)
            removed += 1

    state = db.get(CatalogGenre, genre.key)
    assert state is not None
    state.status = "ok"
    state.entry_count = len(found)
    state.imported_at = now
    state.last_error = None
    db.commit()
    log.info("Katalog %s: %s Künstler (%s neu, %s entfernt)", genre.label, len(found), added, removed,
             extra={"event": "catalog.import", "genre": genre.key, "count": len(found)})
    return {"genre": genre.key, "status": "ok", "count": len(found), "added": added, "removed": removed}


def stale_genres(db: Session, now: datetime | None = None) -> list[Genre]:
    """Genres that were never imported, are older than ``REFRESH_DAYS`` or failed long enough ago."""
    now = now or utcnow()
    states = {s.key: s for s in db.execute(select(CatalogGenre)).scalars()}
    out = []
    for genre in GENRES:
        s = states.get(genre.key)
        if s is None or s.last_attempt_at is None:
            out.append(genre)
        elif s.status == "running" and s.last_attempt_at < now - timedelta(hours=1):
            out.append(genre)  # worker died during the import
        elif s.status in ("error", "pending") and s.last_attempt_at < now - timedelta(hours=RETRY_HOURS):
            out.append(genre)
        elif s.status == "ok" and (s.imported_at is None or s.imported_at < now - timedelta(days=REFRESH_DAYS)):
            out.append(genre)
    return out


# --------------------------------------------------------------------------- browsing
def _filtered(stmt, genre: str | None, origin: str):
    if genre:
        stmt = stmt.where(CatalogEntry.genres.any(genre))
    if origin == "dach":
        stmt = stmt.where(CatalogEntry.is_dach.is_(True))
    elif origin == "intl":
        stmt = stmt.where(CatalogEntry.is_dach.is_(False))
    return stmt


def letter_counts(db: Session, genre: str | None, origin: str) -> dict[str, int]:
    rows = db.execute(_filtered(select(CatalogEntry.letter, func.count()), genre, origin).group_by(CatalogEntry.letter)).all()
    counts = {letter: int(n) for letter, n in rows}
    return {letter: counts.get(letter, 0) for letter in LETTERS}


def followed_map(db: Session, user_id: int, mbids: list[str]) -> dict[str, tuple[int, bool]]:
    """mbid -> (TourDesk artist id, followed by this user)."""
    if not mbids:
        return {}
    mb = Artist.external_ids["musicbrainz"].astext
    rows = db.execute(
        select(mb, Artist.id, UserArtist.id)
        .outerjoin(UserArtist, (UserArtist.artist_id == Artist.id) & (UserArtist.user_id == user_id))
        .where(mb.in_(mbids))
    ).all()
    out: dict[str, tuple[int, bool]] = {}
    for mbid, artist_id, ua_id in rows:
        if mbid not in out or ua_id is not None:
            out[mbid] = (artist_id, ua_id is not None)
    return out


def _image_state(entry: CatalogEntry, images: bool) -> str:
    if entry.image_status == "ok":
        return "ok"
    if entry.image_status == "missing" or not images:
        return "missing"
    return "unknown"  # wird gerade im Hintergrund gesucht


def entry_out(entry: CatalogEntry, link: tuple[int, bool] | None = None, *, images: bool = True) -> dict[str, Any]:
    ordered = sorted(entry.genres or [], key=lambda g: (entry.genre_ranks or {}).get(g, 10**6))
    return {
        "mbid": entry.mbid,
        "name": entry.name,
        "sort_name": entry.sort_name,
        "letter": entry.letter,
        "kind": entry.kind,
        "country": entry.country,
        "begin_year": entry.begin_year,
        "end_year": entry.end_year,
        "ended": entry.ended,
        "disambiguation": entry.disambiguation,
        "genres": [genre_label(g) for g in ordered],
        "genre_keys": ordered,
        "image": _image_state(entry, images),
        "artist_id": link[0] if link else None,
        "followed": bool(link and link[1]),
    }


def catalog_page(db: Session, user_id: int, *, genre: str | None, origin: str, page: int, per_page: int,
                 images: str | None = None) -> dict[str, Any]:
    """One catalogue page. ``images`` = User-Agent for the background picture search (None = keine Bilder).

    Jeder Anfangsbuchstabe beginnt auf einer neuen Seite (oben links); die letzte Seite eines
    Buchstabens bleibt dafür unten teilweise leer.
    """
    counts = letter_counts(db, genre, origin)
    total = sum(counts.values())
    letter_pages: dict[str, int | None] = {}
    spans: list[tuple[str, int, int]] = []  # (Buchstabe, erste Seite, Seitenzahl)
    pages = 0
    for letter in LETTERS:
        n = -(-counts[letter] // per_page)
        letter_pages[letter] = pages if n else None
        if n:
            spans.append((letter, pages, n))
        pages += n
    pages = max(1, pages)
    page = max(0, min(page, pages - 1))
    rows: list[CatalogEntry] = []
    span = next((s for s in spans if s[1] <= page < s[1] + s[2]), None)
    if span is not None:
        letter, first, _n = span
        rows = list(db.execute(
            _filtered(select(CatalogEntry), genre, origin)
            .where(CatalogEntry.letter == letter)
            .order_by(CatalogEntry.sort_key.collate("C"), CatalogEntry.mbid)
            .offset((page - first) * per_page)
            .limit(per_page)
        ).scalars().all())
    links = followed_map(db, user_id, [r.mbid for r in rows])
    if images:
        queue_images([r.mbid for r in rows if r.image_status == "unknown"], images)
    return {
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "total": total,
        "letters": letter_pages,
        "items": [entry_out(r, links.get(r.mbid), images=bool(images)) for r in rows],
    }


def catalog_meta(db: Session) -> dict[str, Any]:
    states = {s.key: s for s in db.execute(select(CatalogGenre)).scalars()}
    counts = dict(db.execute(
        select(func.unnest(CatalogEntry.genres).label("g"), func.count()).group_by("g")
    ).all())
    total = int(db.execute(select(func.count()).select_from(CatalogEntry)).scalar() or 0)
    done = sum(1 for g in GENRES if states.get(g.key) and states[g.key].imported_at)
    importing = any(s.status == "running" for s in states.values())
    imported = [s.imported_at for s in states.values() if s.imported_at]
    return {
        "total": total,
        "ready": total > 0,
        "importing": importing,
        "progress": {"done": done, "total": len(GENRES)},
        "imported_at": max(imported) if imported else None,
        "genres": [{"key": g.key, "label": g.label, "count": int(counts.get(g.key, 0))} for g in GENRES],
        "dach_total": int(db.execute(select(func.count()).select_from(CatalogEntry).where(CatalogEntry.is_dach.is_(True))).scalar() or 0),
        "images": {
            "ok": int(db.execute(select(func.count()).select_from(CatalogEntry).where(CatalogEntry.image_status == "ok")).scalar() or 0),
            "pending": int(db.execute(select(func.count()).select_from(CatalogEntry).where(CatalogEntry.image_status == "unknown")).scalar() or 0),
        },
    }


# --------------------------------------------------------------------------- images (Deezer, Wikimedia Commons)
_deezer_lock = threading.Lock()
_deezer_last = 0.0
DEEZER_INTERVAL = 0.15  # Deezer erlaubt 50 API-Anfragen / 5 s (Downloads vom Bild-CDN zählen nicht)
JOB_DEEZER_INTERVAL = 0.25  # Vorladen im Hintergrund: Luft lassen für das Blättern (eigener Prozess)
SPARQL_URL = "https://query.wikidata.org/sparql"
SPARQL_BATCH = 150
PRELOAD_LIMIT = 1500  # Einträge je Lauf des Vorlade-Jobs (~6 min); der Scheduler startet den nächsten


class TransientImageError(Exception):
    """Bildquelle gerade nicht erreichbar oder Kontingent erschöpft – Eintrag bleibt offen, später erneut."""


def _deezer_throttle(interval: float = DEEZER_INTERVAL) -> None:
    global _deezer_last
    with _deezer_lock:
        wait = interval - (time.monotonic() - _deezer_last)
        if wait > 0:
            time.sleep(wait)
        _deezer_last = time.monotonic()


def _check_transient(resp: httpx.Response) -> None:
    if resp.status_code == 429 or resp.status_code >= 500:
        raise TransientImageError(f"HTTP {resp.status_code}")


def entry_image_file(mbid: str) -> Path:
    return media_root() / "catalog" / mbid[:2] / f"{mbid}.webp"


def delete_entry_image(entry: CatalogEntry) -> None:
    entry_image_file(entry.mbid).unlink(missing_ok=True)


def find_deezer_picture(name: str, ua: str, get: Callable[..., httpx.Response] = httpx.get, *,
                        interval: float = DEEZER_INTERVAL) -> str | None:
    _deezer_throttle(interval)
    try:
        resp = get("https://api.deezer.com/search/artist", params={"q": name, "limit": 5},
                   headers={"User-Agent": ua}, timeout=8.0, follow_redirects=True)
    except httpx.TransportError as exc:
        raise TransientImageError(str(exc)) from exc
    _check_transient(resp)
    resp.raise_for_status()
    body = resp.json() or {}
    if body.get("error"):
        # z. B. {"error": {"message": "Quota limit exceeded", "code": 4}} – kommt mit HTTP 200
        raise TransientImageError(str((body["error"] or {}).get("message") or body["error"]))
    wanted = normalize_name(name)
    for hit in body.get("data") or []:
        if normalize_name(hit.get("name")) != wanted:
            continue
        url = hit.get("picture_medium") or hit.get("picture")
        if url and "/artist//" not in url:  # Deezer-Platzhalter ohne Bild
            return url
    return None


def _store_image(file: Path, content: bytes) -> None:
    if len(content) > 2_000_000:
        raise ImageError("Bild zu groß")
    data = _encode_webp(_square(_open(content), IMAGE_SIZE), quality=80)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)


def _save_result(db: Session, mbid: str, file: Path, status: str, source: str, credit: str | None = None) -> Path | None:
    entry = db.get(CatalogEntry, mbid)
    if entry is None:
        return None
    entry.image_status = status
    entry.image_source = source
    entry.image_credit = credit if status == "ok" else None
    entry.image_path = str(file.relative_to(media_root())).replace("\\", "/") if status == "ok" else None
    entry.image_checked_at = utcnow()
    db.commit()
    return file if status == "ok" else None


def fetch_entry_image(db: Session, entry: CatalogEntry, ua: str, get: Callable[..., httpx.Response] = httpx.get, *,
                      interval: float = DEEZER_INTERVAL) -> Path | None:
    """Search Deezer for the picture of a catalogue entry and store it (or remember that there is none).

    Raises ``TransientImageError`` when Deezer is unreachable or the quota is used up – the entry then
    stays „unknown“ and is tried again later. The database connection is released during the network
    calls (``db.close()``), so slow picture lookups never block other requests.
    """
    file = entry_image_file(entry.mbid)
    if entry.image_status == "ok" and file.is_file():
        return file
    now = utcnow()
    if entry.image_status == "missing" and entry.image_checked_at and entry.image_checked_at > now - timedelta(days=IMAGE_RETRY_DAYS):
        return None
    mbid, name = entry.mbid, entry.name
    db.close()
    status = "missing"
    try:
        url = find_deezer_picture(name, ua, get, interval=interval)
        if url:
            img = get(url, headers={"User-Agent": ua}, timeout=8.0, follow_redirects=True)  # Bild-CDN, kein API-Kontingent
            _check_transient(img)
            img.raise_for_status()
            _store_image(file, img.content)
            status = "ok"
    except TransientImageError:
        raise
    except (httpx.HTTPError, ImageError, ValueError) as exc:
        log.info("Katalogbild %s: %s", name, exc, extra={"event": "catalog.image_error"})
    return _save_result(db, mbid, file, status, "deezer")


def wikimedia_pictures(mbids: list[str], ua: str, post: Callable[..., httpx.Response] = httpx.post) -> dict[str, str]:
    """MusicBrainz-ID → Dateiname bei Wikimedia Commons (Wikidata P434 → P18), in einer Sammelabfrage."""
    if not mbids:
        return {}
    values = " ".join(f'"{m}"' for m in mbids if re.fullmatch(r"[0-9a-f-]{36}", m))
    query = f"SELECT ?mbid ?image WHERE {{ VALUES ?mbid {{ {values} }} ?item wdt:P434 ?mbid ; wdt:P18 ?image . }}"
    try:
        resp = post(SPARQL_URL, data={"query": query}, timeout=60.0,
                    headers={"User-Agent": wikimedia_user_agent(ua), "Accept": "application/sparql-results+json"})
    except httpx.TransportError as exc:
        raise TransientImageError(str(exc)) from exc
    _check_transient(resp)
    resp.raise_for_status()
    out: dict[str, str] = {}
    for row in (resp.json().get("results") or {}).get("bindings") or []:
        mbid = (row.get("mbid") or {}).get("value")
        image = (row.get("image") or {}).get("value") or ""
        if mbid and image:
            out.setdefault(mbid, unquote(image.rsplit("/", 1)[-1]))
    return out


def fetch_commons_image(db: Session, entry: CatalogEntry, filename: str, ua: str,
                        get: Callable[..., httpx.Response] = httpx.get) -> Path | None:
    """Store a Wikimedia Commons picture (thumbnail) for an entry Deezer has none for, with credit link."""
    file = entry_image_file(entry.mbid)
    name = filename.replace(" ", "_")
    mbid = entry.mbid
    db.close()
    status, credit = "missing", None
    try:
        img = get(f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(name)}", params={"width": 320},
                  headers={"User-Agent": wikimedia_user_agent(ua)}, timeout=20.0, follow_redirects=True)
        _check_transient(img)
        img.raise_for_status()
        if not (img.headers.get("content-type") or "").startswith("image/"):
            raise ImageError("Keine Bilddatei")
        _store_image(file, img.content)
        status, credit = "ok", f"https://commons.wikimedia.org/wiki/File:{quote(name)}"
    except TransientImageError:
        raise
    except (httpx.HTTPError, ImageError, ValueError) as exc:
        log.info("Commons-Bild %s: %s", filename, exc, extra={"event": "catalog.image_error"})
    return _save_result(db, mbid, file, status, "wikimedia" if status == "ok" else "all", credit)


def fill_from_wikimedia(db: Session, ua: str, *, get: Callable[..., httpx.Response] = httpx.get,
                        post: Callable[..., httpx.Response] = httpx.post, limit: int = 3000) -> dict[str, int]:
    """Entries without Deezer picture: look for a Commons picture via Wikidata (few batch queries)."""
    mbids = list(db.execute(
        select(CatalogEntry.mbid)
        .where(CatalogEntry.image_status == "missing", or_(CatalogEntry.image_source.is_(None), CatalogEntry.image_source == "deezer"))
        .order_by(CatalogEntry.sort_key)
        .limit(limit)
    ).scalars())
    found = 0
    for start in range(0, len(mbids), SPARQL_BATCH):
        chunk = mbids[start: start + SPARQL_BATCH]
        pictures = wikimedia_pictures(chunk, ua, post)
        for mbid in chunk:
            entry = db.get(CatalogEntry, mbid)
            if entry is None:
                continue
            if mbid in pictures:
                time.sleep(0.2)  # höflich zu Commons
                if fetch_commons_image(db, entry, pictures[mbid], ua, get):
                    found += 1
            else:
                entry.image_source = "all"
                db.commit()
    return {"checked": len(mbids), "found": found}


def images_pending(now: datetime | None = None):
    """Statement condition: entries the preload job still has to look at."""
    now = now or utcnow()
    return or_(
        CatalogEntry.image_status == "unknown",
        (CatalogEntry.image_status == "missing") & or_(CatalogEntry.image_source.is_(None), CatalogEntry.image_source == "deezer"),
        (CatalogEntry.image_status == "missing") & (CatalogEntry.image_checked_at < now - timedelta(days=IMAGE_RETRY_DAYS)),
    )


def preload_images(db: Session, ua: str, *, limit: int = PRELOAD_LIMIT, get: Callable[..., httpx.Response] = httpx.get,
                   post: Callable[..., httpx.Response] = httpx.post, interval: float = JOB_DEEZER_INTERVAL,
                   max_transient: int = 5) -> dict[str, Any]:
    """One run of the preload job: Deezer for unknown entries, then Wikimedia Commons for the gaps."""
    now = utcnow()
    # Lücken nach einem Monat erneut versuchen
    db.execute(
        update(CatalogEntry)
        .where(CatalogEntry.image_status == "missing", CatalogEntry.image_checked_at < now - timedelta(days=IMAGE_RETRY_DAYS))
        .values(image_status="unknown", image_source=None)
    )
    db.commit()
    mbids = list(db.execute(
        select(CatalogEntry.mbid).where(CatalogEntry.image_status == "unknown").order_by(CatalogEntry.sort_key).limit(limit)
    ).scalars())
    # transient: einzelne Aussetzer (der Eintrag bleibt offen und kommt im nächsten Lauf dran)
    # paused: Quelle anhaltend gestört oder Kontingent erschöpft – der Scheduler wartet dann eine Weile
    stats: dict[str, Any] = {"deezer_ok": 0, "deezer_missing": 0, "transient": 0, "paused": False}
    in_a_row = 0
    for mbid in mbids:
        entry = db.get(CatalogEntry, mbid)
        if entry is None or entry.image_status != "unknown":
            continue  # inzwischen beim Blättern geholt
        try:
            path = fetch_entry_image(db, entry, ua, get, interval=interval)
            stats["deezer_ok" if path else "deezer_missing"] += 1
            in_a_row = 0
        except TransientImageError as exc:
            stats["transient"] += 1
            in_a_row += 1
            if in_a_row >= max_transient:
                log.warning("Bilder vorladen pausiert: %s", exc, extra={"event": "catalog.image_pause"})
                stats["paused"] = True
                break
    try:
        stats["wikimedia"] = fill_from_wikimedia(db, ua, get=get, post=post)
    except (TransientImageError, httpx.HTTPError, ValueError) as exc:
        log.info("Wikidata-Bilder später: %s", exc, extra={"event": "catalog.image_error"})
        stats["wikimedia"] = {"checked": 0, "found": 0}
        stats["transient"] += 1
        stats["paused"] = True
    stats["remaining"] = int(db.execute(select(func.count()).select_from(CatalogEntry).where(images_pending())).scalar() or 0)
    stats["status"] = "partial" if stats["paused"] else "success"
    return stats


# Hintergrund-Suche: Katalogseiten liefern sofort (mit Initialen) und stoßen die Bildsuche an; der
# Browser lädt später nur noch fertige Bilder. So belegen langsame Bildabrufe keine Verbindungen.
_image_queue: queue.Queue[str] = queue.Queue()
_image_pending: set[str] = set()
_image_lock = threading.Lock()
_image_thread: threading.Thread | None = None


def queue_images(mbids: list[str], ua: str) -> None:
    global _image_thread
    with _image_lock:
        new = [m for m in mbids if m not in _image_pending]
        if not new:
            return
        _image_pending.update(new)
        for m in new:
            _image_queue.put(m)
        if _image_thread is None or not _image_thread.is_alive():
            _image_thread = threading.Thread(target=_image_worker, args=(ua,), name="catalog-images", daemon=True)
            _image_thread.start()


def _image_worker(ua: str) -> None:
    global _image_thread
    from tourdesk.core.db import get_session_factory

    sf = get_session_factory()
    while True:
        try:
            mbid = _image_queue.get(timeout=30)
        except queue.Empty:
            with _image_lock:
                if _image_queue.empty():
                    _image_thread = None
                    return
            continue
        try:
            with sf() as db:
                entry = db.get(CatalogEntry, mbid)
                if entry is not None:
                    fetch_entry_image(db, entry, ua)
        except TransientImageError as exc:
            log.info("Katalogbild %s später: %s", mbid, exc, extra={"event": "catalog.image_error"})
        except Exception:  # noqa: BLE001 - ein Bild darf die Warteschlange nicht anhalten
            log.exception("Katalogbild %s fehlgeschlagen", mbid, extra={"event": "catalog.image_error"})
        finally:
            with _image_lock:
                _image_pending.discard(mbid)


# --------------------------------------------------------------------------- details
def _first_sentences(text: str, limit: int = 460) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > 120 else cut.rsplit(" ", 1)[0] + " …"


PROJECT_URL = "https://github.com/Iroxx1/TourDesk"


def wikimedia_user_agent(ua: str) -> str:
    """Wikimedia (Wikidata, Wikipedia) blocks bots without contact details with 403 – without a
    configured contact the project page serves as contact (the user's e-mail is never added)."""
    if "@" in ua or "http://" in ua or "https://" in ua:
        return ua
    return f"{ua} (+{PROJECT_URL})"


def _wikipedia_summary(qid: str, ua: str, get: Callable[..., httpx.Response]) -> dict[str, Any]:
    headers = {"User-Agent": wikimedia_user_agent(ua), "Accept": "application/json"}
    data = get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json", headers=headers, timeout=6.0, follow_redirects=True)
    data.raise_for_status()
    sitelinks = ((data.json().get("entities") or {}).get(qid) or {}).get("sitelinks") or {}
    for lang in ("de", "en"):
        title = (sitelinks.get(f"{lang}wiki") or {}).get("title")
        if not title:
            continue
        resp = get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
                   headers=headers, timeout=6.0, follow_redirects=True)
        if resp.status_code != 200:
            continue
        body = resp.json()
        extract = _first_sentences(body.get("extract") or "")
        page = ((body.get("content_urls") or {}).get("desktop") or {}).get("page")
        if extract:
            return {"description": extract, "description_lang": lang, "wikipedia_url": page}
    return {}


def fetch_details(entry: CatalogEntry, ua: str, get: Callable[..., httpx.Response] = httpx.get,
                  lookup: Callable[..., dict[str, Any] | None] | None = None) -> dict[str, Any] | None:
    info = (lookup or musicbrainz.lookup_artist)(entry.mbid, ua)
    if info is None:
        return None
    urls = info.get("urls") or {}
    website = next((u for u in urls.get("official homepage", []) if u.startswith(("http://", "https://"))), None)
    qid = None
    for rel_type, links in urls.items():
        for url in links:
            if rel_type == "wikidata" or "wikidata.org/wiki/" in url:
                qid = url.rstrip("/").rsplit("/", 1)[-1]
    details: dict[str, Any] = {"website": website, "wikidata": qid, "description": None, "description_lang": None, "wikipedia_url": None}
    if qid and re.fullmatch(r"Q\d+", qid):
        try:
            details.update(_wikipedia_summary(qid, ua, get))
        except (httpx.HTTPError, ValueError) as exc:
            log.info("Wikipedia für %s: %s", entry.name, exc, extra={"event": "catalog.details_error"})
            details["incomplete"] = True  # nicht einen Monat merken – beim nächsten Öffnen erneut versuchen
    return details


def ensure_details(db: Session, entry: CatalogEntry, ua: str, **kw: Any) -> tuple[CatalogEntry, dict[str, Any]]:
    """Detail data of an entry, fetched once (MusicBrainz, Wikidata, Wikipedia) and cached for a month.

    Returns the (possibly reloaded) entry: the database connection is released during the network calls.
    """
    now = utcnow()
    if entry.details is None or entry.details_fetched_at is None or entry.details_fetched_at < now - timedelta(days=DETAILS_DAYS):
        mbid = entry.mbid
        db.close()
        details = fetch_details(entry, ua, **kw)
        entry = db.get(CatalogEntry, mbid) or entry
        if details is not None:
            incomplete = bool(details.pop("incomplete", False))
            entry.details = details
            entry.details_fetched_at = None if incomplete else now
            db.commit()
    return entry, entry.details or {}


def detail_out(db: Session, entry: CatalogEntry, user_id: int, details: dict[str, Any], *, images: bool = True) -> dict[str, Any]:
    link = followed_map(db, user_id, [entry.mbid]).get(entry.mbid)
    out = entry_out(entry, link, images=images)
    out.update({
        "tags": entry.tags or [],
        "website": details.get("website"),
        "wikipedia_url": details.get("wikipedia_url"),
        "description": details.get("description"),
        "description_lang": details.get("description_lang"),
        "musicbrainz_url": f"https://musicbrainz.org/artist/{entry.mbid}",
        "image_credit": entry.image_credit if entry.image_status == "ok" and entry.image_source == "wikimedia" else None,
    })
    return out


__all__ = [
    "GENRES_BY_KEY",
    "catalog_meta",
    "catalog_page",
    "ensure_details",
    "fetch_entry_image",
    "import_genre",
    "preload_images",
    "queue_images",
    "stale_genres",
]
