"""Users must never see data of other users; admin endpoints are protected."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "path",
    ["/api/admin/overview", "/api/admin/users", "/api/admin/system", "/api/admin/logs", "/api/admin/audit",
     "/api/admin/crawler/status", "/api/admin/crawler/runs", "/api/admin/sources", "/api/admin/events"],
)
def test_user_cannot_access_admin(make_user, path: str) -> None:
    alice = make_user("alice")
    assert alice.get(path).status_code == 403


def test_anonymous_gets_401(client) -> None:
    for path in ("/api/artists", "/api/dashboard", "/api/filters", "/api/admin/users", "/api/events"):
        assert client.get(path).status_code == 401


def test_users_are_isolated(make_user) -> None:
    alice = make_user("alice")
    bob = make_user("bob")
    a = alice.post("/api/artists", json={"name": "Alice Lieblingsband"}).json()
    # bob does not see alice's artist
    assert bob.get("/api/artists").json() == []
    assert bob.get(f"/api/artists/{a['id']}").status_code == 404
    assert bob.get(f"/api/artists/{a['id']}/events").status_code == 404
    assert bob.patch(f"/api/artists/{a['id']}", json={"show_festivals": True}).status_code == 404
    assert bob.delete(f"/api/artists/{a['id']}").status_code == 404
    # location rules are private
    rules = alice.post("/api/filters/locations", json={"level": "country", "target_id": 1}).json()
    key = rules[0]["key"]
    assert bob.delete(f"/api/filters/locations/{key}").status_code == 404
    assert bob.get("/api/filters").json()["locations"] == []
    assert len(alice.get("/api/filters").json()["locations"]) == 1


def test_event_of_unfollowed_artist_is_hidden(db, make_user) -> None:
    from datetime import date, timedelta

    from tourdesk.core.timeutil import utcnow
    from tourdesk.models import Event

    alice = make_user("alice")
    bob = make_user("bob")
    artist = alice.post("/api/artists", json={"name": "Geheime Band"}).json()
    e = Event(artist_id=artist["id"], event_date=date.today() + timedelta(days=10), dedup_key="x",
              first_seen_at=utcnow(), last_seen_at=utcnow(), is_confirmed=True)
    db.add(e)
    db.commit()
    assert alice.get(f"/api/events/{e.id}").status_code == 200
    assert bob.get(f"/api/events/{e.id}").status_code == 404


def test_impersonation_is_read_only_and_audited(admin, make_user) -> None:
    alice = make_user("alice")
    alice.post("/api/artists", json={"name": "Alice Band"})
    users = admin.get("/api/admin/users").json()
    alice_id = next(u["id"] for u in users if u["username"] == "alice")
    me = admin.post(f"/api/admin/users/{alice_id}/impersonate").json()
    assert me["user"]["username"] == "alice"
    assert me["impersonation"]["admin"]["username"] == "admin"
    # the admin now sees exactly alice's data …
    assert [a["name"] for a in admin.get("/api/artists").json()] == ["Alice Band"]
    # … but cannot change anything
    blocked = admin.put("/api/settings", json={"theme": "dark"})
    assert blocked.status_code == 403
    assert admin.post("/api/artists", json={"name": "Neu"}).status_code == 403
    # stopping is allowed
    back = admin.post("/api/admin/impersonation/stop").json()
    assert back["user"]["username"] == "admin" and back["impersonation"] is None
    actions = [a["action"] for a in admin.get("/api/admin/audit").json()["items"]]
    assert "admin.impersonation_start" in actions and "admin.impersonation_stop" in actions


def test_user_cannot_edit_shared_city(make_user) -> None:
    alice = make_user("alice")
    city = alice.get("/api/cities", params={"q": "Saarbrücken"}).json()[0]
    assert alice.patch(f"/api/cities/{city['id']}", json={"region_id": None}).status_code == 403
