"""Filter scenarios against the real geo seed + demo tour (requirements sections 7, 43, 46)."""

from __future__ import annotations

import dataclasses
import random
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from tourdesk_crawler.jobs.runner import run_job_inline


def _ids(client, kind: str, q: str, **params) -> int:
    hits = client.get(f"/api/{kind}", params={"q": q, **params}).json()
    assert hits, f"{kind} {q} nicht gefunden"
    return hits[0]["id"]


@pytest.fixture()
def example_user(make_user):
    """User from the requirements: Saarland complete, Luxembourg only Rockhal + Luxexpo, France only Metz + Strasbourg."""
    alice = make_user("alice")
    saarland = next(r["id"] for r in alice.get("/api/regions", params={"q": "Saarland"}).json() if r["code"] == "DE-SL")
    alice.post("/api/filters/locations", json={"level": "region", "target_id": saarland})
    for venue in ("Rockhal", "Luxexpo"):
        alice.post("/api/filters/locations", json={"level": "venue", "target_id": _ids(alice, "venues", venue)})
    fr = next(c["id"] for c in alice.get("/api/countries").json() if c["code"] == "FR")
    for city in ("Metz", "Strasbourg"):
        alice.post("/api/filters/locations", json={"level": "city", "target_id": _ids(alice, "cities", city, country_id=fr)})
    band = alice.post("/api/artists", json={"name": "Beispielband", "show_festivals": True}).json()
    result = run_job_inline("artist_crawl", artist_id=band["id"])
    assert result["status"] == "success" and result["events_new"] >= 15
    return alice, band


def _tour(client, artist_id: int) -> list[dict]:
    return client.get(f"/api/artists/{artist_id}/events").json()["all_events"]


def _shown(events: list[dict], venue: str) -> bool:
    match = [e for e in events if e["venue_name"] == venue]
    assert match, venue
    return match[0]["matches"]


def test_location_rules_listing(example_user) -> None:
    alice, _band = example_user
    rules = alice.get("/api/filters").json()["locations"]
    assert {(r["level"], r["label"]) for r in rules} == {
        ("region", "Saarland"), ("venue", "Rockhal"), ("venue", "Luxexpo The Box"), ("city", "Metz"), ("city", "Straßburg"),
    }


def test_saarland_complete(example_user) -> None:
    alice, band = example_user
    events = _tour(alice, band["id"])
    assert _shown(events, "Garage")  # Saarbrücken
    assert _shown(events, "Neue Gebläsehalle")  # Neunkirchen
    assert _shown(events, "E-Werk Saarbrücken")
    assert not _shown(events, "Arena Trier")  # Rheinland-Pfalz


def test_luxembourg_only_selected_venues(example_user) -> None:
    alice, band = example_user
    events = _tour(alice, band["id"])
    assert _shown(events, "Rockhal")
    assert _shown(events, "Luxexpo The Box")
    assert not _shown(events, "den Atelier")


def test_france_only_selected_cities(example_user) -> None:
    alice, band = example_user
    events = _tour(alice, band["id"])
    assert _shown(events, "BAM – Boîte à Musiques")
    assert _shown(events, "La Laiterie")
    assert not _shown(events, "L'Autre Canal")  # Nancy


def test_festival_switch(example_user) -> None:
    alice, band = example_user
    fests = [e for e in _tour(alice, band["id"]) if e["event_type"] == "festival"]
    by_name = {e["festival"]["name"]: e for e in fests}
    assert by_name["Rocco del Schlacko"]["matches"] is True  # Saarland
    assert by_name["Rock am Ring"]["matches"] is False  # outside filters
    alice.patch(f"/api/artists/{band['id']}", json={"show_festivals": False})
    fests = [e for e in _tour(alice, band["id"]) if e["event_type"] == "festival"]
    assert all(e["matches"] is False and e["hidden_reason"] == "Festival ausgeblendet" for e in fests)


def test_dashboard_tile(example_user) -> None:
    alice, band = example_user
    tiles = alice.get("/api/dashboard").json()["tiles"]
    tile = next(t for t in tiles if t["artist"]["id"] == band["id"])
    assert tile["tour_status"]["state"] == "on_tour"
    assert tile["tour_status"]["emoji"] == "🟢"
    assert len(tile["matching_events"]) == 3
    assert tile["more_count"] == tile["matching_count"] - 3
    assert tile["outside_filters"] > 0


def test_explanations(example_user) -> None:
    alice, band = example_user
    events = _tour(alice, band["id"])
    atelier = next(e for e in events if e["venue_name"] == "den Atelier")
    exp = alice.get(f"/api/events/{atelier['id']}/explain").json()
    assert exp["shown"] is False
    failed = [c["message"] for c in exp["checks"] if c["ok"] is False]
    assert "Luxemburg ist nicht komplett ausgewählt – nur: Rockhal, Luxexpo The Box" in failed
    garage = next(e for e in events if e["venue_name"] == "Garage")
    detail = alice.get(f"/api/events/{garage['id']}").json()
    ok = [c["message"] for c in detail["explanation"]["checks"] if c["ok"]]
    assert "Saarland ist bevorzugte Region" in ok
    assert detail["sources"][0]["trust_level"] == 1
    assert detail["ticket_url"].startswith("https://example.org/tickets/")


def test_events_endpoint_uses_same_rules(example_user) -> None:
    alice, band = example_user
    page = alice.get("/api/events", params={"limit": 200}).json()
    listed = {e["id"] for e in page["items"]}
    expected = {e["id"] for e in _tour(alice, band["id"]) if e["matches"]}
    assert listed == expected
    assert page["total"] == len(expected)


