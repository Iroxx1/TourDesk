"""Crawler job ``catalog_import``: lädt die Genre-Listen des Künstlerkatalogs aus MusicBrainz."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from tourdesk.core.db import get_session_factory
from tourdesk.services import catalog
from tourdesk.services.app_settings import crawler_settings
from tourdesk.services.catalog_genres import GENRES


def run_catalog_import(db: Session, *, force: bool = False, search=None) -> dict[str, Any]:
    settings = crawler_settings(db, fresh=True)
    if not settings.get("musicbrainz_lookup", True):
        return {"status": "skipped", "reason": "MusicBrainz-Abfragen sind in den Crawler-Einstellungen aus"}
    ua = settings["user_agent"] + (f" ({settings['contact']})" if settings.get("contact") else "")
    genres = list(GENRES) if force else catalog.stale_genres(db)
    results = []
    for genre in genres:
        kwargs = {"search": search} if search is not None else {}
        results.append(catalog.import_genre(db, genre, ua, **kwargs))
    failed = [r for r in results if r["status"] != "ok"]
    status = "success" if not failed else ("failed" if len(failed) == len(results) else "partial")
    return {
        "status": status if results else "skipped",
        "genres": len(results),
        "failed": [r["genre"] for r in failed],
        "entries": sum(r.get("count", 0) for r in results),
    }


def run_catalog_images(db: Session, sf: sessionmaker[Session] | None = None, **kwargs: Any) -> dict[str, Any]:
    """Crawler job ``catalog_images``: lädt die Katalogbilder im Hintergrund vor (Deezer, Lücken über Wikimedia)."""
    settings = crawler_settings(db, fresh=True)
    if "deezer" not in (settings.get("image_providers") or []):
        return {"status": "skipped", "reason": "Deezer ist als Bildquelle abgeschaltet"}
    ua = settings["user_agent"] + (f" ({settings['contact']})" if settings.get("contact") else "")
    # eigene Sitzung: die Bildabrufe geben ihre Verbindung zwischendurch frei (db.close()) –
    # in der Sitzung des Runners würde das den Job selbst abhängen und sein Ergebnis ginge verloren
    with (sf or get_session_factory())() as work:
        return catalog.preload_images(work, ua, **kwargs)
