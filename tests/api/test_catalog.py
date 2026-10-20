"""Künstlerkatalog: Import aus MusicBrainz (simuliert), Seiten/Register, Details, Bilder, Scheduler."""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx


def mb_artist(name: str, *, sort: str | None = None, tags: tuple[str, ...] = ("rock",), country: str | None = "GB",
              kind: str = "Group", begin: str | None = "1990", mbid: str | None = None) -> dict[str, Any]:
    return {
        "id": mbid or str(uuid.uuid5(uuid.NAMESPACE_URL, name)),
        "name": name,
        "sort-name": sort or name,
        "type": kind,
        "country": country,
        "life-span": {"begin": begin, "ended": False},
        "tags": [{"name": t, "count": 10 - i} for i, t in enumerate(tags)],
    }


class FakeSearch:
    """Stands in for ``musicbrainz.search_page``: world list and DACH list per genre query."""

    def __init__(self, world: list[dict], dach: list[dict] | None = None) -> None:
        self.world = world
        self.dach = dach or []
        self.calls: list[tuple[str, int]] = []

    def __call__(self, query: str, ua: str, *, offset: int = 0, limit: int = 100):
        # wie MusicBrainz: "Must retrieve at most 500 search results"
        assert offset + limit <= 500, f"MusicBrainz würde mit HTTP 400 antworten: offset={offset} limit={limit}"
        self.calls.append((query, offset))
        items = self.dach if "country:DE" in query else self.world
        return len(items), items[offset: offset + limit]


ROCK_WORLD = [
    mb_artist("The Kinks", sort="Kinks, The"),
    mb_artist("Bruce Springsteen", sort="Springsteen, Bruce", kind="Person", country="US", begin="1949-09-23"),
    mb_artist("The Beatles", sort="Beatles, The", tags=("pop", "rock", "psychedelic")),
    mb_artist("Some Jazz Act", tags=("jazz", "fusion", "funk", "soul", "blues", "swing", "rock")),  # rock nicht unter den Top-Tags
    mb_artist("Various Artists", mbid="89ad4ac3-39f7-470e-963a-56509c546377"),
    mb_artist("[unknown]"),
    mb_artist("10cc"),
    mb_artist("Мумий Тролль", country="RU"),
]
ROCK_DACH = [
    mb_artist("Die Ärzte", sort="Ärzte, Die", country="DE"),
    mb_artist("Kraftklub", country="DE", begin="2008"),
    mb_artist("Scorpions", country="DE"),
]


def _import(db, key: str = "rock", world=None, dach=None):
    from tourdesk.services import catalog
    from tourdesk.services.catalog_genres import GENRES_BY_KEY

    search = FakeSearch(ROCK_WORLD if world is None else world, ROCK_DACH if dach is None else dach)
    result = catalog.import_genre(db, GENRES_BY_KEY[key], "TourDeskTest/1.0", search=search)
    return result, search


def test_import_genre_filters_and_sorts(db) -> None:
    from tourdesk.models import CatalogEntry, CatalogGenre

    result, search = _import(db)
    assert result["status"] == "ok"
    names = {e.name: e for e in db.query(CatalogEntry).all()}
    # Sonderkünstler und Künstler ohne passendes Top-Schlagwort fehlen
    assert set(names) == {"The Kinks", "Bruce Springsteen", "The Beatles", "10cc", "Мумий Тролль", "Die Ärzte", "Kraftklub", "Scorpions"}
    assert names["The Kinks"].letter == "K"
    assert names["Bruce Springsteen"].letter == "S" and names["Bruce Springsteen"].begin_year == 1949
    assert names["Die Ärzte"].letter == "A" and names["Die Ärzte"].is_dach
    assert names["10cc"].letter == "#" and names["Мумий Тролль"].letter == "#"
    assert names["Kraftklub"].genre_ranks == {"rock": 2}
    state = db.get(CatalogGenre, "rock")
    assert state.status == "ok" and state.entry_count == 8
    # Weltliste je Schlagwort einzeln, dazu die DACH-Liste
    queries = {q for q, _ in search.calls}
    assert {'tag:"rock"', 'tag:"hard rock"', 'tag:"classic rock"'} <= queries
    assert any("country:DE" in q for q in queries)


