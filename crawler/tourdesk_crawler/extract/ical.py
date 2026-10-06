"""iCalendar (.ics) feed extraction."""

from __future__ import annotations

from datetime import date, datetime

from icalendar import Calendar

from tourdesk.core.text import clean_text, safe_url
from tourdesk_crawler.pipeline.models import RawEvent


def extract_ical(content: bytes | str) -> list[RawEvent]:
    if isinstance(content, str):
        content = content.encode("utf-8", errors="replace")
    try:
        cal = Calendar.from_ical(content)
    except Exception:
        return []
    events: list[RawEvent] = []
    for comp in cal.walk("VEVENT"):
        start = comp.get("DTSTART")
        if start is None:
            continue
        value = start.dt
        if isinstance(value, datetime):
            tz = value.tzinfo
            ev = RawEvent(start_date=value.date(), start_time=value.time().replace(tzinfo=None), method="ical", confidence=0.85)
            ev.extra["tzinfo"] = tz
        elif isinstance(value, date):
            ev = RawEvent(start_date=value, method="ical", confidence=0.85)
        else:
            continue
        end = comp.get("DTEND")
        if end is not None:
            end_value = end.dt
            end_d = end_value.date() if isinstance(end_value, datetime) else end_value
            # all-day events end exclusive
            if isinstance(end_value, date) and not isinstance(end_value, datetime):
                from datetime import timedelta

                end_d = end_value - timedelta(days=1)
            if isinstance(end_d, date) and end_d > ev.start_date:
                ev.end_date = end_d
        ev.title = clean_text(str(comp.get("SUMMARY") or ""), 300)
        ev.description = clean_text(str(comp.get("DESCRIPTION") or ""), 1000)
        location = clean_text(str(comp.get("LOCATION") or ""), 300)
        if location:
            parts = [p.strip() for p in location.split(",") if p.strip()]
            ev.venue_name = parts[0][:200] if parts else None
            if len(parts) >= 2:
                city = parts[-1] if len(parts) == 2 else parts[-2]
                ev.city = clean_text(city.lstrip("0123456789 -").strip(), 160)
            if len(parts) >= 3:
                ev.country = clean_text(parts[-1], 60)
        url = comp.get("URL")
        ev.url = safe_url(str(url)) if url else None
        status = str(comp.get("STATUS") or "").upper()
        if status == "CANCELLED":
            ev.status = "cancelled"
        uid = comp.get("UID")
        ev.external_id = str(uid)[:200] if uid else None
        ev.raw_date = str(start.to_ical().decode() if hasattr(start, "to_ical") else value)
        events.append(ev)
    return events
