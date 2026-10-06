"""Builds the provider context (HTTP client, geo resolver, settings) for a job."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tourdesk.core.timeutil import local_today
from tourdesk.services.app_settings import api_key, crawler_settings
from tourdesk_crawler.geocoder import geocode_city
from tourdesk_crawler.http.client import PoliteHttpClient
from tourdesk_crawler.pipeline.geo_resolver import GeoResolver
from tourdesk_crawler.providers.base import ProviderContext, RunLog

# tests can inject a transport (e.g. respx / MockTransport)
TRANSPORT_OVERRIDE: httpx.BaseTransport | None = None


@contextmanager
def provider_context(db: Session, session_factory: sessionmaker[Session], *, today: date | None = None,
                     dry_run: bool = False, runlog: RunLog | None = None, manual: bool = False) -> Iterator[ProviderContext]:
    settings = crawler_settings(db, fresh=True)
    http = PoliteHttpClient(session_factory, settings, transport=TRANSPORT_OVERRIDE, use_fresh_cache=not (manual or dry_run))
    geocode = None
    if settings.get("geocoder_enabled") and not dry_run:
        base = settings.get("geocoder_url") or "https://nominatim.openstreetmap.org"

        def geocode(name: str, country_code: str | None) -> dict | None:
            return geocode_city(db, http, base, name, country_code)

    geo = GeoResolver(db, geocode=geocode, create=not dry_run)
    ctx = ProviderContext(
        db=db,
        http=http,
        settings=settings,
        today=today or local_today(),
        geo=geo,
        log=runlog or RunLog(),
        api_key=lambda name: api_key(db, name),
        dry_run=dry_run,
    )
    try:
        yield ctx
    finally:
        http.close()
