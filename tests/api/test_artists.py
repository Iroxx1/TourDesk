"""Artist management (shared catalogue + personal subscriptions)."""

from __future__ import annotations


def test_add_artist_creates_catalog_subscription_and_jobs(db, make_user) -> None:
    from tourdesk.models import CrawlerJob, Source

    alice = make_user("alice")
    resp = alice.post(
        "/api/artists",
        json={"name": "Backstreet Boys", "official_website": "backstreetboys.com", "aliases": ["BSB"], "genre": "Pop"},
    )
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert a["official_website"] == "https://backstreetboys.com"
    assert a["aliases"] == ["BSB"]
    assert a["subscription"]["show_festivals"] is False  # default OFF
    assert a["images"]["tile"].endswith(".svg?v=1")  # generated placeholder
    jobs = {j.job_type for j in db.query(CrawlerJob).filter_by(artist_id=a["id"])}
    assert jobs == {"artist_crawl", "artist_enrich"}
    sources = db.query(Source).filter_by(artist_id=a["id"]).all()
    assert [s.provider for s in sources] == ["official_website"]

    dup = alice.post("/api/artists", json={"name": "backstreet boys"})
    assert dup.status_code == 409


def test_second_user_shares_catalog_entry(make_user) -> None:
    alice = make_user("alice")
    bob = make_user("bob")
    a = alice.post("/api/artists", json={"name": "Metallica"}).json()
    b = bob.post("/api/artists", json={"name": "METALLICA", "show_festivals": True}).json()
    assert a["id"] == b["id"]
    assert b["subscription"]["show_festivals"] is True
    assert alice.get(f"/api/artists/{a['id']}").json()["subscription"]["show_festivals"] is False


def test_festival_switch_and_active_toggle(make_user) -> None:
    alice = make_user("alice")
    a = alice.post("/api/artists", json={"name": "Linkin Park"}).json()
    upd = alice.patch(f"/api/artists/{a['id']}", json={"show_festivals": True, "is_active": False}).json()
    assert upd["subscription"]["show_festivals"] is True
    assert upd["subscription"]["is_active"] is False


def test_edit_catalog_fields(make_user) -> None:
    alice = make_user("alice")
    a = alice.post("/api/artists", json={"name": "Die Ärzte"}).json()
    upd = alice.patch(f"/api/artists/{a['id']}", json={"aliases": ["DÄ", "Die Aerzte"], "search_terms": ["Die Ärzte Tour"], "genre": "Punk"}).json()
    assert set(upd["aliases"]) == {"DÄ", "Die Aerzte"}
    assert upd["search_terms"] == ["Die Ärzte Tour"]
    assert upd["genre"] == "Punk"


def test_unfollow(make_user) -> None:
    alice = make_user("alice")
    a = alice.post("/api/artists", json={"name": "Toto"}).json()
    assert alice.delete(f"/api/artists/{a['id']}").status_code == 200
    assert alice.get("/api/artists").json() == []


def test_sources_and_ssrf_protection(make_user) -> None:
    alice = make_user("alice")
    a = alice.post("/api/artists", json={"name": "Muse"}).json()
    bad = alice.post(f"/api/artists/{a['id']}/sources", json={"url": "http://127.0.0.1:8006/", "provider": "tour_page"})
    assert bad.status_code == 422
    bad2 = alice.post(f"/api/artists/{a['id']}/sources", json={"url": "http://router.local/admin", "provider": "tour_page"})
    assert bad2.status_code == 422
    bad3 = alice.post(f"/api/artists/{a['id']}/sources", json={"url": "javascript:alert(1)", "provider": "tour_page"})
    assert bad3.status_code == 422
    ok = alice.post(f"/api/artists/{a['id']}/sources", json={"url": "https://muse.mu/tour", "provider": "tour_page"})
    assert ok.status_code == 201
    listing = alice.get(f"/api/artists/{a['id']}/sources").json()
    assert any(s["url"] == "https://muse.mu/tour" and s["can_delete"] for s in listing["sources"])
    sid = ok.json()["id"]
    assert alice.delete(f"/api/artists/{a['id']}/sources/{sid}").status_code == 200


def test_refresh_cooldown(make_user) -> None:
    alice = make_user("alice")
    a = alice.post("/api/artists", json={"name": "Rammstein"}).json()
    assert alice.post(f"/api/artists/{a['id']}/refresh").status_code == 200
    assert alice.post(f"/api/artists/{a['id']}/refresh").status_code == 429


def test_lookup_finds_catalog(make_user) -> None:
    alice = make_user("alice")
    bob = make_user("bob")
    alice.post("/api/artists", json={"name": "Imagine Dragons"})
    hits = bob.get("/api/artists/lookup", params={"q": "imagine", "external": "false"}).json()
    assert hits and hits[0]["name"] == "Imagine Dragons" and hits[0]["followed"] is False


def test_demo_artist_gets_demo_source(db, make_user) -> None:
    from tourdesk.models import Source

    alice = make_user("alice")
    a = alice.post("/api/artists", json={"name": "Beispielband"}).json()
    assert a["is_demo"] is True
    assert [s.provider for s in db.query(Source).filter_by(artist_id=a["id"])] == ["demo"]
