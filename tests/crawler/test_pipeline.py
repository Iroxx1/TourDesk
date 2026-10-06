"""End-to-end crawl pipeline with mocked websites: dedup, trust, delisting, notifications, venue agendas."""

from __future__ import annotations

import json
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select

import tourdesk_crawler.jobs.context as job_context
from tourdesk.core.text import normalize_name
from tourdesk.core.timeutil import utcnow
from tourdesk.models import Artist, Event, Notification, Source, User, UserArtist, Venue
from tourdesk_crawler.jobs.runner import run_job_inline

D1 = date.today() + timedelta(days=40)
D2 = date.today() + timedelta(days=43)
D3 = date.today() + timedelta(days=47)


def jsonld_page(events: list[dict]) -> str:
    graph = []
    for e in events:
        item = {
            "@type": e.get("type", "MusicEvent"),
            "name": e["name"],
            "startDate": e["date"].isoformat() + "T20:00:00",
            "location": {"@type": "Place", "name": e["venue"], "address": {"addressLocality": e["city"], "addressCountry": e["country"]}},
        }
        if e.get("performers"):
            item["performer"] = [{"@type": "MusicGroup", "name": p} for p in e["performers"]]
        if e.get("status"):
            item["eventStatus"] = e["status"]
        if e.get("offer"):
            item["offers"] = {"url": e["offer"], "availability": e.get("availability", "InStock")}
        graph.append(item)
    return f'<html><head><script type="application/ld+json">{json.dumps({"@graph": graph})}</script></head></html>'


class Site:
    """Mutable fake internet."""

    def __init__(self) -> None:
        self.pages: dict[str, str] = {}
        self.fail: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        key = f"{request.url.host}{request.url.path}"
        if key in self.fail:
            return httpx.Response(500)
        if key in self.pages:
            return httpx.Response(200, text=self.pages[key], headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404)


@pytest.fixture()
def site(db, monkeypatch):
    s = Site()
    monkeypatch.setattr(job_context, "TRANSPORT_OVERRIDE", httpx.MockTransport(s.handler))
    monkeypatch.setattr("tourdesk_crawler.http.client.PoliteHttpClient._wait_for_slot", lambda self, d, i: None)
    monkeypatch.setattr("tourdesk_crawler.http.client.time.sleep", lambda s: None)
    return s


@pytest.fixture()
def follower(make_user):
    """alice follows 'Testband' with the Saarland as region; returns (client, artist_id)."""
    alice = make_user("alice")
    sl = next(r["id"] for r in alice.get("/api/regions", params={"q": "Saarland"}).json() if r["code"] == "DE-SL")
    alice.post("/api/filters/locations", json={"level": "region", "target_id": sl})
    rockhal = alice.get("/api/venues", params={"q": "Rockhal"}).json()[0]["id"]
    alice.post("/api/filters/locations", json={"level": "venue", "target_id": rockhal})
    a = alice.post("/api/artists", json={"name": "Testband", "official_website": "https://testband.test", "show_festivals": True}).json()
    return alice, a["id"]


def crawl(artist_id: int) -> dict:
    return run_job_inline("artist_crawl", artist_id=artist_id)


def events_of(db, artist_id: int) -> list[Event]:
    db.expire_all()
    return list(db.execute(select(Event).where(Event.artist_id == artist_id).order_by(Event.event_date)).unique().scalars())


def test_official_site_crawl_and_idempotency(db, site, follower) -> None:
    _alice, artist_id = follower
    site.pages["testband.test/"] = jsonld_page([
        {"name": "Testband Live", "date": D1, "venue": "Garage", "city": "Saarbrücken", "country": "DE", "offer": "https://www.eventim.de/x"},
        {"name": "Testband Live", "date": D2, "venue": "Rockhal Club", "city": "Esch-sur-Alzette", "country": "LU"},
    ])
    first = crawl(artist_id)
    assert first["events_new"] == 2 and first["sources_ok"] == 1
    evs = events_of(db, artist_id)
    assert [e.venue.name for e in evs] == ["Garage", "Rockhal"]  # "Rockhal Club" matched to the known venue
    assert evs[0].region.code == "DE-SL" and evs[0].is_confirmed and evs[0].best_trust == 1
    assert evs[0].ticket_provider == "Eventim"
    second = crawl(artist_id)
    assert second["events_new"] == 0 and second["events_updated"] == 0 and second["events_removed"] == 0