def test_import_respects_musicbrainz_result_limit(db) -> None:
    many = [mb_artist(f"Band {i:04d}") for i in range(1200)]
    result, search = _import(db, world=many, dach=[])
    assert result["status"] == "ok"
    # pro Suche höchstens 500 Treffer (offset 0–400 in 100er-Schritten)
    assert max(offset for _, offset in search.calls) == 400


def test_reimport_removes_dropped_artists_but_keeps_other_genres(db) -> None:
    from tourdesk.models import CatalogEntry

    _import(db)
    _import(db, "pop", world=[mb_artist("The Beatles", sort="Beatles, The", tags=("pop", "rock"))], dach=[])
    _import(db, world=[mb_artist("The Kinks", sort="Kinks, The")], dach=[])
    names = {e.name: e.genres for e in db.query(CatalogEntry).all()}
    assert names == {"The Kinks": ["rock"], "The Beatles": ["pop"]}


def test_import_error_is_recorded(db) -> None:
    from tourdesk.models import CatalogGenre
    from tourdesk.services import catalog
    from tourdesk.services.catalog_genres import GENRES_BY_KEY

    def broken(*_a, **_k):
        raise httpx.ConnectError("offline")

    result = catalog.import_genre(db, GENRES_BY_KEY["jazz"], "ua", search=broken)
    assert result["status"] == "error"
    state = db.get(CatalogGenre, "jazz")
    assert state.status == "error" and "offline" in state.last_error
    # gerade fehlgeschlagen → noch nicht wieder fällig, nach 6 Stunden schon
    assert "jazz" not in {g.key for g in catalog.stale_genres(db)}
    state.last_attempt_at -= timedelta(hours=7)
    db.commit()
    assert "jazz" in {g.key for g in catalog.stale_genres(db)}


def test_pages_letters_filters_and_followed(db, make_user) -> None:
    _import(db)
    alice = make_user("alice")
    resp = alice.get("/api/catalog/pages", params={"genre": "rock", "per_page": 4})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # jeder Anfangsbuchstabe beginnt auf einer neuen Seite: # | A | B | K | S
    assert data["total"] == 8 and data["pages"] == 5
    assert [i["name"] for i in data["items"]] == ["10cc", "Мумий Тролль"]
    assert {k: v for k, v in data["letters"].items() if v is not None} == {"#": 0, "A": 1, "B": 2, "K": 3, "S": 4}
    second = alice.get("/api/catalog/pages", params={"genre": "rock", "per_page": 4, "page": 3}).json()
    assert [i["name"] for i in second["items"]] == ["The Kinks", "Kraftklub"]
    assert alice.get("/api/catalog/pages", params={"genre": "rock", "per_page": 4, "page": 4}).json()["items"][0]["name"] == "Scorpions"
    assert second["items"][0]["genres"] == ["Rock"]

    dach = alice.get("/api/catalog/pages", params={"origin": "dach"}).json()
    assert [i["name"] for i in dach["items"]] == ["Die Ärzte"] and dach["pages"] == 3
    intl = alice.get("/api/catalog/pages", params={"origin": "intl"}).json()
    assert intl["total"] == 5
    assert alice.get("/api/catalog/pages", params={"genre": "jazz"}).json()["total"] == 0

    kraftklub = next(i for i in second["items"] if i["name"] == "Kraftklub")
    assert kraftklub["followed"] is False
    added = alice.post("/api/artists", json={"name": "Kraftklub", "musicbrainz_id": kraftklub["mbid"], "genre": "Rock"})
    assert added.status_code == 201, added.text
    again = alice.get("/api/catalog/pages", params={"genre": "rock", "per_page": 4, "page": 3}).json()
    entry = next(i for i in again["items"] if i["name"] == "Kraftklub")
    assert entry["followed"] is True and entry["artist_id"] == added.json()["id"]
    # ein anderer Benutzer sieht den Künstler als vorhanden, aber nicht überwacht
    bob = make_user("bob")
    other = next(i for i in bob.get("/api/catalog/pages", params={"genre": "rock", "per_page": 4, "page": 3}).json()["items"] if i["name"] == "Kraftklub")
    assert other["followed"] is False and other["artist_id"] == added.json()["id"]


