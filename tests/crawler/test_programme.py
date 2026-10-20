"""Complete programme of selected venues: stored for all artists, shown via API, artists can be followed."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import func, select, update

import tourdesk_crawler.jobs.context as job_context
from tests.crawler.test_pipeline import D1, D2, D3, jsonld_page
from tourdesk.core.text import normalize_name
from tourdesk.models import CrawlerJob, Event, Source, Venue, VenueListing
from tourdesk.services.app_settings import update_crawler_settings
from tourdesk_crawler.jobs.runner import run_job_inline

ROCKHAL_PAGE = [
    {"name": "Testband – Live 2027", "date": D2, "venue": "Rockhal", "city": "Esch-sur-Alzette", "country": "LU"},
    {"name": "Völlig andere Band + Vorgruppe", "date": D3, "venue": "Rockhal", "city": "Esch-sur-Alzette", "country": "LU"},
    {"name": "Comedy Abend", "date": D1, "venue": "Rockhal", "city": "Esch-sur-Alzette", "country": "LU"},
]


def _venue(db, name: str) -> Venue:
    return db.execute(select(Venue).where(Venue.name_norm == normalize_name(name))).unique().scalars().first()


def _agenda_source(db, venue: Venue, host: str) -> Source:
    source = Source(scope="venue", provider="venue_website", name=f"{venue.name} – Programm", url=f"https://{host}/programm",
                    venue_id=venue.id, trust_level=2, is_enabled=True, config={})
    db.add(source)
    db.commit()
    return source


def _listings(db, venue_id: int) -> list[VenueListing]:
    db.expire_all()
    return list(db.execute(select(VenueListing).where(VenueListing.venue_id == venue_id).order_by(VenueListing.event_date)).scalars())


def test_selected_venue_keeps_whole_programme(db, site, follower) -> None:
    alice, artist_id = follower
    rockhal = _venue(db, "Rockhal")
    # Seed-Quelle (rockhal.lu) gilt als schon abgerufen – sonst stößt die API ihren Abruf an
    db.execute(update(Source).where(Source.venue_id == rockhal.id).values(config=Source.config.op("||")(func.jsonb_build_object("programme_at", "2026-01-01T00:00:00+00:00"))))
    source = _agenda_source(db, rockhal, "rockhal.test")
    site.pages["rockhal.test/programm"] = jsonld_page(ROCKHAL_PAGE)

    result = run_job_inline("source_crawl", source_id=source.id)
    assert result["status"] == "success" and result["programme"] == 3
    # nur der überwachte Künstler bekommt einen Termin …
    events = list(db.execute(select(Event).where(Event.venue_id == rockhal.id)).unique().scalars())
    assert [e.artist_id for e in events] == [artist_id]
    # … das Programm enthält alle Einträge
    rows = _listings(db, rockhal.id)
    assert [r.artists for r in rows] == [["Comedy Abend"], ["Testband"], ["Völlig andere Band", "Vorgruppe"]]

    data = alice.get(f"/api/venues/{rockhal.id}/programme").json()
    assert data["venue"]["is_favorite"] and not data["pending"]
    assert [s["provider"] for s in data["sources"] if s["provider"] == "venue_website"]
    by_title = {it["title"]: it for it in data["items"]}
    assert by_title["Testband – Live 2027"]["artists"] == [{"name": "Testband", "artist_id": artist_id, "musicbrainz_id": None, "followed": True}]
    other = by_title["Völlig andere Band + Vorgruppe"]["artists"][0]
    assert other == {"name": "Völlig andere Band", "artist_id": None, "musicbrainz_id": None, "followed": False}

    # Hinzufügen = normaler Künstler-Eintrag, sofortige Suche wird eingeplant
    added = alice.post("/api/artists", json={"name": other["name"]})
    assert added.status_code == 201
    new_id = added.json()["id"]
    assert db.execute(select(CrawlerJob).where(CrawlerJob.artist_id == new_id, CrawlerJob.job_type == "artist_crawl")).first()
    data = alice.get(f"/api/venues/{rockhal.id}/programme").json()
    other = next(it for it in data["items"] if it["title"].startswith("Völlig"))["artists"][0]
    assert other == {"name": "Völlig andere Band", "artist_id": new_id, "musicbrainz_id": None, "followed": True}

    # Einträge, die die Seite nicht mehr zeigt, verschwinden aus dem Programm
    site.pages["rockhal.test/programm"] = jsonld_page(ROCKHAL_PAGE[:2])
    run_job_inline("source_crawl", source_id=source.id)
    assert len(_listings(db, rockhal.id)) == 2


def test_unselected_venue_keeps_only_matches(db, site, follower) -> None:
    garage = _venue(db, "Garage")
    source = _agenda_source(db, garage, "garage.test")
    site.pages["garage.test/programm"] = jsonld_page([{**e, "venue": "Garage", "city": "Saarbrücken", "country": "DE"} for e in ROCKHAL_PAGE])
    result = run_job_inline("source_crawl", source_id=source.id)
    assert result["status"] == "success" and "programme" not in result
    assert _listings(db, garage.id) == []


def test_programme_request_queues_crawl(db, follower) -> None:
    alice, _artist_id = follower
    rockhal = _venue(db, "Rockhal")
    source = _agenda_source(db, rockhal, "rockhal.test")
    db.query(CrawlerJob).delete()
    db.commit()
    data = alice.get(f"/api/venues/{rockhal.id}/programme").json()
    assert data["pending"] is True
    job = db.execute(select(CrawlerJob).where(CrawlerJob.source_id == source.id, CrawlerJob.job_type == "source_crawl")).scalars().first()
    assert job is not None and job.priority == 8
    # nicht ausgewählter Ort: nichts wird angestoßen
    garage = _venue(db, "Garage")
    data = alice.get(f"/api/venues/{garage.id}/programme").json()
    assert data["pending"] is False and data["venue"]["is_favorite"] is False


# ------------------------------------------------------------------------------------- Ticketmaster
def _tm_event(eid: str, name: str, day, performers: list[str], segment: str = "Music") -> dict:
    return {
        "id": eid,
        "name": name,
        "url": f"https://www.ticketmaster.lu/event/{eid}",
        "dates": {"start": {"localDate": day.isoformat(), "localTime": "20:00:00"}, "status": {"code": "onsale"}},
        "classifications": [{"segment": {"name": segment}, "genre": {"name": "Rock"}}],
        "_embedded": {
            "venues": [{"name": "Rockhal Main Hall", "city": {"name": "Esch-sur-Alzette"}, "country": {"countryCode": "LU"}}],
            "attractions": [{"name": p} for p in performers],
        },
    }


@pytest.fixture()
def ticketmaster(db, site, monkeypatch):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "app.ticketmaster.com" or request.url.path == "/robots.txt":
            return site.handler(request)
        calls.append(request)
        if request.url.path.endswith("/venues.json"):
            # wie bei Ticketmaster echt: mehrere Einträge je Halle, uneinheitliche Städte, viele ohne Termine
            body = {"_embedded": {"venues": [
                {"id": "KovZ3", "name": "Rockhal", "city": {"name": "Esch-sur-Alzette"}, "upcomingEvents": {"_total": 0}},
                {"id": "KovZ2", "name": "ROCKHAL CLUB - LUXEMBOURG", "city": {"name": "Esch/alzette"}, "upcomingEvents": {"_total": 2}},
                {"id": "KovZ1", "name": "Rockhal (Main Hall)", "city": {"name": "Esch-Alzette"}, "upcomingEvents": {"_total": 5}},
                {"id": "KovZ9", "name": "Rockhal", "city": {"name": "Rockhal Town"}, "upcomingEvents": {"_total": 9}},  # andere Stadt
            ]}}
        elif request.url.params.get("venueId") == "KovZ1":
            body = {"_embedded": {"events": [
                _tm_event("e1", "Testband – Europe Tour", D2, ["Testband"]),
                _tm_event("e2", "Disney on Ice", D3, ["Disney on Ice"], segment="Arts & Theatre"),
            ]}, "page": {"totalPages": 1}}
        else:
            body = {"_embedded": {"events": [_tm_event("e3", "Club Night", D1, ["DJ Eins", "DJ Zwei"])]}, "page": {"totalPages": 1}}
        return httpx.Response(200, text=json.dumps(body), headers={"content-type": "application/json"})

    monkeypatch.setattr(job_context, "TRANSPORT_OVERRIDE", httpx.MockTransport(handler))
    update_crawler_settings(db, {"api_keys": {"ticketmaster": "test-key"}}, None)
    db.commit()
    return calls


def test_ticketmaster_programme_of_selected_venue(db, ticketmaster, follower) -> None:
    from tourdesk_crawler.scheduler import ensure_programme_sources_for_selected, relevant_scope, source_is_relevant

    alice, artist_id = follower
    rockhal = _venue(db, "Rockhal")
    assert ensure_programme_sources_for_selected(db) >= 1
    assert ensure_programme_sources_for_selected(db) == 0  # nur einmal
    source = db.execute(select(Source).where(Source.venue_id == rockhal.id, Source.provider == "ticketmaster_venue")).scalars().one()
    assert source_is_relevant(db, source, relevant_scope(db))

    result = run_job_inline("source_crawl", source_id=source.id)
    assert result["status"] == "success" and result["programme"] == 3
    db.expire_all()
    assert db.get(Source, source.id).config["tm_venue_ids"] == ["KovZ1", "KovZ2"]
    # passender Künstler bekommt den Termin wie bei jeder anderen Quelle
    assert db.execute(select(Event).where(Event.artist_id == artist_id, Event.venue_id == rockhal.id)).first()

    items = alice.get(f"/api/venues/{rockhal.id}/programme").json()["items"]
    assert [it["title"] for it in items] == ["Club Night", "Testband – Europe Tour", "Disney on Ice"]
    assert [a["name"] for a in items[0]["artists"]] == ["DJ Eins", "DJ Zwei"]
    assert items[2]["category"] == "Bühne · Rock" and items[1]["ticket_url"].endswith("/e1")

    # zweiter Lauf: Ort ist bekannt, keine neue Ortssuche
    before = len([c for c in ticketmaster if c.url.path.endswith("/venues.json")])
    run_job_inline("source_crawl", source_id=source.id)
    assert len([c for c in ticketmaster if c.url.path.endswith("/venues.json")]) == before


def test_ticketmaster_source_not_relevant_when_unselected(db, ticketmaster, follower) -> None:
    from tourdesk_crawler.scheduler import ensure_programme_sources_for_selected, relevant_scope, source_is_relevant

    alice, _ = follower
    rockhal = _venue(db, "Rockhal")
    ensure_programme_sources_for_selected(db)
    source = db.execute(select(Source).where(Source.venue_id == rockhal.id, Source.provider == "ticketmaster_venue")).scalars().one()
    rule = next(r for r in alice.get("/api/filters").json()["locations"] if r["level"] == "venue" and r["target_id"] == rockhal.id)
    assert alice.delete(f"/api/filters/locations/{rule['key']}").status_code in (200, 204)
    assert not source_is_relevant(db, source, relevant_scope(db))
    # „Programm wird überwacht“ bleibt der eigenen Programmseite vorbehalten
    venue = alice.get(f"/api/venues/{rockhal.id}").json()
    has_page = db.execute(select(Source.id).where(
        Source.venue_id == rockhal.id, Source.provider == "venue_website", Source.is_enabled.is_(True)
    )).first() is not None
    assert venue["has_agenda_source"] is has_page


def test_catalog_spelling_and_musicbrainz_id(db, site, follower) -> None:
    from tests.api.test_catalog import _import
    from tourdesk.services.programme import reset_catalog_index

    alice, _ = follower
    _import(db)
    reset_catalog_index()
    rockhal = _venue(db, "Rockhal")
    db.execute(update(Source).where(Source.venue_id == rockhal.id).values(config=Source.config.op("||")(func.jsonb_build_object("programme_at", "2026-01-01T00:00:00+00:00"))))
    source = _agenda_source(db, rockhal, "rockhal.test")
    site.pages["rockhal.test/programm"] = jsonld_page([
        {"name": "DIE ÄRZTE Rock", "date": D2, "venue": "Rockhal", "city": "Esch-sur-Alzette", "country": "LU"},
    ])
    run_job_inline("source_crawl", source_id=source.id)
    item = alice.get(f"/api/venues/{rockhal.id}/programme").json()["items"][0]
    assert item["title"] == "DIE ÄRZTE" and item["category"] == "Rock"
    artist = item["artists"][0]
    assert artist["name"] == "Die Ärzte" and artist["musicbrainz_id"] and artist["artist_id"] is None
    added = alice.post("/api/artists", json={"name": artist["name"], "musicbrainz_id": artist["musicbrainz_id"]})
    assert added.status_code == 201 and added.json()["name"] == "Die Ärzte"
    artist = alice.get(f"/api/venues/{rockhal.id}/programme").json()["items"][0]["artists"][0]
    assert artist["followed"] and artist["artist_id"] == added.json()["id"]
    reset_catalog_index()


def _card(day_text: str, title: str, location: str, category: str = "Konzert") -> str:
    return (f'<article class="event"><header class="event__header"><div class="event__date">{day_text}</div>'
            f'<div class="event__time">20:00 Uhr</div><div class="event__location"><a href="/location/x/">{location}</a></div></header>'
            f'<div class="event__content"><h2 class="event__title"><a href="/events/{normalize_name(title).replace(" ", "-")}/">{title}</a></h2></div>'
            f'<div class="event__footer"><div class="event__categories"><a><span>{category}</span></a></div></div></article>')


def test_card_page_of_several_venues(db, site, follower) -> None:
    alice, _ = follower
    hall = _venue(db, "Saarlandhalle")
    alice.post("/api/filters/locations", json={"level": "venue", "target_id": hall.id})
    source = Source(scope="venue", provider="venue_website", name="Saarlandhalle – Programm", url="https://cc.test/events/",
                    venue_id=hall.id, trust_level=2, is_enabled=True, config={"venue_filter": True})
    db.add(source)
    db.commit()
    y = D3.year + 1
    site.pages["cc.test/events/"] = "<html><body>" + "".join([
        _card(f"14. Mrz {y}", "Testband – Live", "Saarlandhalle"),
        _card(f"27. - 01. Nov {y}", "Hylo Badminton Open", "Saarlandhalle", "Sport"),
        _card(f"15. Mrz {y}", "Andere Band", "Congresshalle"),
        _card(f"16. Mrz {y}", "Lisa Eckhart  Ich war mal wer", "Saarlandhalle", "Kabarett"),
    ]) + "</body></html>"
    result = run_job_inline("source_crawl", source_id=source.id)
    assert result["programme"] == 3
    rows = _listings(db, hall.id)
    assert [(r.event_date.isoformat(), r.title, r.category) for r in sorted(rows, key=lambda r: r.title)] == [
        (f"{y}-10-27", "Hylo Badminton Open", "Sport"),
        (f"{y}-03-16", "Lisa Eckhart – Ich war mal wer", "Kabarett"),
        (f"{y}-03-14", "Testband – Live", "Konzert"),
    ]
    assert next(r for r in rows if r.title.startswith("Lisa")).artists == ["Lisa Eckhart"]
    assert rows[0].start_time.hour == 20 and rows[0].url.startswith("https://cc.test/events/")
    # der überwachte Künstler bekommt nur den Termin in der Saarlandhalle
    events = list(db.execute(select(Event).where(Event.artist_id == follower[1])).unique().scalars())
    assert [e.venue_id for e in events] == [hall.id]
