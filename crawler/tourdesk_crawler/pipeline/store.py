"""EventDeduplicator + EventMerger.

Every source observation is stored in ``event_sources``. Observations that describe
the same real-world event (same artist, same day, same venue/city – with fuzzy
matching) are attached to the same ``events`` row. The canonical event fields are
recomputed from all *active* observations, preferring the most trustworthy source.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from tourdesk.core.text import normalize_name, url_domain
from tourdesk.core.timeutil import safe_zone
from tourdesk.models import Event, EventSource, TicketSource, Tour
from tourdesk.services.notifications import EventChange
from tourdesk_crawler.pipeline.models import NormalizedEvent, SourceSpec

OFFICIAL_TRUST = 4
TICKET_TRUST_ORDER = {4: 0, 2: 1, 1: 2, 3: 3, 5: 4, 6: 5}
ON_SALE = {"available", "limited"}
NOT_YET = {"unknown", "not_on_sale", "presale"}


def _snapshot(e: Event) -> tuple:
    return (e.event_date, e.start_time, e.venue_id, e.city_id, e.status, e.ticket_status, e.is_listed, e.event_type, e.is_confirmed)


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        h, m = value.split(":")[:2]
        return time(int(h), int(m))
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class EventStore:
    def __init__(self, db: Session, artist_id: int, *, today: date, now: datetime) -> None:
        self.db = db
        self.artist_id = artist_id
        self.today = today
        self.now = now
        events = list(
            db.execute(
                select(Event).where(Event.artist_id == artist_id, Event.event_date >= today - timedelta(days=400))
            ).unique().scalars()
        )
        self.events: list[Event] = events
        self.by_date: dict[date, list[Event]] = defaultdict(list)
        for e in events:
            self.by_date[e.event_date].append(e)
        self.snapshots: dict[int, tuple] = {e.id: _snapshot(e) for e in events}
        self.snapshot_names: dict[int, tuple[str | None, str | None]] = {e.id: (e.venue_name, e.city_name) for e in events}
        self.observations: dict[tuple[int, str], EventSource] = {}
        if events:
            for obs in db.execute(select(EventSource).where(EventSource.event_id.in_([e.id for e in events]))).unique().scalars():
                self.observations[(obs.source_id, obs.obs_key)] = obs
        self.touched: dict[int, Event] = {}
        self.created: set[int] = set()
        self.seen_obs: set[int] = set()
        self._tours: dict[str, Tour] = {}

    # ------------------------------------------------------------------ dedup
    def _loc_similar(self, a: Event, n: NormalizedEvent) -> bool | None:
        """True = same place, False = different place, None = not comparable."""
        if a.venue_id and n.venue_id:
            if a.venue_id == n.venue_id:
                return True
            if a.city_id and n.city_id and a.city_id == n.city_id:
                an, bn = normalize_name(a.venue_name), normalize_name(n.venue_name)
                if an and bn and fuzz.token_set_ratio(an, bn) >= 85:
                    return True
            return False
        if a.city_id and n.city_id:
            return a.city_id == n.city_id
        ac, nc = normalize_name(a.city_name), normalize_name(n.city_name)
        if ac and nc:
            return ac == nc or fuzz.ratio(ac, nc) >= 90
        av, nv = normalize_name(a.venue_name), normalize_name(n.venue_name)
        if av and nv:
            return fuzz.token_set_ratio(av, nv) >= 85
        return None

    def find_match(self, n: NormalizedEvent) -> Event | None:
        candidates = self.by_date.get(n.event_date, [])
        if n.festival_id:
            for delta in range(-4, 5):
                for e in self.by_date.get(n.event_date + timedelta(days=delta), []):
                    if e.festival_id == n.festival_id:
                        return e
        uncertain: list[Event] = []
        for e in candidates:
            same = self._loc_similar(e, n)
            if same is True:
                return e
            if same is None:
                uncertain.append(e)
        if len(candidates) == 1 and uncertain:
            return uncertain[0]
        return None

    # ------------------------------------------------------------------ add observation
    def add(self, n: NormalizedEvent, source: SourceSpec) -> tuple[Event, bool]:
        key = (source.id, n.obs_key)
        obs = self.observations.get(key)
        created = False
        if obs is not None:
            event = obs.event
            if event.event_date != n.event_date:
                match = self.find_match(n)
                if match is not None and match.id != event.id:
                    self._relink(obs, match)
                    event = match
                elif any(o.is_active and o.id != obs.id for o in event.observations):
                    event = self._new_event(n)
                    created = True
                    self._relink(obs, event)
            self._update_obs(obs, n, source)
        else:
            event = self.find_match(n)
            if event is None:
                event = self._new_event(n)
                created = True
            obs = EventSource(
                event=event,
                source_id=source.id,
                obs_key=n.obs_key,
                provider=source.provider,
                trust_level=source.trust_level,
                first_seen_at=self.now,
                last_seen_at=self.now,
                data={},
            )
            self.db.add(obs)
            self._update_obs(obs, n, source)
            self.db.flush()
            self.observations[key] = obs
        self.seen_obs.add(obs.id)
        self.touched[event.id] = event
        return event, created

    def _relink(self, obs: EventSource, event: Event) -> None:
        old = obs.event
        obs.event = event
        self.db.flush()
        if old is not None and old.id != event.id:
            self.touched[old.id] = old

    def _new_event(self, n: NormalizedEvent) -> Event:
        e = Event(
            artist_id=self.artist_id,
            event_date=n.event_date,
            venue_id=n.venue_id,
            city_id=n.city_id,
            region_id=n.region_id,
            country_id=n.country_id,
            venue_name=n.venue_name,
            city_name=n.city_name,
            country_code=n.country_code,
            title=n.title,
            event_type=n.event_type,
            status=n.status,
            ticket_status=n.ticket_status,
            dedup_key=n.dedup_key,
            first_seen_at=self.now,
            last_seen_at=self.now,
            is_listed=True,
        )
        self.db.add(e)
        self.db.flush()
        self.events.append(e)
        self.by_date[e.event_date].append(e)
        self.created.add(e.id)
        return e

    def _update_obs(self, obs: EventSource, n: NormalizedEvent, source: SourceSpec) -> None:
        obs.data = n.data()
        obs.provider = source.provider
        obs.trust_level = source.trust_level
        obs.external_id = n.external_id
        obs.url = n.url
        obs.domain = url_domain(n.url) or url_domain(source.url) or source.provider
        obs.raw_title = n.raw_title
        obs.raw_venue = n.raw_venue
        obs.raw_city = n.raw_city
        obs.raw_date = n.raw_date
        obs.last_seen_at = self.now
        obs.is_active = True
        obs.inactive_since = None

    # ------------------------------------------------------------------ finalize
    def deactivate_missing(self, crawled_source_ids: set[int]) -> None:
        """Observations of successfully crawled sources that were not seen again are
        marked inactive – but only for upcoming events (past events naturally vanish)."""
        for (source_id, _key), obs in self.observations.items():
            if source_id not in crawled_source_ids or obs.id in self.seen_obs or not obs.is_active:
                continue
            event = obs.event
            if event is None or event.event_date < self.today:
                continue
            obs.is_active = False
            obs.inactive_since = self.now
            self.touched[event.id] = event

    def finalize(self) -> tuple[list[EventChange], dict[str, int]]:
        changes: list[EventChange] = []
        stats = {"new": 0, "updated": 0, "removed": 0}
        for event in list(self.touched.values()):
            self.db.refresh(event, ["observations"])
            before = self.snapshots.get(event.id)
            self._recompute(event)
            after = _snapshot(event)
            if event.id in self.created and before is None:
                changes.append(EventChange("created", event.id))
                stats["new"] += 1
                continue
            if before is None or before == after:
                continue
            fields: dict[str, tuple[Any, Any]] = {}
            names = ("event_date", "start_time", "venue", "city", "status", "ticket_status", "is_listed", "event_type", "is_confirmed")
            for name, old, new in zip(names, before, after):
                if old != new:
                    fields[name] = (old, new)
            if "is_listed" in fields and fields["is_listed"] == (True, False):
                changes.append(EventChange("delisted", event.id))
                stats["removed"] += 1
                continue
            if "status" in fields and fields["status"][1] in ("cancelled", "postponed", "rescheduled"):
                changes.append(EventChange(fields["status"][1], event.id, {"status": fields["status"]}))
            if "ticket_status" in fields and fields["ticket_status"][0] in NOT_YET and fields["ticket_status"][1] in ON_SALE:
                changes.append(EventChange("tickets_on_sale", event.id))
            moved = {k: v for k, v in fields.items() if k in ("event_date", "start_time", "venue", "city")}
            if moved:
                display = {}
                old_names = self.snapshot_names.get(event.id, (None, None))
                for k, (old, new) in moved.items():
                    if k == "venue":
                        display[k] = (old_names[0], event.venue_name)
                    elif k == "city":
                        display[k] = (old_names[1], event.city_name)
                    else:
                        display[k] = (_fmt(old), _fmt(new))
                changes.append(EventChange("changed", event.id, display))
            if "is_confirmed" in fields and fields["is_confirmed"] == (False, True):
                changes.append(EventChange("created", event.id))
            stats["updated"] += 1
        self._update_tours()
        self.db.flush()
        return changes, stats

    # ------------------------------------------------------------------ merging
    def _tour(self, name: str) -> Tour:
        key = normalize_name(name)
        if key in self._tours:
            return self._tours[key]
        tour = self.db.execute(select(Tour).where(Tour.artist_id == self.artist_id, Tour.name_norm == key)).scalar_one_or_none()
        if tour is None:
            tour = Tour(artist_id=self.artist_id, name=name[:300], name_norm=key[:300], event_count=0)
            self.db.add(tour)
            self.db.flush()
        self._tours[key] = tour
        return tour

    def _recompute(self, e: Event) -> None:
        obs_all = list(e.observations)
        active = [o for o in obs_all if o.is_active]
        if not active:
            if e.event_date >= self.today and e.is_listed:
                e.is_listed = False
                e.delisted_at = self.now
            e.source_count = 0
            e.last_checked_at = self.now
            return
        active.sort(key=lambda o: (o.trust_level, -(o.last_seen_at.timestamp() if o.last_seen_at else 0)))
        best = active[0]
        data = [o.data or {} for o in active]
        bd = data[0]

        e.is_listed = True
        e.delisted_at = None
        new_date = _parse_date(bd.get("date")) or e.event_date
        if new_date != e.event_date:
            old_list = self.by_date.get(e.event_date)
            if old_list and e in old_list:
                old_list.remove(e)
            self.by_date[new_date].append(e)
            e.event_date = new_date
        e.end_date = _parse_date(next((d.get("end_date") for d in data if d.get("end_date")), None))
        e.start_time = _parse_time(next((d.get("start_time") for d in data if d.get("start_time")), None))
        e.doors_time = _parse_time(next((d.get("doors_time") for d in data if d.get("doors_time")), None))

        loc = next((d for d in data if d.get("venue_id")), None) or next((d for d in data if d.get("city_id")), None) or bd
        e.venue_id = loc.get("venue_id")
        e.city_id = loc.get("city_id")
        e.region_id = loc.get("region_id")
        e.country_id = loc.get("country_id") or next((d.get("country_id") for d in data if d.get("country_id")), None)
        e.venue_name = loc.get("venue_name") or next((d.get("venue_name") for d in data if d.get("venue_name")), None)
        e.city_name = loc.get("city_name") or next((d.get("city_name") for d in data if d.get("city_name")), None)
        e.country_code = loc.get("country_code") or next((d.get("country_code") for d in data if d.get("country_code")), None)
        e.timezone = next((d.get("timezone") for d in data if d.get("timezone")), None)
        e.title = next((d.get("title") for d in data if d.get("title")), None)

        official = [(o, o.data or {}) for o in active if o.trust_level <= OFFICIAL_TRUST]
        statuses = [d.get("status") for _o, d in official] or [bd.get("status")]
        if "cancelled" in statuses:
            e.status = "cancelled"
        elif "postponed" in statuses:
            e.status = "postponed"
        elif "rescheduled" in statuses:
            e.status = "rescheduled"
        else:
            e.status = "scheduled"

        by_ticket_trust = sorted(active, key=lambda o: (TICKET_TRUST_ORDER.get(o.trust_level, 9), -(o.last_seen_at.timestamp() if o.last_seen_at else 0)))
        ts = next(((o.data or {}).get("ticket_status") for o in by_ticket_trust if (o.data or {}).get("ticket_status") not in (None, "unknown")), "unknown")
        e.ticket_status = "cancelled" if e.status == "cancelled" and ts in ("unknown", "available", "limited") else ts
        ticket_obs = next((o for o in by_ticket_trust if (o.data or {}).get("ticket_url")), None)
        e.ticket_url = (ticket_obs.data or {}).get("ticket_url") if ticket_obs else None
        e.ticket_provider = (ticket_obs.data or {}).get("ticket_provider") if ticket_obs else None
        onsale = next((d.get("onsale_at") for d in data if d.get("onsale_at")), None)
        e.onsale_at = datetime.fromisoformat(onsale) if onsale else None

        festival_id = next((d.get("festival_id") for d in data if d.get("festival_id")), None)
        types = [d.get("event_type") for d in data]
        if festival_id or "festival" in types:
            e.event_type = "festival"
        elif bd.get("event_type") in ("support", "special"):
            e.event_type = bd["event_type"]
        elif any((o.data or {}).get("event_type") == "support" for o in active if o.trust_level <= 2):
            e.event_type = "support"
        elif "special" in types:
            e.event_type = "special"
        else:
            e.event_type = "concert"
        e.festival_id = festival_id

        tour_name = next((d.get("tour_name") for d in data if d.get("tour_name")), None)
        e.tour_id = self._tour(tour_name).id if tour_name and e.event_type != "festival" else None

        distinct_sources = {o.source_id for o in active}
        distinct_domains = {o.domain or str(o.source_id) for o in active}
        best_trust = min(o.trust_level for o in active)
        if e.event_type == "festival":
            e.is_confirmed = best_trust <= OFFICIAL_TRUST
        else:
            e.is_confirmed = best_trust <= OFFICIAL_TRUST or len(distinct_domains) >= 2
        base = max(float((o.data or {}).get("confidence") or 0.5) for o in active)
        e.confidence = min(1.0, base + 0.1 * (len(distinct_domains) - 1))
        e.source_count = len(distinct_sources)
        e.best_trust = best_trust
        e.primary_source_url = bd.get("url") or (best.source.url if best.source else None)
        e.last_seen_at = self.now
        e.last_checked_at = self.now
        e.dedup_key = e.dedup_key or f"{e.artist_id}|{e.event_date}"
        tz = safe_zone(e.timezone)
        e.starts_at = datetime.combine(e.event_date, e.start_time, tz) if (e.start_time and tz) else None
        if _snapshot(e) != self.snapshots.get(e.id):
            e.last_changed_at = self.now
        self._sync_tickets(e, active)

    def _sync_tickets(self, e: Event, active: list[EventSource]) -> None:
        wanted: dict[str, dict[str, Any]] = {}
        for o in active:
            d = o.data or {}
            url = d.get("ticket_url")
            if not url or url in wanted:
                continue
            wanted[url] = {
                "provider": d.get("ticket_provider") or (o.source.name if o.source else o.provider),
                "status": d.get("ticket_status") or "unknown",
                "trust": o.trust_level,
                "price_min": d.get("price_min"),
                "price_max": d.get("price_max"),
                "currency": d.get("currency"),
            }
        existing = {t.url: t for t in e.tickets}
        for url, info in wanted.items():
            t = existing.get(url)
            if t is None:
                t = TicketSource(event=e, url=url[:1000], first_seen_at=self.now, last_seen_at=self.now, provider=info["provider"][:100])
                self.db.add(t)
            t.provider = str(info["provider"])[:100]
            t.status = info["status"]
            t.trust_level = info["trust"]
            t.price_min = Decimal(str(info["price_min"])) if info["price_min"] is not None else None
            t.price_max = Decimal(str(info["price_max"])) if info["price_max"] is not None else None
            t.currency = info["currency"]
            t.is_active = True
            t.last_seen_at = self.now
        for url, t in existing.items():
            if url not in wanted:
                t.is_active = False

    def _update_tours(self) -> None:
        tours = self.db.execute(select(Tour).where(Tour.artist_id == self.artist_id)).scalars().all()
        for tour in tours:
            dates = [e.event_date for e in self.events if e.tour_id == tour.id and e.is_listed and e.status != "cancelled"]
            tour.event_count = len(dates)
            tour.start_date = min(dates) if dates else None
            tour.end_date = max(dates) if dates else None


def _fmt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    return str(value)