def test_pages_validation_and_auth(db, client, make_user) -> None:
    assert client.get("/api/catalog/pages").status_code == 401
    alice = make_user("alice")
    assert alice.get("/api/catalog/pages", params={"genre": "gibtsnicht"}).status_code == 422
    assert alice.get("/api/catalog/pages", params={"origin": "mars"}).status_code == 422
    assert alice.get("/api/catalog/entries/keine-mbid").status_code == 422
    assert alice.get(f"/api/catalog/entries/{uuid.uuid4()}").status_code == 404


def test_meta(db, make_user) -> None:
    alice = make_user("alice")
    empty = alice.get("/api/catalog/meta").json()
    assert empty["ready"] is False and empty["total"] == 0 and empty["progress"] == {"done": 0, "total": 20}
    _import(db)
    meta = alice.get("/api/catalog/meta").json()
    assert meta["ready"] is True and meta["total"] == 8 and meta["dach_total"] == 3
    rock = next(g for g in meta["genres"] if g["key"] == "rock")
    assert rock == {"key": "rock", "label": "Rock", "count": 8}
    assert meta["progress"]["done"] == 1


@respx.mock
def test_detail_fetches_website_and_wikipedia_once(db, make_user, monkeypatch) -> None:
    from tourdesk.services import musicbrainz

    _import(db)
    alice = make_user("alice")
    mbid = str(uuid.uuid5(uuid.NAMESPACE_URL, "Kraftklub"))
    lookups: list[str] = []

    def fake_lookup(m: str, ua: str):
        lookups.append(m)
        return {"mbid": m, "urls": {"official homepage": ["https://www.kraftklub.to/"], "wikidata": ["https://www.wikidata.org/wiki/Q1786614"]}}

    monkeypatch.setattr(musicbrainz, "lookup_artist", fake_lookup)
    respx.get("https://www.wikidata.org/wiki/Special:EntityData/Q1786614.json").mock(
        return_value=httpx.Response(200, json={"entities": {"Q1786614": {"sitelinks": {"dewiki": {"title": "Kraftklub"}}}}})
    )
    respx.get("https://de.wikipedia.org/api/rest_v1/page/summary/Kraftklub").mock(
        return_value=httpx.Response(200, json={
            "extract": "Kraftklub ist eine deutsche Band aus Chemnitz. Sie wurde 2008 gegründet.",
            "content_urls": {"desktop": {"page": "https://de.wikipedia.org/wiki/Kraftklub"}},
        })
    )
    resp = alice.get(f"/api/catalog/entries/{mbid}")
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert d["name"] == "Kraftklub" and d["begin_year"] == 2008 and d["country"] == "DE"
    assert d["website"] == "https://www.kraftklub.to/"
    assert d["description"].startswith("Kraftklub ist eine deutsche Band") and d["description_lang"] == "de"
    assert d["wikipedia_url"] == "https://de.wikipedia.org/wiki/Kraftklub"
    assert d["musicbrainz_url"].endswith(mbid)
    # zweiter Aufruf kommt aus der Datenbank
    assert alice.get(f"/api/catalog/entries/{mbid}").json()["website"] == "https://www.kraftklub.to/"
    assert lookups == [mbid]


def test_wikimedia_user_agent_gets_contact() -> None:
    from tourdesk.services.catalog import PROJECT_URL, wikimedia_user_agent

    assert wikimedia_user_agent("TourDeskBot/1.0 (+self-hosted concert monitor)").endswith(f"(+{PROJECT_URL})")
    # ein eingetragener Kontakt bleibt unverändert (keine zweite Angabe)
    assert wikimedia_user_agent("TourDeskBot/1.0 (admin@example.org)") == "TourDeskBot/1.0 (admin@example.org)"


