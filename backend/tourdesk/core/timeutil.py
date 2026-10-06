"""Time helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Europe/Berlin"


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def local_today(tz: str = DEFAULT_TZ) -> date:
    try:
        return datetime.now(tz=ZoneInfo(tz)).date()
    except ZoneInfoNotFoundError:
        return datetime.now(tz=UTC).date()


def safe_zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
