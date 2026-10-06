"""Tour status detection ("Aktuell auf Tour", "Tour angekündigt", "Derzeit nicht auf Tour").

Uses *all* known events of an artist – not only those matching the user's
filters – so a 15-date tour with only two dates in the user's region is still
recognised as a tour.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

GAP_DAYS = 45
LOOKBACK_DAYS = 120


@dataclass(frozen=True, slots=True)
class TourEvent:
    event_date: date
    tour_id: int | None = None
    tour_name: str | None = None
    event_type: str = "concert"
    status: str = "scheduled"
    is_listed: bool = True
    is_confirmed: bool = True
    city_name: str | None = None


@dataclass(frozen=True, slots=True)
class TourStatus:
    state: str  # on_tour | announced | not_on_tour
    label: str
    emoji: str
    detail: str
    tour_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    event_count: int = 0
    upcoming_count: int = 0
    next_date: date | None = None
    festival_only: bool = False

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "label": self.label,
            "emoji": self.emoji,
            "detail": self.detail,
            "tour_name": self.tour_name,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "event_count": self.event_count,
            "upcoming_count": self.upcoming_count,
            "next_date": self.next_date.isoformat() if self.next_date else None,
            "festival_only": self.festival_only,
        }


def _fmt(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _clusters(events: list[TourEvent]) -> list[list[TourEvent]]:
    clusters: list[list[TourEvent]] = []
    for ev in sorted(events, key=lambda e: e.event_date):
        if clusters:
            last = clusters[-1][-1]
            same_tour = ev.tour_id is not None and any(e.tour_id == ev.tour_id for e in clusters[-1])
            if same_tour or (ev.event_date - last.event_date).days <= GAP_DAYS:
                clusters[-1].append(ev)
                continue
        clusters.append([ev])
    return clusters


def _tour_name(cluster: list[TourEvent]) -> str | None:
    names = Counter(e.tour_name for e in cluster if e.tour_name)
    return names.most_common(1)[0][0] if names else None


def compute_tour_status(events: list[TourEvent], today: date) -> TourStatus:
    relevant = [
        e
        for e in events
        if e.is_listed and e.is_confirmed and e.status != "cancelled" and e.event_date >= today - timedelta(days=LOOKBACK_DAYS)
    ]
    upcoming = [e for e in relevant if e.event_date >= today]
    if not upcoming:
        past = sorted((e for e in events if e.event_date < today and e.status != "cancelled"), key=lambda e: e.event_date)
        detail = f"Letzter bekannter Termin: {_fmt(past[-1].event_date)}" if past else "Keine bekannten Termine"
        return TourStatus("not_on_tour", "Derzeit nicht auf Tour", "⚪", detail)

    for cluster in _clusters(relevant):
        start, end = cluster[0].event_date, cluster[-1].event_date
        cluster_upcoming = [e for e in cluster if e.event_date >= today]
        if not cluster_upcoming:
            continue
        name = _tour_name(cluster)
        festival_only = all(e.event_type == "festival" for e in cluster)
        if start <= today <= end and len(cluster) >= 2:
            what = name or ("Festivalsaison" if festival_only else "Tour")
            n = len(cluster_upcoming)
            noun = "weiterer Termin" if n == 1 else "weitere Termine"
            return TourStatus(
                "on_tour", "Aktuell auf Tour", "🟢",
                f"{what} · {n} {noun} bis {_fmt(end)}",
                tour_name=name, start_date=start, end_date=end, event_count=len(cluster),
                upcoming_count=n, next_date=cluster_upcoming[0].event_date, festival_only=festival_only,
            )
        # first cluster that lies (at least partly) in the future
        n = len(cluster_upcoming)
        first = cluster_upcoming[0].event_date
        if n == 1:
            where = f" in {cluster_upcoming[0].city_name}" if cluster_upcoming[0].city_name else ""
            detail = f"Nächster Termin: {_fmt(first)}{where}"
            if first == today:
                detail = f"Heute live{where}"
        else:
            what = name or ("Festivalsaison" if festival_only else "Tour")
            detail = f"{what} ab {_fmt(first)} · {n} Termine"
        return TourStatus(
            "announced", "Tour angekündigt", "🔵", detail,
            tour_name=name, start_date=start, end_date=end, event_count=len(cluster),
            upcoming_count=n, next_date=first, festival_only=festival_only,
        )
    return TourStatus("not_on_tour", "Derzeit nicht auf Tour", "⚪", "Keine bekannten Termine")  # pragma: no cover