@respx.mock
def test_detail_wikidata_error_is_retried_next_time(db, make_user, monkeypatch) -> None:
    from tourdesk.models import CatalogEntry
    from tourdesk.services import musicbrainz

    _import(db)
    alice = make_user("alice")
    mbid = str(uuid.uuid5(uuid.NAMESPACE_URL, "Scorpions"))
    lookups: list[str] = []

    def fake_lookup(m: str, ua: str):
        lookups.append(m)
        return {"mbid": m, "urls": {"wikidata": ["https://www.wikidata.org/wiki/Q158895"]}}

    monkeypatch.setattr(musicbrainz, "lookup_artist", fake_lookup)
    wikidata = respx.get("https://www.wikidata.org/wiki/Special:EntityData/Q158895.json").mock(
        return_value=httpx.Response(403, text="Please respect our robot policy")
    )
    assert alice.get(f"/api/catalog/entries/{mbid}").json()["description"] is None
    assert "github.com/Iroxx1/TourDesk" in wikidata.calls.last.request.headers["user-agent"]
    entry = db.get(CatalogEntry, mbid)
    db.refresh(entry)
    assert entry.details_fetched_at is None  # Fehler wird nicht einen Monat gemerkt
    alice.get(f"/api/catalog/entries/{mbid}")
    assert len(lookups) == 2


def test_detail_survives_musicbrainz_outage(db, make_user, monkeypatch) -> None:
    from tourdesk.services import musicbrainz

    _import(db)
    alice = make_user("alice")
    monkeypatch.setattr(musicbrainz, "lookup_artist", lambda m, ua: None)
    mbid = str(uuid.uuid5(uuid.NAMESPACE_URL, "Scorpions"))
    d = alice.get(f"/api/catalog/entries/{mbid}").json()
    assert d["name"] == "Scorpions" and d["website"] is None and d["description"] is None


