"""Minimal MusicBrainz web service client (artist search and lookup).

MusicBrainz asks for at most one request per second and a meaningful User-Agent.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

log = logging.getLogger("tourdesk.api")

BASE = "https://musicbrainz.org/ws/2"
_lock = threading.Lock()
_last_request = 0.0
_cache: dict[str, tuple[float, Any]] = {}
CACHE_SECONDS = 3600


def _throttle() -> None:
    global _last_request
    with _lock:
        wait = 1.1 - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def _get(path: str, params: dict[str, Any], user_agent: str, timeout: float) -> Any:
    key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    _throttle()
    resp = httpx.get(
        f"{BASE}/{path}",
        params={**params, "fmt": "json"},
        headers={"User-Agent": user_agent, "Accept": "application/json"},
        timeout=timeout,
        follow_redirects=True,
    )
    resp.raise_for_status()
    data = resp.json()
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = (time.monotonic(), data)
    return data


def search_artists(query: str, user_agent: str, limit: int = 8, timeout: float = 4.0) -> list[dict[str, Any]]:
    q = query.replace('"', " ").strip()
    if len(q) < 2:
        return []
    try:
        data = _get("artist/", {"query": f'artist:"{q}" OR alias:"{q}"', "limit": limit}, user_agent, timeout)
    except (httpx.HTTPError, ValueError) as exc:
        log.info("musicbrainz search failed: %s", exc, extra={"event": "musicbrainz.error"})
        return []
    out = []
    for a in data.get("artists", []):
        tags = sorted(a.get("tags") or [], key=lambda t: -int(t.get("count") or 0))
        out.append(
            {
                "mbid": a.get("id"),
                "name": a.get("name"),
                "disambiguation": a.get("disambiguation") or None,
                "country": a.get("country"),
                "type": a.get("type"),
                "score": a.get("score"),
                "genre": tags[0]["name"] if tags else None,
            }
        )
    return out


def lookup_artist(mbid: str, user_agent: str, timeout: float = 8.0) -> dict[str, Any] | None:
    try:
        data = _get(f"artist/{mbid}", {"inc": "url-rels+aliases+genres+tags"}, user_agent, timeout)
    except (httpx.HTTPError, ValueError) as exc:
        log.info("musicbrainz lookup failed: %s", exc, extra={"event": "musicbrainz.error"})
        return None
    urls: dict[str, list[str]] = {}
    for rel in data.get("relations") or []:
        url = (rel.get("url") or {}).get("resource")
        if url:
            urls.setdefault(rel.get("type") or "other", []).append(url)
    genres = sorted(data.get("genres") or data.get("tags") or [], key=lambda g: -int(g.get("count") or 0))
    aliases = [a.get("name") for a in data.get("aliases") or [] if a.get("name")]
    return {
        "mbid": data.get("id"),
        "name": data.get("name"),
        "country": data.get("country"),
        "type": data.get("type"),
        "aliases": aliases,
        "genre": genres[0]["name"] if genres else None,
        "urls": urls,
    }
