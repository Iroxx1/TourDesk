"""Artist enrichment: MusicBrainz metadata (MBID, aliases, genre, website, links) and image."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from tourdesk.core.text import normalize_variants
from tourdesk.core.timeutil import utcnow
from tourdesk.models import Artist, CrawlerJob
from tourdesk.services import musicbrainz
from tourdesk.services.artists import add_aliases, ensure_website_source
from tourdesk_crawler.images import find_and_store_image
from tourdesk_crawler.jobs.common import RunRecorder, artist_spec, as_crawl_error
from tourdesk_crawler.jobs.context import provider_context
from tourdesk_crawler.providers.base import RunLog

_LATIN = re.compile(r"^[\w\s'’&.,!?+\-/()]+$")
_LINK_KEYS = {
    "songkick": "songkick", "bandsintown": "bandsintown", "discogs": "discogs", "last.fm": "lastfm",
    "spotify": "spotify", "deezer": "deezer", "youtube": "youtube", "instagram": "instagram", "facebook": "facebook",
}


def _apply_musicbrainz(artist: Artist, info: dict[str, Any], db: Session, runlog: RunLog) -> None:
    ext = dict(artist.external_ids or {})
    ext["musicbrainz"] = info.get("mbid") or ext.get("musicbrainz")
    for rel_type, urls in (info.get("urls") or {}).items():
        for url in urls:
            low = url.lower()
            if rel_type == "wikidata" or "wikidata.org" in low:
                ext["wikidata"] = url.rstrip("/").rsplit("/", 1)[-1]
            for needle, key in _LINK_KEYS.items():
                if needle in low and key not in ext:
                    ext[key] = url
    artist.external_ids = ext
    if not artist.genre and info.get("genre"):
        artist.genre = str(info["genre"]).title()[:100]
    if not artist.country_code and info.get("country") and len(info["country"]) == 2:
        artist.country_code = info["country"]
    aliases = [a for a in info.get("aliases", []) if a and len(a) <= 100 and _LATIN.match(a)][:10]
    if aliases:
        add_aliases(db, artist, aliases, "musicbrainz")
    homepage = (info.get("urls") or {}).get("official homepage")
    if homepage and not artist.official_website:
        artist.official_website = homepage[0][:500]
        ensure_website_source(db, artist)
        runlog.ok(f"Offizielle Website gefunden: {artist.official_website}")


def run_enrich(db: Session, session_factory: sessionmaker[Session], job: CrawlerJob | None, artist_id: int,
               *, force_image: bool = False) -> dict[str, Any]:
    artist = db.get(Artist, artist_id)
    if artist is None:
        return {"status": "skipped", "reason": "Künstler existiert nicht mehr"}
    runlog = RunLog()
    runlog.info(f"Metadaten & Bild: {artist.name}")
    recorder = RunRecorder(db, job, job_type="artist_enrich", label=artist.name, artist_id=artist.id)
    result: dict[str, Any] = {"musicbrainz": False, "image": None}
    with provider_context(db, session_factory, runlog=runlog) as ctx:
        settings = ctx.settings
        ua = ctx.http.user_agent
        if settings.get("musicbrainz_lookup", True):
            try:
                mbid = (artist.external_ids or {}).get("musicbrainz")
                if not mbid:
                    wanted: set[str] = set()
                    for n in (artist.name, *artist.alias_names):
                        wanted |= normalize_variants(n)
                    for hit in musicbrainz.search_artists(artist.name, ua, limit=5):
                        if (hit.get("score") or 0) >= 90 and normalize_variants(hit.get("name") or "") & wanted:
                            mbid = hit["mbid"]
                            break
                if mbid:
                    info = musicbrainz.lookup_artist(mbid, ua)
                    if info:
                        _apply_musicbrainz(artist, info, db, runlog)
                        result["musicbrainz"] = True
                        runlog.ok(f"MusicBrainz: {mbid}")
                else:
                    runlog.warn("MusicBrainz: kein eindeutiger Treffer")
            except Exception as exc:  # noqa: BLE001
                # discard a half-applied lookup (aliases, website source); a failed flush would
                # otherwise make the commit below raise and the whole job fail
                db.rollback()
                recorder.error(exc)
                runlog.fail(f"MusicBrainz: {as_crawl_error(exc)}")
            db.commit()
        if force_image or not artist.image_locked and artist.image_source in (None, "fallback"):
            try:
                found = find_and_store_image(ctx.http, artist_spec(artist), list(settings.get("image_providers") or ["official", "wikidata", "deezer"]))
            except Exception as exc:  # noqa: BLE001
                recorder.error(exc)
                found = None
                runlog.fail(f"Bildsuche: {as_crawl_error(exc)}")
            if found is not None:
                artist.image_path = f"artists/{artist.id}"
                artist.image_source = found.source
                artist.image_source_url = found.source_url[:1000]
                artist.image_version += 1
                artist.image_updated_at = utcnow()
                artist.image_locked = False
                result["image"] = found.source
                runlog.ok(f"Bild gefunden ({found.source})")
            else:
                runlog.warn("Kein Bild gefunden – Platzhalter bleibt")
        artist.enriched_at = utcnow()
        db.commit()
    recorder.finish("success" if not recorder.errors else "partial", {"sources_total": 0}, runlog)
    return {"status": "success", **result}