def test_cancelled_events_can_be_hidden(example_user) -> None:
    alice, band = example_user
    alice.post("/api/filters/locations", json={"level": "country", "target_id": next(
        c["id"] for c in alice.get("/api/countries").json() if c["code"] == "DE")})
    munich = next(e for e in _tour(alice, band["id"]) if e["venue_name"] == "Zenith München")
    assert munich["status"] == "cancelled" and munich["matches"] is True
    alice.put("/api/filters", json={"show_cancelled": False})
    munich = next(e for e in _tour(alice, band["id"]) if e["venue_name"] == "Zenith München")
    assert munich["matches"] is False


def test_search(example_user) -> None:
    alice, _band = example_user
    res = alice.get("/api/search", params={"q": "Saarland"}).json()
    assert any(r["code"] == "DE-SL" for r in res["regions"])
    assert res["events"] and all(e["region"]["name"] == "Saarland" for e in res["events"])
    res = alice.get("/api/search", params={"q": "Rockhal"}).json()
    assert res["venues"][0]["name"] == "Rockhal"
    assert any(e["venue_name"] == "Rockhal" for e in res["events"])
    res = alice.get("/api/search", params={"q": "Beispiel"}).json()
    assert res["artists"][0]["name"] == "Beispielband"


def test_ical_export(example_user) -> None:
    alice, band = example_user
    event = _tour(alice, band["id"])[0]
    resp = alice.get(f"/api/events/{event['id']}/ical")
    assert resp.status_code == 200 and "BEGIN:VEVENT" in resp.text and "Beispielband" in resp.text


def test_sql_predicate_matches_engine(db, example_user) -> None:
    """Randomised check: SQL filter == Python filter engine for many rule combinations."""
    from tourdesk.models import Event, User, UserFilter
    from tourdesk.services.filter_engine import evaluate
    from tourdesk.services.filter_sql import matching_events_query
    from tourdesk.services.filters import artist_prefs, build_profile, event_facts

    alice, _band = example_user
    user = db.execute(select(User).where(User.username_norm == "alice")).unique().scalar_one()
    events = db.execute(select(Event)).unique().scalars().all()
    city_ids = [e.city_id for e in events if e.city_id]
    venue_ids = [e.venue_id for e in events if e.venue_id]
    region_ids = [e.region_id for e in events if e.region_id]
    country_ids = [e.country_id for e in events if e.country_id]
    rng = random.Random(42)
    for _ in range(40):
        f = db.execute(select(UserFilter).where(UserFilter.user_id == user.id)).scalar_one()
        f.festival_mode = rng.choice(["artist", "always", "never"])
        f.festival_scope = rng.choice(["filters", "anywhere"])
        f.show_cancelled = rng.random() < 0.5
        f.include_support = rng.random() < 0.7
        f.include_special = rng.random() < 0.7
        f.date_mode = rng.choice(["upcoming", "months"])
        f.months_ahead = rng.choice([1, 3, 12])
        db.flush()
        profile = build_profile(db, f, date.today())
        # random rule set (built directly on the profile)
        from tourdesk.services.filter_engine import LocationRule

        rules = []
        for level, pool in (("venue", venue_ids), ("city", city_ids), ("region", region_ids), ("country", country_ids)):
            for target in rng.sample(sorted(set(pool)), k=min(len(set(pool)), rng.randint(0, 2))):
                rules.append(LocationRule(len(rules) + 1, level, target, str(target)))
        profile = dataclasses.replace(profile, rules=tuple(rules), region_coverage={})
        prefs = artist_prefs(db, user.id)
        sql_ids = {e.id for e in db.execute(matching_events_query(user.id, profile)).unique().scalars()}
        py_ids = {e.id for e in events if evaluate(event_facts(e), prefs.get(e.artist_id), profile).shown}
        assert sql_ids == py_ids
    db.rollback()


def test_location_catalog_endpoints(make_user) -> None:
    alice = make_user("alice")
    countries = alice.get("/api/countries").json()
    assert countries[0]["code"] == "DE"
    de = countries[0]["id"]
    regions = alice.get("/api/regions", params={"country_id": de}).json()
    assert len(regions) == 16
    sl = next(r for r in regions if r["code"] == "DE-SL")
    cities = alice.get("/api/cities", params={"region_id": sl["id"], "limit": 200}).json()
    names = {c["name"] for c in cities}
    assert {"Saarbrücken", "Neunkirchen", "Homburg", "Saarlouis", "Sankt Ingbert"} <= names
    lux = alice.get("/api/cities", params={"q": "Luxemburg"}).json()
    assert lux[0]["country_code"] == "LU"
    assert alice.get("/api/cities", params={"q": "Straßburg"}).json()[0]["local_name"] == "Strasbourg"
    new_city = alice.post("/api/cities", json={"name": "Kleinstadt am See", "country_id": de, "region_id": sl["id"]})
    assert new_city.status_code == 201
    v = alice.post("/api/venues", json={"name": "Kulturscheune", "city_id": new_city.json()["id"], "website": "https://kulturscheune.example"})
    assert v.status_code == 201 and v.json()["is_favorite"] is True and v.json()["has_agenda_source"] is True
    favs = alice.get("/api/venues", params={"favorites": "true"}).json()
    assert [f["name"] for f in favs] == ["Kulturscheune"]


def test_date_range_filter(example_user) -> None:
    alice, band = example_user
    alice.put("/api/filters", json={"date_mode": "range", "date_from": date.today().isoformat(),
                                    "date_to": (date.today() + timedelta(days=6)).isoformat()})
    shown = [e for e in _tour(alice, band["id"]) if e["matches"]]
    assert shown and all(date.fromisoformat(e["date"]) <= date.today() + timedelta(days=6) for e in shown)