def _png() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (300, 300), (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


@respx.mock
def test_image_from_deezer_is_cached(db, make_user) -> None:
    from tourdesk.models import CatalogEntry

    _import(db)
    alice = make_user("alice")
    mbid = str(uuid.uuid5(uuid.NAMESPACE_URL, "Kraftklub"))
    search = respx.get("https://api.deezer.com/search/artist").mock(return_value=httpx.Response(200, json={"data": [
        {"name": "Kraftklub Tribute", "picture_medium": "https://cdn.example/wrong.jpg"},
        {"name": "KRAFTKLUB", "picture_medium": "https://cdn.example/kk.jpg"},
    ]}))
    respx.get("https://cdn.example/kk.jpg").mock(return_value=httpx.Response(200, content=_png()))
    # noch nicht gesucht → der Server liefert kein Bild (die Suche läuft im Hintergrund)
    assert alice.get(f"/api/catalog/entries/{mbid}/image").status_code == 404
    from tourdesk.services import catalog

    assert catalog.fetch_entry_image(db, db.get(CatalogEntry, mbid), "ua") is not None
    assert catalog.fetch_entry_image(db, db.get(CatalogEntry, mbid), "ua") is not None  # aus dem Zwischenspeicher
    assert search.call_count == 1
    resp = alice.get(f"/api/catalog/entries/{mbid}/image")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/webp"
    entry = db.get(CatalogEntry, mbid)
    db.refresh(entry)
    assert entry.image_status == "ok"
    page = alice.get("/api/catalog/pages", params={"origin": "dach", "page": 1}).json()  # K = Kraftklub
    assert next(i for i in page["items"] if i["mbid"] == mbid)["image"] == "ok"


@respx.mock
def test_image_missing_is_remembered(db) -> None:
    from tourdesk.models import CatalogEntry
    from tourdesk.services import catalog

    _import(db)
    mbid = str(uuid.uuid5(uuid.NAMESPACE_URL, "Scorpions"))
    search = respx.get("https://api.deezer.com/search/artist").mock(return_value=httpx.Response(200, json={"data": [
        {"name": "Scorpions", "picture_medium": "https://e-cdns-images.dzcdn.net/images/artist//250x250-000000-80-0-0.jpg"},
    ]}))
    assert catalog.fetch_entry_image(db, db.get(CatalogEntry, mbid), "ua") is None
    assert catalog.fetch_entry_image(db, db.get(CatalogEntry, mbid), "ua") is None
    assert search.call_count == 1
    assert db.get(CatalogEntry, mbid).image_status == "missing"


def test_pages_queue_unknown_images_in_background(db, make_user, monkeypatch) -> None:
    from tourdesk.core.config import get_settings
    from tourdesk.services import catalog

    _import(db)
    alice = make_user("alice")
    # in Tests ist die Bildsuche aus: unbekannte Bilder gelten als „fehlt“, nichts wird angestoßen
    queued: list[list[str]] = []
    monkeypatch.setattr(catalog, "queue_images", lambda mbids, ua: queued.append(list(mbids)))
    off = alice.get("/api/catalog/pages", params={"origin": "dach"}).json()
    assert {i["image"] for i in off["items"]} == {"missing"} and queued == []
    monkeypatch.setattr(get_settings(), "catalog_images", True)
    on = alice.get("/api/catalog/pages", params={"origin": "dach"}).json()
    assert {i["image"] for i in on["items"]} == {"unknown"}
    assert queued == [[i["mbid"] for i in on["items"]]] and len(queued[0]) == 1


def test_scheduler_queues_one_catalog_import(db, monkeypatch) -> None:
    from tourdesk.core.config import get_settings
    from tourdesk.core.timeutil import utcnow
    from tourdesk.models import CrawlerJob
    from tourdesk.services.app_settings import crawler_settings
    from tourdesk_crawler.scheduler import schedule_catalog

    settings = crawler_settings(db)
    assert schedule_catalog(db, utcnow(), settings) is False  # in Tests abgeschaltet
    monkeypatch.setattr(get_settings(), "catalog_auto_import", True)
    assert schedule_catalog(db, utcnow(), settings) is True
    assert schedule_catalog(db, utcnow(), settings) is False  # läuft bereits
    assert db.query(CrawlerJob).filter_by(job_type="catalog_import").count() == 1


def test_catalog_import_job_runs_all_stale_genres(db) -> None:
    from tourdesk.models import CatalogGenre
    from tourdesk_crawler.jobs.catalog import run_catalog_import

    search = FakeSearch(ROCK_WORLD, ROCK_DACH)
    result = run_catalog_import(db, search=search)
    assert result["status"] == "success" and result["genres"] == 20
    assert db.query(CatalogGenre).filter_by(status="ok").count() == 20
    # nichts mehr fällig
    again = run_catalog_import(db, search=search)
    assert again["status"] == "skipped" and again["genres"] == 0


@pytest.mark.parametrize(("sort_name", "letter"), [("Ärzte, Die", "A"), ("10cc", "#"), ("!!!", "#"), ("Øresund", "O"), ("", "#")])
def test_letter_of(sort_name: str, letter: str) -> None:
    from tourdesk.services.catalog import letter_of

    assert letter_of(sort_name) == letter


# --------------------------------------------------------------------------- Bilder vorladen
def _deezer_by_name(pictures: dict[str, str]):
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("q")
        data = [{"name": name, "picture_medium": pictures[name]}] if name in pictures else []
        return httpx.Response(200, json={"data": data})

    return handler


@respx.mock
def test_preload_images_deezer_then_wikimedia(db, make_user, monkeypatch) -> None:
    from tourdesk.models import CatalogEntry
    from tourdesk.services import catalog, musicbrainz

    _import(db)
    kraftklub = str(uuid.uuid5(uuid.NAMESPACE_URL, "Kraftklub"))
    scorpions = str(uuid.uuid5(uuid.NAMESPACE_URL, "Scorpions"))
    search = respx.get("https://api.deezer.com/search/artist").mock(
        side_effect=_deezer_by_name({"Kraftklub": "https://cdn.example/kk.jpg"})
    )
    respx.get("https://cdn.example/kk.jpg").mock(return_value=httpx.Response(200, content=_png()))
    sparql = respx.post(catalog.SPARQL_URL).mock(return_value=httpx.Response(200, json={"results": {"bindings": [
        {"mbid": {"value": scorpions}, "image": {"value": "http://commons.wikimedia.org/wiki/Special:FilePath/Scorpions%20live.jpg"}},
    ]}}))
    commons = respx.get("https://commons.wikimedia.org/wiki/Special:FilePath/Scorpions_live.jpg").mock(
        return_value=httpx.Response(200, content=_png(), headers={"content-type": "image/png"})
    )

    result = catalog.preload_images(db, "TourDeskTest/1.0", interval=0)
    assert result["deezer_ok"] == 1 and result["deezer_missing"] == 7 and result["transient"] == 0 and result["paused"] is False
    assert result["wikimedia"] == {"checked": 7, "found": 1}
    assert result["remaining"] == 0 and result["status"] == "success"
    assert search.call_count == 8 and sparql.call_count == 1
    assert scorpions in sparql.calls.last.request.content.decode()
    assert "github.com/Iroxx1/TourDesk" in sparql.calls.last.request.headers["user-agent"]
    assert "github.com/Iroxx1/TourDesk" in commons.calls.last.request.headers["user-agent"]
    assert commons.calls.last.request.url.params.get("width") == "320"

    db.expire_all()
    kk, sc = db.get(CatalogEntry, kraftklub), db.get(CatalogEntry, scorpions)
    assert (kk.image_status, kk.image_source, kk.image_credit) == ("ok", "deezer", None)
    assert (sc.image_status, sc.image_source) == ("ok", "wikimedia")
    assert sc.image_credit == "https://commons.wikimedia.org/wiki/File:Scorpions_live.jpg"
    rest = db.query(CatalogEntry).filter(CatalogEntry.mbid.notin_([kraftklub, scorpions])).all()
    assert {(e.image_status, e.image_source) for e in rest} == {("missing", "all")}

    # nichts mehr offen: ein zweiter Lauf fragt niemanden
    again = catalog.preload_images(db, "TourDeskTest/1.0", interval=0)
    assert again["deezer_ok"] == again["deezer_missing"] == 0 and again["wikimedia"]["checked"] == 0
    assert search.call_count == 8 and sparql.call_count == 1

    # Karteikarte nennt die Quelle nur bei Commons-Bildern
    monkeypatch.setattr(musicbrainz, "lookup_artist", lambda m, ua: None)
    alice = make_user("alice")
    assert alice.get(f"/api/catalog/entries/{scorpions}").json()["image_credit"] == sc.image_credit
    assert alice.get(f"/api/catalog/entries/{kraftklub}").json()["image_credit"] is None
    assert alice.get(f"/api/catalog/entries/{scorpions}/image").status_code == 200


@respx.mock
def test_preload_images_stops_when_deezer_quota_is_used_up(db) -> None:
    from tourdesk.models import CatalogEntry
    from tourdesk.services import catalog

    _import(db)
    search = respx.get("https://api.deezer.com/search/artist").mock(
        return_value=httpx.Response(200, json={"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}})
    )
    sparql = respx.post(catalog.SPARQL_URL).mock(return_value=httpx.Response(200, json={"results": {"bindings": []}}))
    result = catalog.preload_images(db, "TourDeskTest/1.0", interval=0, max_transient=3)
    assert search.call_count == 3 and sparql.call_count == 0
    assert result["transient"] == 3 and result["paused"] is True and result["status"] == "partial" and result["remaining"] == 8
    db.expire_all()
    # nichts wird fälschlich als „kein Bild“ gemerkt
    assert {e.image_status for e in db.query(CatalogEntry)} == {"unknown"}


@respx.mock
def test_preload_images_single_hiccup_does_not_pause(db) -> None:
    from tourdesk.models import CatalogEntry
    from tourdesk.services import catalog

    _import(db)
    scorpions = str(uuid.uuid5(uuid.NAMESPACE_URL, "Scorpions"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("q") == "Scorpions":
            return httpx.Response(503)
        return httpx.Response(200, json={"data": []})

    respx.get("https://api.deezer.com/search/artist").mock(side_effect=handler)
    respx.post(catalog.SPARQL_URL).mock(return_value=httpx.Response(200, json={"results": {"bindings": []}}))
    result = catalog.preload_images(db, "TourDeskTest/1.0", interval=0)
    assert result["transient"] == 1 and result["paused"] is False and result["status"] == "success"
    assert result["remaining"] == 1  # Scorpions kommt im nächsten Lauf dran
    db.expire_all()
    assert db.get(CatalogEntry, scorpions).image_status == "unknown"


@respx.mock
def test_preload_images_retries_old_gaps(db) -> None:
    from tourdesk.core.timeutil import utcnow
    from tourdesk.models import CatalogEntry
    from tourdesk.services import catalog

    _import(db)
    kinks = str(uuid.uuid5(uuid.NAMESPACE_URL, "The Kinks"))
    for e in db.query(CatalogEntry):
        e.image_status, e.image_source, e.image_checked_at = "missing", "all", utcnow() - timedelta(days=2)
    db.get(CatalogEntry, kinks).image_checked_at = utcnow() - timedelta(days=40)
    db.commit()
    search = respx.get("https://api.deezer.com/search/artist").mock(
        side_effect=_deezer_by_name({"The Kinks": "https://cdn.example/kinks.jpg"})
    )
    respx.get("https://cdn.example/kinks.jpg").mock(return_value=httpx.Response(200, content=_png()))
    result = catalog.preload_images(db, "TourDeskTest/1.0", interval=0)
    assert search.call_count == 1 and result["deezer_ok"] == 1 and result["remaining"] == 0
    db.expire_all()
    assert db.get(CatalogEntry, kinks).image_status == "ok"


def test_scheduler_preloads_images_in_portions(db, monkeypatch) -> None:
    from tourdesk.core.config import get_settings
    from tourdesk.core.timeutil import utcnow
    from tourdesk.models import CatalogEntry, CrawlerJob
    from tourdesk.services.app_settings import crawler_settings
    from tourdesk_crawler.scheduler import schedule_catalog_images

    settings = crawler_settings(db)
    now = utcnow()
    _import(db)
    assert schedule_catalog_images(db, now, settings) is False  # in Tests abgeschaltet
    monkeypatch.setattr(get_settings(), "catalog_images", True)
    assert schedule_catalog_images(db, now, settings) is True
    assert schedule_catalog_images(db, now, settings) is False  # wartet bereits
    jobs = db.query(CrawlerJob).filter_by(job_type="catalog_images").all()
    assert len(jobs) == 1 and jobs[0].max_attempts == 1

    # einzelner Aussetzer: gleich weiter mit der nächsten Portion
    jobs[0].status, jobs[0].finished_at, jobs[0].result = "succeeded", now, {"transient": 1, "paused": False, "remaining": 8}
    db.commit()
    assert schedule_catalog_images(db, now + timedelta(minutes=1), settings) is True
    # Kontingent erschöpft: eine Viertelstunde Pause, dann die nächste Portion
    second = db.query(CrawlerJob).filter_by(job_type="catalog_images").order_by(CrawlerJob.id.desc()).first()
    second.status, second.finished_at, second.result = "partial", now, {"transient": 5, "paused": True, "remaining": 8}
    db.commit()
    assert schedule_catalog_images(db, now + timedelta(minutes=5), settings) is False
    assert schedule_catalog_images(db, now + timedelta(minutes=16), settings) is True

    # alles erledigt: kein neuer Job
    db.query(CrawlerJob).filter_by(job_type="catalog_images").update({"status": "succeeded", "finished_at": now, "result": {}})
    db.query(CatalogEntry).update({"image_status": "ok", "image_source": "deezer", "image_checked_at": now})
    db.commit()
    assert schedule_catalog_images(db, now + timedelta(minutes=30), settings) is False
    # ohne Deezer als Bildquelle wird nichts gesammelt
    db.query(CatalogEntry).update({"image_status": "unknown"})
    db.commit()
    assert schedule_catalog_images(db, now + timedelta(minutes=30), {**settings, "image_providers": ["official", "wikidata"]}) is False


@respx.mock
def test_catalog_images_job_result_is_stored(db) -> None:
    from tourdesk.models import CatalogEntry, CrawlerJob
    from tourdesk.services import catalog
    from tourdesk.services.jobs import enqueue_job
    from tourdesk_crawler.jobs.runner import execute_job

    _import(db)
    respx.get("https://api.deezer.com/search/artist").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.post(catalog.SPARQL_URL).mock(return_value=httpx.Response(200, json={"results": {"bindings": []}}))
    job = enqueue_job(db, "catalog_images", priority=-4, reason="schedule", max_attempts=1)
    db.commit()
    job_id = job.id
    status, result = execute_job(job_id)  # 8 Einträge im Deezer-Takt des Jobs (~2 s)
    assert status == "succeeded" and result["deezer_missing"] == 8
    db.expire_all()
    # der Abschluss landet in der Datenbank, obwohl die Bildabrufe die Sitzung zwischendurch freigeben
    stored = db.get(CrawlerJob, job_id)
    assert stored.status == "succeeded" and stored.finished_at is not None
    assert stored.result["remaining"] == 0
    assert {e.image_source for e in db.query(CatalogEntry)} == {"all"}


def test_meta_reports_image_progress(db, make_user, monkeypatch) -> None:
    from tourdesk.core.config import get_settings
    from tourdesk.models import CatalogEntry

    _import(db)
    alice = make_user("alice")
    first = db.query(CatalogEntry).first()
    first.image_status, first.image_source = "ok", "deezer"
    db.commit()
    # in Tests ist die Bildsuche aus → kein Fortschritt
    assert alice.get("/api/catalog/meta").json()["images"] == {"ok": 1, "pending": 0}
    monkeypatch.setattr(get_settings(), "catalog_images", True)
    assert alice.get("/api/catalog/meta").json()["images"] == {"ok": 1, "pending": 7}


def test_crawler_wikidata_image_sends_contact(db) -> None:
    from tourdesk.core.db import get_session_factory
    from tourdesk_crawler.http.client import PoliteHttpClient
    from tourdesk_crawler.images import from_wikidata
    from tourdesk_crawler.pipeline.models import ArtistSpec

    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers["user-agent"]))
        if request.url.host == "www.wikidata.org":
            return httpx.Response(200, json={"entities": {"Q1": {"claims": {"P18": [
                {"mainsnak": {"datavalue": {"value": "Band live.jpg"}}},
            ]}}}})
        return httpx.Response(200, content=_png(), headers={"content-type": "image/png"})

    settings = {"user_agent": "TourDeskBot/1.0", "timeout_s": 5, "max_retries": 0, "max_response_mb": 1,
                "cache_ttl_minutes": 30, "min_domain_interval_s": 0.0, "respect_robots": True, "allow_private_networks": False}
    http = PoliteHttpClient(get_session_factory(), settings, transport=httpx.MockTransport(handler))
    found = from_wikidata(http, ArtistSpec(id=1, name="Band", external_ids={"wikidata": "Q1"}))
    assert found is not None and found.source == "wikimedia"
    assert found.source_url == "https://commons.wikimedia.org/wiki/File:Band_live.jpg"
    assert [h for h, _ in seen] == ["www.wikidata.org", "commons.wikimedia.org"]
    assert all("github.com/Iroxx1/TourDesk" in ua for _, ua in seen)
