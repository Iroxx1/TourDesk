"""Hierarchical event filter with human readable explanations.

This module is pure (no database access) so it can be unit tested exhaustively.
``filter_sql.build_event_predicate`` implements the same rules as an SQL
predicate for paginated queries; tests make sure both agree.

Location rules (OR-combined), each on exactly one level:

* ``country`` – the whole country
* ``region``  – the region and all its sub-regions, cities and venues
* ``city``    – all venues of that city
* ``venue``   – only that venue (never the whole city/region/country)

No location rules at all means: no location restriction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from tourdesk.models.enums import TRUST_LABELS

HIDE_STATUSES = {"cancelled", "postponed"}

# "im Saarland" vs. "in Bayern"
_IM_NAMES = {
    "saarland", "burgenland", "elsass", "tessin", "wallis", "aargau", "thurgau", "jura", "baskenland",
    "aostatal", "latium", "piemont", "trentino-südtirol", "venetien", "friaul-julisch venetien",
}


def in_phrase(name: str) -> str:
    return f"im {name}" if name.casefold() in _IM_NAMES else f"in {name}"


@dataclass(frozen=True, slots=True)
class LocationRule:
    id: int
    level: str  # country | region | city | venue
    target_id: int
    label: str
    country_id: int | None = None
    country_label: str | None = None


@dataclass(frozen=True, slots=True)
class FilterProfile:
    rules: tuple[LocationRule, ...] = ()
    # region rule target -> region ids covered (the region itself and all descendants)
    region_coverage: Mapping[int, frozenset[int]] = field(default_factory=dict)
    date_from: date | None = None
    date_to: date | None = None
    include_concerts: bool = True
    include_support: bool = True
    include_special: bool = True
    festival_mode: str = "artist"  # artist | always | never
    festival_scope: str = "filters"  # filters | anywhere
    show_cancelled: bool = True
    show_unconfirmed: bool = False

    @property
    def has_location_rules(self) -> bool:
        return bool(self.rules)

    def covered_regions(self, rule: LocationRule) -> frozenset[int]:
        return self.region_coverage.get(rule.target_id, frozenset({rule.target_id}))

    def ids(self, level: str) -> set[int]:
        if level == "region":
            out: set[int] = set()
            for rule in self.rules:
                if rule.level == "region":
                    out |= self.covered_regions(rule)
            return out
        return {r.target_id for r in self.rules if r.level == level}


@dataclass(frozen=True, slots=True)
class EventFacts:
    artist_id: int
    event_date: date
    event_type: str = "concert"
    status: str = "scheduled"
    is_confirmed: bool = True
    is_listed: bool = True
    source_count: int = 1
    best_trust: int = 1
    id: int | None = None
    venue_id: int | None = None
    venue_name: str | None = None
    city_id: int | None = None
    city_name: str | None = None
    region_id: int | None = None
    region_name: str | None = None
    country_id: int | None = None
    country_name: str | None = None
    festival_name: str | None = None


@dataclass(frozen=True, slots=True)
class ArtistPref:
    artist_id: int
    artist_name: str
    followed: bool = True
    active: bool = True
    show_festivals: bool = False


@dataclass(slots=True)
class Check:
    ok: bool | None  # True = ✓, False = ✗, None = information
    code: str
    message: str

    def as_dict(self) -> dict:
        return {"ok": self.ok, "code": self.code, "message": self.message}


@dataclass(slots=True)
class Decision:
    shown: bool
    location_match: bool
    checks: list[Check]
    matched_rule_ids: list[int]
    hidden_reason: str | None = None

    @property
    def title(self) -> str:
        return "Warum wird dieses Event angezeigt?" if self.shown else "Warum wird dieses Event nicht angezeigt?"

    def as_dict(self) -> dict:
        return {
            "shown": self.shown,
            "title": self.title,
            "location_match": self.location_match,
            "matched_rule_ids": self.matched_rule_ids,
            "hidden_reason": self.hidden_reason,
            "checks": [c.as_dict() for c in self.checks],
        }


def _place(event: EventFacts) -> str:
    parts = [p for p in (event.venue_name, event.city_name) if p]
    return ", ".join(parts) if parts else "unbekannter Ort"


def match_location(event: EventFacts, profile: FilterProfile) -> list[LocationRule]:
    """All location rules matching the event (empty list = no match)."""
    matched: list[LocationRule] = []
    for rule in profile.rules:
        if rule.level == "venue":
            if event.venue_id is not None and event.venue_id == rule.target_id:
                matched.append(rule)
        elif rule.level == "city":
            if event.city_id is not None and event.city_id == rule.target_id:
                matched.append(rule)
        elif rule.level == "region":
            if event.region_id is not None and event.region_id in profile.covered_regions(rule):
                matched.append(rule)
        elif rule.level == "country":
            if event.country_id is not None and event.country_id == rule.target_id:
                matched.append(rule)
    return matched


def _location_checks(event: EventFacts, profile: FilterProfile, matched: list[LocationRule]) -> list[Check]:
    checks: list[Check] = []
    if matched:
        for rule in matched:
            if rule.level == "venue":
                checks.append(Check(True, "venue_rule", f"Veranstaltungsort {rule.label} ist bevorzugt"))
            elif rule.level == "city":
                checks.append(Check(True, "city_rule", f"{rule.label} ist eine bevorzugte Stadt"))
            elif rule.level == "region":
                checks.append(Check(True, "region_rule", f"{rule.label} ist bevorzugte Region"))
                where = event.city_name or event.venue_name
                suffix = f" ({where})" if where else ""
                if event.region_name and event.region_id != rule.target_id:
                    checks.append(Check(True, "region_contains",
                                        f"Veranstaltung liegt {in_phrase(event.region_name)}, Teil von {rule.label}{suffix}"))
                else:
                    checks.append(Check(True, "region_contains", f"Veranstaltung liegt {in_phrase(rule.label)}{suffix}"))
            elif rule.level == "country":
                checks.append(Check(True, "country_rule", f"{rule.label} ist komplett ausgewählt"))
        return checks

    # --- explain the miss -----------------------------------------------------------
    if event.venue_name:
        checks.append(Check(False, "venue_not_in_filters", f"Veranstaltungsort {event.venue_name} ist nicht in deinen Filtern"))
    elif event.city_name:
        checks.append(Check(False, "city_not_in_filters", f"{event.city_name} ist nicht in deinen Filtern"))
    else:
        checks.append(Check(False, "location_unknown", "Ort des Events ist unbekannt"))

    if event.country_id is None:
        checks.append(Check(False, "country_unknown", "Land des Events konnte nicht bestimmt werden"))
        return checks

    country = event.country_name or "dieses Land"
    in_country = [r for r in profile.rules if r.country_id == event.country_id]
    if not in_country:
        checks.append(Check(False, "country_no_rules", f"Für {country} sind keine Orte ausgewählt"))
        return checks

    labels = ", ".join(r.label for r in in_country)
    checks.append(Check(False, "country_partial", f"{country} ist nicht komplett ausgewählt – nur: {labels}"))
    region_rules = [r for r in in_country if r.level == "region"]
    if region_rules:
        if event.region_id is None:
            checks.append(Check(False, "region_unknown", "Der Ort konnte keiner Region zugeordnet werden"))
        elif event.region_name:
            checks.append(Check(False, "region_not_selected",
                                f"{event.region_name} gehört nicht zu deinen Regionen ({', '.join(r.label for r in region_rules)})"))
    city_rules = [r for r in in_country if r.level == "city"]
    if city_rules and event.city_name:
        checks.append(Check(False, "city_not_selected",
                            f"{event.city_name} ist keine deiner Städte ({', '.join(r.label for r in city_rules)})"))
    return checks


def evaluate(event: EventFacts, pref: ArtistPref | None, profile: FilterProfile) -> Decision:
    checks: list[Check] = []
    shown = True
    hidden_reason: str | None = None

    def fail(reason: str) -> None:
        nonlocal shown, hidden_reason
        shown = False
        if hidden_reason is None:
            hidden_reason = reason

    # 1. artist ---------------------------------------------------------------------
    if pref is None or not pref.followed:
        checks.append(Check(False, "artist_not_followed", "Künstler wird nicht überwacht"))
        fail("Künstler nicht überwacht")
    else:
        checks.append(Check(True, "artist_followed", f"Künstler überwacht ({pref.artist_name})"))
        if not pref.active:
            checks.append(Check(False, "artist_inactive", "Künstler ist deaktiviert"))
            fail("Künstler deaktiviert")

    # 2. listing ----------------------------------------------------------------------
    if event.is_listed:
        noun = "Quelle" if event.source_count == 1 else "Quellen"
        checks.append(Check(True, "event_found", f"Event gefunden ({event.source_count} {noun})"))
    else:
        checks.append(Check(False, "event_delisted", "Event wird von keiner Quelle mehr gelistet"))
        fail("Nicht mehr gelistet")

    # 3. date -------------------------------------------------------------------------
    if profile.date_from and event.event_date < profile.date_from:
        checks.append(Check(False, "date_past", "Termin liegt vor dem gewählten Zeitraum"))
        fail("Außerhalb des Zeitraums")
    elif profile.date_to and event.event_date > profile.date_to:
        checks.append(Check(False, "date_after", f"Termin liegt nach dem gewählten Zeitraum (bis {profile.date_to:%d.%m.%Y})"))
        fail("Außerhalb des Zeitraums")
    else:
        checks.append(Check(True, "date_ok", "Datum liegt im gewählten Zeitraum"))

    # 4. status -----------------------------------------------------------------------
    if event.status in HIDE_STATUSES:
        label = "abgesagt" if event.status == "cancelled" else "verschoben"
        if profile.show_cancelled:
            checks.append(Check(None, "status_flagged", f"Event ist {label} (wird gekennzeichnet)"))
        else:
            checks.append(Check(False, "status_hidden", f"Event ist {label} – abgesagte/verschobene Termine sind ausgeblendet"))
            fail("Abgesagt/verschoben")
    elif event.status == "rescheduled":
        checks.append(Check(None, "status_rescheduled", "Termin wurde auf dieses Datum verlegt"))

    # 5. type / festival ------------------------------------------------------------
    is_festival = event.event_type == "festival"
    if is_festival:
        name = f" ({event.festival_name})" if event.festival_name else ""
        if profile.festival_mode == "never":
            checks.append(Check(False, "festival_never", f"Festival{name} – Festivals sind generell ausgeblendet"))
            fail("Festival ausgeblendet")
        elif profile.festival_mode == "always":
            checks.append(Check(True, "festival_always", f"Festival{name} – Festivals sind generell eingeblendet"))
        elif pref is not None and pref.show_festivals:
            checks.append(Check(True, "festival_switch_on", f"Festival{name} – Festival-Schalter für {pref.artist_name} ist AN"))
        else:
            artist = pref.artist_name if pref else "den Künstler"
            checks.append(Check(False, "festival_switch_off", f"Festival{name} – Festival-Schalter für {artist} ist AUS"))
            fail("Festival ausgeblendet")
    elif event.event_type == "support":
        if profile.include_support:
            checks.append(Check(True, "type_support", "Support-Auftritt – kein Festivalfilter notwendig"))
        else:
            checks.append(Check(False, "type_support_hidden", "Support-Auftritte sind ausgeblendet"))
            fail("Support ausgeblendet")
    elif event.event_type == "special":
        if profile.include_special:
            checks.append(Check(True, "type_special", "Special Event – kein Festivalfilter notwendig"))
        else:
            checks.append(Check(False, "type_special_hidden", "Special Events sind ausgeblendet"))
            fail("Special Event ausgeblendet")
    else:
        if profile.include_concerts:
            checks.append(Check(True, "type_concert", "Konzert – kein Festivalfilter notwendig"))
        else:
            checks.append(Check(False, "type_concert_hidden", "Konzerte sind ausgeblendet"))
            fail("Konzerte ausgeblendet")

    # 6. location ---------------------------------------------------------------------
    matched: list[LocationRule] = []
    if is_festival and profile.festival_scope == "anywhere":
        location_match = True
        checks.append(Check(True, "festival_anywhere", f"Festivals werden unabhängig vom Ort angezeigt ({_place(event)})"))
    elif not profile.has_location_rules:
        location_match = True
        checks.append(Check(True, "no_location_rules", "Keine Ortsfilter definiert – alle Orte"))
    else:
        matched = match_location(event, profile)
        location_match = bool(matched)
        checks.extend(_location_checks(event, profile, matched))
        if not location_match:
            fail("Außerhalb deiner Filter")

    # 7. confirmation -------------------------------------------------------------
    if event.is_confirmed:
        trust = TRUST_LABELS.get(event.best_trust, "Quelle")
        if event.source_count >= 2:
            checks.append(Check(True, "confirmed", f"Event bestätigt – {event.source_count} Quellen bestätigen diesen Termin"))
        elif event.best_trust <= 4:
            checks.append(Check(True, "confirmed", f"Event offiziell bestätigt (Quelle: {trust})"))
        else:
            checks.append(Check(True, "confirmed", "Event bestätigt"))
    elif profile.show_unconfirmed:
        checks.append(Check(None, "unconfirmed_flagged", "Event ist nicht bestätigt (wird gekennzeichnet)"))
    else:
        checks.append(Check(False, "unconfirmed", "Event ist nicht bestätigt (nur unsichere Quelle)"))
        fail("Unbestätigt")

    return Decision(
        shown=shown,
        location_match=location_match,
        checks=checks,
        matched_rule_ids=[r.id for r in matched],
        hidden_reason=None if shown else hidden_reason,
    )
