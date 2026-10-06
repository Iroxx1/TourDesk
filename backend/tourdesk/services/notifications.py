"""Notification service.

Notifications are created in-app. External channels (e-mail, Telegram, Discord,
push, WhatsApp …) plug in via :class:`NotificationChannel` and the
``notification_channels`` / ``notification_deliveries`` tables.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tourdesk.core.timeutil import utcnow
from tourdesk.models import Event, Notification, NotificationChannel, NotificationDelivery, User, UserArtist, UserSettings
from tourdesk.models.user import DEFAULT_NOTIFICATION_SETTINGS
from tourdesk.services.filter_engine import ArtistPref, FilterProfile, evaluate
from tourdesk.services.filters import event_facts, load_profile

log = logging.getLogger("tourdesk.api")


# ----------------------------------------------------------------------------------- channels
class NotificationChannelHandler(Protocol):
    kind: str

    def deliver(self, notification: Notification, channel: NotificationChannel) -> None: ...


_CHANNEL_HANDLERS: dict[str, NotificationChannelHandler] = {}


def register_channel(handler: NotificationChannelHandler) -> None:
    """Register an external channel implementation (e.g. e-mail, Telegram)."""
    _CHANNEL_HANDLERS[handler.kind] = handler


def _queue_external(db: Session, notification: Notification) -> None:
    channels = db.execute(
        select(NotificationChannel).where(
            NotificationChannel.user_id == notification.user_id, NotificationChannel.is_enabled.is_(True)
        )
    ).scalars().all()
    for ch in channels:
        if ch.types and notification.type not in ch.types:
            continue
        if ch.kind not in _CHANNEL_HANDLERS:
            continue
        db.add(NotificationDelivery(notification_id=notification.id, channel_id=ch.id, status="pending"))


# ----------------------------------------------------------------------------------- creation
def notify(
    db: Session,
    user_id: int,
    type_: str,
    title: str,
    *,
    body: str | None = None,
    artist_id: int | None = None,
    event_id: int | None = None,
    data: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> int | None:
    stmt = pg_insert(Notification).values(
        user_id=user_id,
        type=type_,
        title=title[:300],
        body=body,
        artist_id=artist_id,
        event_id=event_id,
        data=data or {},
        dedupe_key=dedupe_key,
    )
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
    new_id = db.execute(stmt.returning(Notification.id)).scalar()
    if new_id is not None:
        db.flush()
        notification = db.get(Notification, new_id)
        if notification is not None:
            _queue_external(db, notification)
    return new_id


@dataclass
class EventChange:
    kind: str  # created | changed | cancelled | postponed | rescheduled | tickets_on_sale | delisted
    event_id: int
    fields: dict[str, tuple[Any, Any]] = field(default_factory=dict)


def _fmt_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _where(e: Event) -> str:
    venue = e.venue.name if e.venue else e.venue_name
    city = e.city.display_name if e.city else e.city_name
    return " – ".join(p for p in (venue, city) if p) or "Ort folgt"


FIELD_LABELS = {
    "event_date": "Datum",
    "start_time": "Beginn",
    "venue": "Veranstaltungsort",
    "city": "Stadt",
    "status": "Status",
    "ticket_status": "Ticketstatus",
}


def dispatch_changes(db: Session, artist_id: int, changes: list[EventChange]) -> int:
    """Create notifications for all subscribers of ``artist_id``. Returns count."""
    if not changes:
        return 0
    subs = db.execute(
        select(UserArtist).join(User, User.id == UserArtist.user_id).where(
            UserArtist.artist_id == artist_id, UserArtist.is_active.is_(True), User.is_active.is_(True)
        )
    ).unique().scalars().all()
    if not subs:
        return 0
    events = {
        e.id: e
        for e in db.execute(select(Event).where(Event.id.in_({c.event_id for c in changes}))).unique().scalars()
    }
    created = 0
    for ua in subs:
        if not ua.notify:
            continue
        settings = db.get(UserSettings, ua.user_id)
        enabled = {**DEFAULT_NOTIFICATION_SETTINGS, **((settings.notifications if settings else None) or {})}
        profile, _f = load_profile(db, ua.user)
        pref = ArtistPref(artist_id=artist_id, artist_name=ua.artist.name, active=ua.is_active, show_festivals=ua.show_festivals)
        baseline_done = ua.baseline_completed_at is not None
        new_matching: list[Event] = []
        for change in changes:
            event = events.get(change.event_id)
            if event is None:
                continue
            created += _notify_for_change(db, ua, event, change, profile, pref, enabled, baseline_done, new_matching)
        if new_matching and enabled.get("new_events") and baseline_done:
            n = len(new_matching)
            first = min(new_matching, key=lambda e: e.event_date)
            title = f"{ua.artist.name}: {n} neue{'r' if n == 1 else ''} Termin{'e' if n > 1 else ''}"
            body = f"Nächster: {_fmt_date(first.event_date)} · {_where(first)}"
            key = f"new:{artist_id}:" + ",".join(str(e.id) for e in sorted(new_matching, key=lambda e: e.id))[:150]
            if notify(db, ua.user_id, "new_events", title, body=body, artist_id=artist_id, event_id=first.id,
                      data={"event_ids": [e.id for e in new_matching]}, dedupe_key=key):
                created += 1
    return created


def _notify_for_change(
    db: Session,
    ua: UserArtist,
    event: Event,
    change: EventChange,
    profile: FilterProfile,
    pref: ArtistPref,
    enabled: dict[str, Any],
    baseline_done: bool,
    new_matching: list[Event],
) -> int:
    decision = evaluate(event_facts(event), pref, profile)
    artist = ua.artist.name
    when = _fmt_date(event.event_date)
    where = _where(event)
    if change.kind == "created":
        if not baseline_done or not decision.shown:
            return 0
        if event.event_type == "festival":
            if enabled.get("festival_confirmed"):
                fest = event.festival.name if event.festival else "einem Festival"
                return 1 if notify(db, ua.user_id, "festival_confirmed", f"{artist} spielt bei {fest}",
                                   body=f"{when} · {where}", artist_id=event.artist_id, event_id=event.id,
                                   dedupe_key=f"fest:{event.id}") else 0
            return 0
        if profile.has_location_rules and decision.location_match and enabled.get("event_in_region"):
            return 1 if notify(db, ua.user_id, "event_in_region", f"Konzert in deiner Region: {artist}",
                               body=f"{when} · {where}", artist_id=event.artist_id, event_id=event.id,
                               dedupe_key=f"region:{event.id}") else 0
        new_matching.append(event)
        return 0
    if not decision.location_match and change.kind != "cancelled":
        return 0
    if change.kind in ("cancelled", "postponed"):
        if not enabled.get("event_cancelled") or not decision.location_match:
            return 0
        label = "abgesagt" if change.kind == "cancelled" else "verschoben"
        return 1 if notify(db, ua.user_id, "event_cancelled", f"{artist}: Konzert {label}",
                           body=f"{when} · {where}", artist_id=event.artist_id, event_id=event.id,
                           dedupe_key=f"{change.kind}:{event.id}") else 0
    if change.kind == "tickets_on_sale" and decision.shown and enabled.get("tickets_on_sale"):
        return 1 if notify(db, ua.user_id, "tickets_on_sale", f"Tickets verfügbar: {artist}",
                           body=f"{when} · {where}", artist_id=event.artist_id, event_id=event.id,
                           dedupe_key=f"tickets:{event.id}") else 0
    if change.kind in ("changed", "rescheduled") and decision.shown and enabled.get("event_changed"):
        parts = []
        for key, (old, new) in change.fields.items():
            label = FIELD_LABELS.get(key, key)
            parts.append(f"{label}: {old or '–'} → {new or '–'}")
        digest = hashlib.sha1(repr(sorted((k, str(v)) for k, v in change.fields.items())).encode()).hexdigest()[:12]
        return 1 if notify(db, ua.user_id, "event_changed", f"{artist}: Termin geändert",
                           body=f"{when} · {where}" + (f"\n{'; '.join(parts)}" if parts else ""),
                           artist_id=event.artist_id, event_id=event.id,
                           dedupe_key=f"changed:{event.id}:{digest}") else 0
    return 0


def complete_baselines(db: Session, artist_id: int) -> None:
    db.execute(
        update(UserArtist)
        .where(UserArtist.artist_id == artist_id, UserArtist.baseline_completed_at.is_(None))
        .values(baseline_completed_at=utcnow())
    )
