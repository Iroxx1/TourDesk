"""Optional geocoding of unknown cities via Nominatim (OpenStreetMap), cached in the DB.

Nominatim usage policy: max. 1 request/second, meaningful User-Agent, caching.
A self-hosted Nominatim can be configured via ``geocoder_url``.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from sqlalchemy.orm import Session

from tourdesk.models import GeocodeCache
from tourdesk_crawler.http.client import PoliteHttpClient
from tourdesk_crawler.http.errors import CrawlError

log = logging.getLogger("tourdesk.crawler")


def geocode_city(db: Session, http: PoliteHttpClient, base_url: str, city: str, country_code: str | None) -> dict[str, Any] | None:
    query = f"{city}|{country_code or ''}".casefold()
    key = hashlib.sha256(query.encode()).hexdigest()
    cached = db.get(GeocodeCache, key)
    if cached is not None:
        return cached.result
    params = {"city": city, "format": "jsonv2", "addressdetails": 1, "limit": 1, "accept-language": "de"}
    if country_code:
        params["countrycodes"] = country_code.lower()
    result: dict[str, Any] | None = None
    try:
        data = http.fetch_json(base_url.rstrip("/") + "/search", params=params, api=True, min_interval=1.2)
        if isinstance(data, list) and data:
            hit = data[0]
            address = hit.get("address") or {}
            result = {
                "lat": float(hit["lat"]),
                "lon": float(hit["lon"]),
                "state": address.get("state") or address.get("region") or address.get("province"),
                "county": address.get("county"),
                "country_code": (address.get("country_code") or "").upper() or None,
                "display_name": hit.get("display_name"),
            }
    except (CrawlError, KeyError, ValueError, TypeError) as exc:
        log.info("geocoding failed for %s: %s", city, exc, extra={"event": "geocode.error"})
        return None  # do not cache failures
    db.add(GeocodeCache(query_hash=key, query=query, result=result))
    db.flush()
    return result
