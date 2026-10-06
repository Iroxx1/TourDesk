"""Filter engine tests incl. the scenarios from the requirements (Saarland / Luxembourg)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tourdesk.services.filter_engine import ArtistPref, EventFacts, FilterProfile, LocationRule, evaluate

TODAY = date(2026, 10, 6)

# --- tiny fake geography ----------------------------------------------------------
DE, LU, FR, BE = 1, 2, 3, 4
SAARLAND, RLP, LU_ESCH, LU_LUX, GRAND_EST, WALLONIA = 10, 11, 20, 21, 30, 40
SAARBRUECKEN, NEUNKIRCHEN, TRIER, ESCH, LUXEMBOURG, METZ, STRASBOURG, NANCY, LIEGE = 100, 101, 102, 200, 201, 300, 301, 302, 400
ROCKHAL, LUXEXPO, DEN_ATELIER, GARAGE, BAM, FORUM = 1000, 1001, 1002, 1003, 1004, 1005

NAMES = {
    DE: "Deutschland", LU: "Luxemburg", FR: "Frankreich", BE: "Belgien",
    SAARLAND: "Saarland", RLP: "Rheinland-Pfalz", LU_ESCH: "Kanton Esch", LU_LUX: "Kanton Luxemburg",
    GRAND_EST: "Grand Est", WALLONIA: "Wallonien",
}
CITY = {
    SAARBRUECKEN: ("Saarbrücken", SAARLAND, DE), NEUNKIRCHEN: ("Neunkirchen", SAARLAND, DE),
    TRIER: ("Trier", RLP, DE), ESCH: ("Esch-sur-Alzette", LU_ESCH, LU), LUXEMBOURG: ("Luxemburg", LU_LUX, LU),
    METZ: ("Metz", GRAND_EST, FR), STRASBOURG: ("Straßburg", GRAND_EST, FR), NANCY: ("Nancy", GRAND_EST, FR),
    LIEGE: ("Lüttich", WALLONIA, BE),
}
VENUE = {
    ROCKHAL: ("Rockhal", ESCH), LUXEXPO: ("Luxexpo The Box", LUXEMBOURG), DEN_ATELIER: ("den Atelier", LUXEMBOURG),
    GARAGE: ("Garage", SAARBRUECKEN), BAM: ("BAM", METZ), FORUM: ("Le Forum", LIEGE),
}


def ev(*, city: int | None = None, venue: int | None = None, artist: int = 1, days: int = 30, **kw) -> EventFacts:
    venue_name = None
    if venue is not None:
        venue_name, city = VENUE[venue]
    city_name, region, country = CITY[city] if city is not None else (None, None, None)
    return EventFacts(
        artist_id=artist,
        event_date=TODAY + timedelta(days=days),
        venue_id=venue,
        venue_name=venue_name,
        city_id=city,
        city_name=city_name,
        region_id=region,
        region_name=NAMES.get(region) if region else None,
        country_id=country,
        country_name=NAMES.get(country) if country else None,
        **kw,
    )


def rule(rid: int, level: str, target: int) -> LocationRule:
    if level == "venue":
        label = VENUE[target][0]
        country = CITY[VENUE[target][1]][2]
    elif level == "city":
        label, _, country = CITY[target]
    elif level == "region":
        label = NAMES[target]
        country = next(c for (_, r, c) in CITY.values() if r == target)
    else:
        label, country = NAMES[target], target
    return LocationRule(id=rid, level=level, target_id=target, label=label, country_id=country, country_label=NAMES[country])


def profile(*rules: LocationRule, **kw) -> FilterProfile:
    return FilterProfile(rules=tuple(rules), date_from=TODAY, **kw)


PREF = ArtistPref(artist_id=1, artist_name="Backstreet Boys", show_festivals=True)


# --- requirement: Saarland complete ---------------------------------------------------
def test_saarland_complete_includes_all_saarland_cities_but_not_trier() -> None:
    p = profile(rule(1, "region", SAARLAND))
    assert evaluate(ev(city=SAARBRUECKEN), PREF, p).shown
    assert evaluate(ev(city=NEUNKIRCHEN), PREF, p).shown
    assert evaluate(ev(venue=GARAGE), PREF, p).shown  # venue inside the region
    trier = evaluate(ev(city=TRIER), PREF, p)
    assert not trier.shown
    assert trier.hidden_reason == "Außerhalb deiner Filter"


def test_region_explanation_mentions_region() -> None:
    d = evaluate(ev(city=SAARBRUECKEN), PREF, profile(rule(1, "region", SAARLAND)))
    messages = [c.message for c in d.checks if c.ok]
    assert "Saarland ist bevorzugte Region" in messages
    assert any(m.startswith("Veranstaltung liegt im Saarland") for m in messages)
    assert d.matched_rule_ids == [1]


# --- requirement: Luxembourg NOT complete ----------------------------------------------
def test_luxembourg_only_selected_venues() -> None:
    p = profile(rule(1, "venue", ROCKHAL), rule(2, "venue", LUXEXPO))
    assert evaluate(ev(venue=ROCKHAL), PREF, p).shown
    assert evaluate(ev(venue=LUXEXPO), PREF, p).shown
    other = evaluate(ev(venue=DEN_ATELIER), PREF, p)
    assert not other.shown
    # an event in the same city as Luxexpo but at another club is not shown either
    assert not evaluate(ev(city=LUXEMBOURG), PREF, p).shown
    # nor in the city of the Rockhal
    assert not evaluate(ev(city=ESCH), PREF, p).shown


def test_luxembourg_partial_explanation() -> None:
    p = profile(rule(1, "venue", ROCKHAL), rule(2, "venue", LUXEXPO))
    d = evaluate(ev(venue=DEN_ATELIER), PREF, p)
    failed = [c.message for c in d.checks if c.ok is False]
    assert "Veranstaltungsort den Atelier ist nicht in deinen Filtern" in failed
    assert "Luxemburg ist nicht komplett ausgewählt – nur: Rockhal, Luxexpo The Box" in failed


def test_venue_rule_never_expands_to_country() -> None:
    p = profile(rule(1, "venue", ROCKHAL))
    assert not evaluate(ev(city=LUXEMBOURG), PREF, p).shown


# --- requirement: combinations -----------------------------------------------------
@pytest.fixture
def combo() -> FilterProfile:
    return profile(
        rule(1, "region", SAARLAND),
        rule(2, "region", RLP),
        rule(3, "venue", ROCKHAL),
        rule(4, "venue", LUXEXPO),
        rule(5, "city", METZ),
        rule(6, "city", STRASBOURG),
        rule(7, "venue", FORUM),
    )


@pytest.mark.parametrize(
    ("event_kwargs", "expected"),
    [
        ({"city": SAARBRUECKEN}, True),
        ({"city": NEUNKIRCHEN}, True),
        ({"city": TRIER}, True),  # RLP complete
        ({"venue": ROCKHAL}, True),
        ({"venue": LUXEXPO}, True),
        ({"venue": DEN_ATELIER}, False),
        ({"city": METZ}, True),
        ({"venue": BAM}, True),  # venue in Metz (city rule)
        ({"city": STRASBOURG}, True),
        ({"city": NANCY}, False),  # Grand Est not complete
        ({"venue": FORUM}, True),
        ({"city": LIEGE}, False),
    ],
)
def test_combined_rules(combo: FilterProfile, event_kwargs: dict, expected: bool) -> None:
    assert evaluate(ev(**event_kwargs), PREF, combo).shown is expected


def test_country_rule() -> None:
    p = profile(rule(1, "country", FR))
    assert evaluate(ev(city=NANCY), PREF, p).shown
    assert not evaluate(ev(city=TRIER), PREF, p).shown


def test_no_rules_means_everywhere() -> None:
    d = evaluate(ev(city=LIEGE), PREF, profile())
    assert d.shown
    assert any(c.code == "no_location_rules" for c in d.checks)


def test_unknown_location_does_not_match_rules() -> None:
    d = evaluate(ev(), PREF, profile(rule(1, "region", SAARLAND)))
    assert not d.shown
    assert any(c.code == "location_unknown" for c in d.checks)


def test_city_without_region_does_not_match_region_rule() -> None:
    e = EventFacts(artist_id=1, event_date=TODAY, city_id=999, city_name="Kleinblittersdorf", country_id=DE, country_name="Deutschland")
    d = evaluate(e, PREF, profile(rule(1, "region", SAARLAND)))
    assert not d.shown
    assert any(c.code == "region_unknown" for c in d.checks)


def test_sub_region_coverage() -> None:
    sub_region = 12  # e.g. a district below Rheinland-Pfalz
    p = FilterProfile(rules=(rule(1, "region", RLP),), region_coverage={RLP: frozenset({RLP, sub_region})}, date_from=TODAY)
    e = EventFacts(artist_id=1, event_date=TODAY, city_id=5, city_name="Bitburg", region_id=sub_region, region_name="Eifelkreis", country_id=DE)
    assert evaluate(e, PREF, p).shown


# --- requirement: festival switch -------------------------------------------------
BSB = ArtistPref(artist_id=1, artist_name="Backstreet Boys", show_festivals=True)
METALLICA = ArtistPref(artist_id=2, artist_name="Metallica", show_festivals=False)
LINKIN = ArtistPref(artist_id=3, artist_name="Linkin Park", show_festivals=True)


def test_festival_switch_per_artist() -> None:
    p = profile()
    fest = dict(city=SAARBRUECKEN, event_type="festival", festival_name="Rock am Ring")
    assert evaluate(ev(**fest), BSB, p).shown
    assert evaluate(ev(**fest, artist=3), LINKIN, p).shown
    d = evaluate(ev(**fest, artist=2), METALLICA, p)
    assert not d.shown
    assert d.hidden_reason == "Festival ausgeblendet"
    assert any("Festival-Schalter für Metallica ist AUS" in c.message for c in d.checks)
    # normal concerts of Metallica are not affected
    assert evaluate(ev(city=SAARBRUECKEN, artist=2), METALLICA, p).shown


def test_festival_global_modes() -> None:
    fest = ev(city=SAARBRUECKEN, event_type="festival", artist=2)
    assert evaluate(fest, METALLICA, profile(festival_mode="always")).shown
    assert not evaluate(ev(city=SAARBRUECKEN, event_type="festival"), BSB, profile(festival_mode="never")).shown


def test_festival_scope_anywhere() -> None:
    p = profile(rule(1, "region", SAARLAND), festival_scope="anywhere")
    assert evaluate(ev(city=LIEGE, event_type="festival"), BSB, p).shown
    assert not evaluate(ev(city=LIEGE), BSB, p).shown  # concerts still filtered


def test_unconfirmed_festival_rumour_not_shown() -> None:
    d = evaluate(ev(city=SAARBRUECKEN, event_type="festival", is_confirmed=False, best_trust=6), BSB, profile())
    assert not d.shown
    assert d.hidden_reason == "Unbestätigt"


# --- other criteria ------------------------------------------------------------------
def test_past_and_future_limits() -> None:
    assert not evaluate(ev(city=SAARBRUECKEN, days=-1), PREF, profile()).shown
    p = FilterProfile(date_from=TODAY, date_to=TODAY + timedelta(days=60))
    assert evaluate(ev(city=SAARBRUECKEN, days=59), PREF, p).shown
    assert not evaluate(ev(city=SAARBRUECKEN, days=61), PREF, p).shown


def test_cancelled_flagged_or_hidden() -> None:
    cancelled = ev(city=SAARBRUECKEN, status="cancelled")
    assert evaluate(cancelled, PREF, profile(show_cancelled=True)).shown
    assert not evaluate(cancelled, PREF, profile(show_cancelled=False)).shown
    assert evaluate(ev(city=SAARBRUECKEN, status="rescheduled"), PREF, profile(show_cancelled=False)).shown


def test_inactive_or_unfollowed_artist() -> None:
    inactive = ArtistPref(artist_id=1, artist_name="X", active=False)
    assert not evaluate(ev(city=SAARBRUECKEN), inactive, profile()).shown
    assert not evaluate(ev(city=SAARBRUECKEN), None, profile()).shown


def test_event_types() -> None:
    assert not evaluate(ev(city=SAARBRUECKEN, event_type="support"), PREF, profile(include_support=False)).shown
    assert evaluate(ev(city=SAARBRUECKEN, event_type="support"), PREF, profile()).shown
    assert not evaluate(ev(city=SAARBRUECKEN, event_type="special"), PREF, profile(include_special=False)).shown


def test_delisted_events_hidden() -> None:
    d = evaluate(ev(city=SAARBRUECKEN, is_listed=False), PREF, profile())
    assert not d.shown and d.hidden_reason == "Nicht mehr gelistet"


def test_confirmation_message_multiple_sources() -> None:
    d = evaluate(ev(city=SAARBRUECKEN, source_count=3), PREF, profile())
    assert any("3 Quellen bestätigen diesen Termin" in c.message for c in d.checks)