def test_dedup_across_sources_and_confirmation(db, site, follower) -> None:
    alice, artist_id = follower
    # unofficial page (trust 6) lists the event
    alice.post(f"/api/artists/{artist_id}/sources", json={"url": "https://fanpage.test/dates", "provider": "generic_web"})
    site.pages["testband.test/"] = "<html><body>Bald neue Termine!</body></html>"
    site.pages["fanpage.test/dates"] = jsonld_page([
        {"name": "Testband", "date": D3, "venue": "Garage Club", "city": "Saarbrücken", "country": "DE", "performers": ["Testband"]},
    ])
    crawl(artist_id)
    ev = events_of(db, artist_id)[0]
    assert ev.is_confirmed is False and ev.source_count == 1  # rumour level only
    # a second independent source confirms it
    alice.post(f"/api/artists/{artist_id}/sources", json={"url": "https://tickets.test/testband", "provider": "generic_web"})
    site.pages["tickets.test/testband"] = jsonld_page([
        {"name": "Testband – Live", "date": D3, "venue": "Garage", "city": "Saarbrücken", "country": "DE", "performers": ["Testband"]},
    ])
    crawl(artist_id)
    evs = events_of(db, artist_id)
    assert len(evs) == 1
    assert evs[0].source_count == 2 and evs[0].is_confirmed is True


def test_festival_rumour_is_not_confirmed(db, site, follower) -> None:
    alice, artist_id = follower
    alice.post(f"/api/artists/{artist_id}/sources", json={"url": "https://geruechte.test/", "provider": "generic_web"})
    alice.post(f"/api/artists/{artist_id}/sources", json={"url": "https://news.test/", "provider": "generic_web"})
    page = jsonld_page([{"type": "Festival", "name": "Rocco del Schlacko", "date": D1, "venue": "Sauwasen", "city": "Püttlingen",
                         "country": "DE", "performers": ["Testband", "Andere Band"]}])
    site.pages["geruechte.test/"] = page
    site.pages["news.test/"] = page
    crawl(artist_id)
    ev = events_of(db, artist_id)[0]
    assert ev.event_type == "festival" and ev.source_count == 2
    assert ev.is_confirmed is False  # festivals need an official source


def test_removed_event_is_delisted_not_deleted(db, site, follower) -> None:
    _alice, artist_id = follower
    site.pages["testband.test/"] = jsonld_page([
        {"name": "A", "date": D1, "venue": "Garage", "city": "Saarbrücken", "country": "DE"},
        {"name": "B", "date": D2, "venue": "Rockhal", "city": "Esch-sur-Alzette", "country": "LU"},
    ])
    crawl(artist_id)
    site.pages["testband.test/"] = jsonld_page([{"name": "A", "date": D1, "venue": "Garage", "city": "Saarbrücken", "country": "DE"}])
    result = crawl(artist_id)
    assert result["events_removed"] == 1
    evs = events_of(db, artist_id)
    assert len(evs) == 2 and [e.is_listed for e in evs] == [True, False]


def test_source_failure_keeps_events(db, site, follower) -> None:
    _alice, artist_id = follower
    site.pages["testband.test/"] = jsonld_page([{"name": "A", "date": D1, "venue": "Garage", "city": "Saarbrücken", "country": "DE"}])
    crawl(artist_id)
    site.fail.add("testband.test/")
    result = crawl(artist_id)
    assert result["sources_failed"] == 1 and result["events_removed"] == 0
    assert events_of(db, artist_id)[0].is_listed is True
    source = db.execute(select(Source).where(Source.artist_id == artist_id)).scalar_one()
    db.refresh(source)
    assert source.status == "error" and source.consecutive_failures == 1 and source.next_attempt_at is not None
    artist = db.get(Artist, artist_id)
    db.refresh(artist)
    assert artist.crawl_status == "error"


def test_suspicious_empty_page_does_not_delist(db, site, follower) -> None:
    _alice, artist_id = follower
    site.pages["testband.test/"] = jsonld_page([
        {"name": n, "date": D1 + timedelta(days=i), "venue": "Garage", "city": "Saarbrücken", "country": "DE"}
        for i, n in enumerate("ABCD")
    ])
    crawl(artist_id)
    site.pages["testband.test/"] = "<html><body>Wartungsarbeiten</body></html>"
    result = crawl(artist_id)
    assert result["events_removed"] == 0
    assert all(e.is_listed for e in events_of(db, artist_id))


def test_notifications_after_baseline(db, site, follower) -> None:
    alice, artist_id = follower
    site.pages["testband.test/"] = jsonld_page([{"name": "A", "date": D1, "venue": "Garage", "city": "Saarbrücken", "country": "DE"}])
    crawl(artist_id)  # baseline: no notifications
    assert db.execute(select(Notification)).first() is None
    site.pages["testband.test/"] = jsonld_page([
        {"name": "A", "date": D1, "venue": "Garage", "city": "Saarbrücken", "country": "DE", "status": "EventCancelled"},
        {"name": "B", "date": D2, "venue": "Rockhal", "city": "Esch-sur-Alzette", "country": "LU"},
        {"name": "C", "date": D3, "venue": "Ziggo Dome", "city": "Amsterdam", "country": "NL"},
    ])
    crawl(artist_id)
    types = sorted(n.type for n in db.execute(select(Notification)).scalars())
    # Rockhal = new event in preferred places, Garage cancelled; Amsterdam is outside the filters -> nothing
    assert types == ["event_cancelled", "event_in_region"]
    data = alice.get("/api/notifications").json()
    assert data["unread"] == 2
    assert alice.post("/api/notifications/read-all").status_code == 200
    assert alice.get("/api/notifications/unread-count").json()["unread"] == 0


