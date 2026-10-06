"""Central runtime configuration stored in ``app_settings`` (editable by admins)."""

from __future__ import annotations

import copy
import threading
import time
from typing import Any

from sqlalchemy.orm import Session

from tourdesk.core.config import get_settings
from tourdesk.models import AppSetting


def _defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "enabled": True,
        "interval_minutes": s.crawler_interval_minutes,
        "user_agent": s.crawler_user_agent,
        "contact": s.crawler_contact or "",
        "respect_robots": True,
        "min_domain_interval_s": 3.0,
        "timeout_s": 20,
        "max_retries": 2,
        "max_response_mb": 5,
        "cache_ttl_minutes": 30,
        "max_pages_per_source": 3,
        "allow_private_networks": s.crawler_allow_private_networks,
        "worker_threads": s.worker_threads,
        "enrich_interval_days": 14,
        "source_backoff_max_hours": 24,
        "geocoder_enabled": s.geocoder_enabled,
        "geocoder_url": s.geocoder_url,
        "musicbrainz_lookup": True,
        "image_providers": ["official", "wikidata", "deezer"],
        "ticketmaster_countries": ["DE", "LU", "FR", "BE", "NL", "AT", "CH"],
        "keep_runs_days": 30,
        "providers": {
            "official_website": True,
            "tour_page": True,
            "generic_web": True,
            "ical_feed": True,
            "ticketmaster": True,
            "bandsintown": True,
            "songkick": True,
            "venue_website": True,
            "festival_lineup": True,
            "promoter_website": True,
            "ticket_listing": True,
            "demo": True,
        },
        "api_keys": {"ticketmaster": "", "bandsintown": "", "songkick": ""},
    }


_EDITABLE_TYPES: dict[str, type | tuple[type, ...]] = {
    "enabled": bool,
    "interval_minutes": int,
    "user_agent": str,
    "contact": str,
    "respect_robots": bool,
    "min_domain_interval_s": (int, float),
    "timeout_s": (int, float),
    "max_retries": int,
    "max_response_mb": (int, float),
    "cache_ttl_minutes": int,
    "max_pages_per_source": int,
    "allow_private_networks": bool,
    "worker_threads": int,
    "enrich_interval_days": int,
    "source_backoff_max_hours": int,
    "geocoder_enabled": bool,
    "geocoder_url": str,
    "musicbrainz_lookup": bool,
    "image_providers": list,
    "ticketmaster_countries": list,
    "keep_runs_days": int,
    "providers": dict,
    "api_keys": dict,
}
_LIMITS = {
    "interval_minutes": (10, 24 * 60),
    "min_domain_interval_s": (1, 120),
    "timeout_s": (3, 120),
    "max_retries": (0, 5),
    "max_response_mb": (1, 50),
    "cache_ttl_minutes": (0, 24 * 60),
    "max_pages_per_source": (1, 10),
    "worker_threads": (1, 16),
    "enrich_interval_days": (1, 365),
    "source_backoff_max_hours": (1, 168),
    "keep_runs_days": (1, 365),
}

_cache: dict[str, Any] = {}
_cache_at = 0.0
_lock = threading.Lock()
CACHE_SECONDS = 30


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out


def crawler_settings(db: Session, *, fresh: bool = False) -> dict[str, Any]:
    global _cache, _cache_at
    with _lock:
        if not fresh and _cache and time.monotonic() - _cache_at < CACHE_SECONDS:
            return copy.deepcopy(_cache)
    row = db.get(AppSetting, "crawler")
    merged = _merge(_defaults(), row.value if row else {})
    with _lock:
        _cache, _cache_at = merged, time.monotonic()
    return copy.deepcopy(merged)


def invalidate_cache() -> None:
    global _cache_at
    with _lock:
        _cache_at = 0.0


def api_key(db: Session, name: str) -> str | None:
    s = get_settings()
    env_value = {
        "ticketmaster": s.ticketmaster_api_key,
        "bandsintown": s.bandsintown_app_id,
        "songkick": s.songkick_api_key,
    }.get(name)
    if env_value is not None and env_value.get_secret_value():
        return env_value.get_secret_value()
    value = (crawler_settings(db).get("api_keys") or {}).get(name)
    return value or None


def update_crawler_settings(db: Session, patch: dict[str, Any], user_id: int | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    defaults = _defaults()
    for key, value in patch.items():
        expected = _EDITABLE_TYPES.get(key)
        if expected is None or value is None:
            continue
        if expected in (int, (int, float)) and isinstance(value, bool):
            continue
        if not isinstance(value, expected):
            raise ValueError(f"Ungültiger Wert für {key}")
        if key in _LIMITS:
            lo, hi = _LIMITS[key]
            if not lo <= value <= hi:
                raise ValueError(f"{key} muss zwischen {lo} und {hi} liegen")
        if key == "providers":
            value = {k: bool(v) for k, v in value.items() if k in defaults["providers"]}
        if key == "api_keys":
            value = {k: str(v).strip() for k, v in value.items() if k in defaults["api_keys"] and v != "********"}
        if key == "ticketmaster_countries":
            value = [str(v).upper()[:2] for v in value if isinstance(v, str)][:30]
        if key == "image_providers":
            value = [v for v in value if v in ("official", "wikidata", "deezer")]
        if key in ("user_agent", "contact", "geocoder_url"):
            value = value.strip()[:300]
        clean[key] = value
    row = db.get(AppSetting, "crawler")
    if row is None:
        row = AppSetting(key="crawler", value={}, updated_by_user_id=user_id)
        db.add(row)
    current = dict(row.value or {})
    for key, value in clean.items():
        if isinstance(value, dict):
            current[key] = {**(current.get(key) or {}), **value}
        else:
            current[key] = value
    row.value = current
    row.updated_by_user_id = user_id
    db.flush()
    invalidate_cache()
    return crawler_settings(db, fresh=True)


def public_crawler_settings(db: Session) -> dict[str, Any]:
    """Settings for the admin UI with API keys masked."""
    data = crawler_settings(db)
    s = get_settings()
    env = {
        "ticketmaster": bool(s.ticketmaster_api_key and s.ticketmaster_api_key.get_secret_value()),
        "bandsintown": bool(s.bandsintown_app_id and s.bandsintown_app_id.get_secret_value()),
        "songkick": bool(s.songkick_api_key and s.songkick_api_key.get_secret_value()),
    }
    data["api_keys"] = {k: ("********" if v else "") for k, v in (data.get("api_keys") or {}).items()}
    data["api_keys_from_env"] = env
    return data