def test_venue_agenda_matches_monitored_artists(db, site, follower, make_user) -> None:
    _alice, artist_id = follower
    garage = db.execute(select(Venue).where(Venue.name_norm == normalize_name("Garage"))).unique().scalars().first()
    source = Source(scope="venue", provider="venue_website", name="Garage – Programm", url="https://garage.test/programm",
                    venue_id=garage.id, trust_level=2, is_enabled=True, config={})
    db.add(source)
    db.commit()
    site.pages["garage.test/programm"] = jsonld_page([
        {"name": "Testband – Live 2027", "date": D2, "venue": "Garage", "city": "Saarbrücken", "country": "DE"},
        {"name": "Völlig andere Band", "date": D3, "venue": "Garage", "city": "Saarbrücken", "country": "DE"},
        {"name": "Testband Tribute Night", "date": D1, "venue": "Garage", "city": "Saarbrücken", "country": "DE"},
    ])
    result = run_job_inline("source_crawl", source_id=source.id)
    assert result["status"] == "success" and result["events_new"] == 1
    evs = events_of(db, artist_id)
    assert len(evs) == 1 and evs[0].venue_id == garage.id and evs[0].best_trust == 2 and evs[0].is_confirmed


def test_festival_lineup_source(db, site, follower) -> None:
    from tourdesk.models import Festival

    _alice, artist_id = follower
    fest = db.execute(select(Festival).where(Festival.name == "Rocco del Schlacko")).unique().scalar_one()
    source = Source(scope="festival", provider="festival_lineup", name="RdS Line-up", url="https://rds.test/",
                    festival_id=fest.id, trust_level=3, is_enabled=True,
                    config={"start_date": D1.isoformat(), "end_date": (D1 + timedelta(days=2)).isoformat()})
    db.add(source)
    db.commit()
    site.pages["rds.test/"] = """<html><body><ul class="lineup">
      <li><a>Die Toten Hosen</a></li><li><a>Testband</a></li><li><a>Testband Tribute</a></li></ul></body></html>"""
    result = run_job_inline("source_crawl", source_id=source.id)
    assert result["events_new"] == 1
    ev = events_of(db, artist_id)[0]
    assert ev.event_type == "festival" and ev.festival_id == fest.id and ev.is_confirmed
    assert ev.city.name == "Püttlingen" and ev.region.code == "DE-SL"


def test_scheduler_tick_enqueues_once(db, follower) -> None:
    from tourdesk.models import CrawlerJob
    from tourdesk_crawler.scheduler import tick

    _alice, artist_id = follower
    db.query(CrawlerJob).delete()
    artist = db.get(Artist, artist_id)
    artist.next_crawl_at = utcnow() - timedelta(minutes=1)
    db.commit()
    first = tick(db)
    second = tick(db)
    assert first["artists"] == 1 and second["artists"] == 0
    jobs = db.execute(select(CrawlerJob).where(CrawlerJob.artist_id == artist_id, CrawlerJob.job_type == "artist_crawl")).scalars().all()
    assert len(jobs) == 1


def test_scheduler_venue_relevance(db, follower) -> None:
    from tourdesk_crawler.scheduler import relevant_scope, source_is_relevant

    _alice, _artist_id = follower
    scope = relevant_scope(db)
    rockhal_source = db.execute(select(Source).join(Venue, Venue.id == Source.venue_id).where(Venue.name == "Rockhal")).scalars().first()
    atelier_source = db.execute(select(Source).join(Venue, Venue.id == Source.venue_id).where(Venue.name == "den Atelier")).scalars().first()
    garage_source = db.execute(select(Source).join(Venue, Venue.id == Source.venue_id).where(Venue.name == "Garage")).scalars().first()
    assert source_is_relevant(db, rockhal_source, scope)  # venue rule
    assert source_is_relevant(db, garage_source, scope)  # inside the Saarland
    assert not source_is_relevant(db, atelier_source, scope)  # Luxembourg is not selected completely


def test_inactive_artists_are_not_crawled(db, follower) -> None:
    from tourdesk_crawler.scheduler import tick

    alice, artist_id = follower
    alice.patch(f"/api/artists/{artist_id}", json={"is_active": False})
    artist = db.get(Artist, artist_id)
    artist.next_crawl_at = utcnow() - timedelta(minutes=5)
    db.commit()
    from tourdesk.models import CrawlerJob

    db.query(CrawlerJob).delete()
    db.commit()
    assert tick(db)["artists"] == 0


def test_user_deactivated_stops_monitoring(db, follower, admin) -> None:
    from tourdesk_crawler.jobs.common import is_monitored

    _alice, artist_id = follower
    uid = db.execute(select(User.id).where(User.username_norm == "alice")).scalar_one()
    admin.patch(f"/api/admin/users/{uid}", json={"is_active": False})
    db.expire_all()
    assert not is_monitored(db, artist_id)
    assert db.execute(select(UserArtist).where(UserArtist.user_id == uid)).first() is not None
