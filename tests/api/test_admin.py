"""Admin functions: user management, overview, crawler control, sources, logs, audit."""

from __future__ import annotations

from tests.conftest import ApiClient


def _user_id(admin: ApiClient, username: str) -> int:
    return next(u["id"] for u in admin.get("/api/admin/users").json() if u["username"] == username)


def test_user_crud(admin) -> None:
    created = admin.post("/api/admin/users", json={"username": "erika", "email": "erika@example.org", "role": "user"})
    assert created.status_code == 201
    body = created.json()
    assert body["temporary_password"] and body["user"]["must_change_password"] is True
    uid = body["user"]["id"]
    assert admin.post("/api/admin/users", json={"username": "erika", "email": "x@example.org"}).status_code == 409
    upd = admin.patch(f"/api/admin/users/{uid}", json={"role": "admin", "display_name": "Erika M."})
    assert upd.status_code == 200 and upd.json()["role"] == "admin"
    reset = admin.post(f"/api/admin/users/{uid}/password", json={})
    assert reset.status_code == 200 and reset.json()["temporary_password"]
    assert admin.delete(f"/api/admin/users/{uid}").status_code == 200
    assert admin.get(f"/api/admin/users/{uid}").status_code == 404


def test_cannot_lock_out_last_admin(admin) -> None:
    me = _user_id(admin, "admin")
    assert admin.patch(f"/api/admin/users/{me}", json={"is_active": False}).status_code == 422
    assert admin.patch(f"/api/admin/users/{me}", json={"role": "user"}).status_code == 422
    assert admin.delete(f"/api/admin/users/{me}").status_code == 422


def test_admin_sees_user_artists_and_filters(admin, make_user) -> None:
    alice = make_user("alice")
    alice.post("/api/artists", json={"name": "Alice Band"})
    alice.post("/api/filters/locations", json={"level": "country", "target_id": 1})
    uid = _user_id(admin, "alice")
    assert [a["name"] for a in admin.get(f"/api/admin/users/{uid}/artists").json()] == ["Alice Band"]
    assert len(admin.get(f"/api/admin/users/{uid}/filters").json()["locations"]) == 1
    detail = admin.get(f"/api/admin/users/{uid}").json()
    assert detail["artist_count"] == 1 and detail["location_rule_count"] == 1


def test_overview_and_system(admin, make_user) -> None:
    make_user("alice")
    ov = admin.get("/api/admin/overview").json()
    assert ov["counts"]["users"] == 2
    assert set(ov["crawler_status"]) == {"ok", "partial", "error", "pending"}
    sysinfo = admin.get("/api/admin/system").json()
    assert sysinfo["database"]["ok"] is True
    assert sysinfo["counts"]["cities"] > 30000


def test_crawler_jobs_and_runs(admin, make_user) -> None:
    from tourdesk_crawler.jobs.runner import run_job_inline

    alice = make_user("alice")
    band = alice.post("/api/artists", json={"name": "Beispielband"}).json()
    assert admin.post("/api/admin/crawler/jobs", json={"job_type": "artist_crawl", "artist_id": band["id"]}).status_code == 200
    jobs = admin.get("/api/admin/crawler/jobs", params={"status": "queued"}).json()
    assert any(j["artist_id"] == band["id"] for j in jobs["items"])
    run_job_inline("artist_crawl", artist_id=band["id"])
    runs = admin.get("/api/admin/crawler/runs").json()["items"]
    assert runs[0]["artist_name"] == "Beispielband" and runs[0]["status"] == "success"
    detail = admin.get(f"/api/admin/crawler/runs/{runs[0]['id']}").json()
    assert "Crawler gestartet" in detail["log"] and "Neue Events:" in detail["log"]
    status = admin.get("/api/admin/crawler/status").json()
    assert "settings" in status and status["settings"]["api_keys"]["ticketmaster"] == ""
    events = admin.get("/api/admin/events").json()
    assert events["total"] >= 15


def test_crawler_settings_validation(admin) -> None:
    ok = admin.put("/api/admin/crawler/settings", json={"interval_minutes": 90, "api_keys": {"ticketmaster": "abc123"}})
    assert ok.status_code == 200
    data = ok.json()
    assert data["interval_minutes"] == 90 and data["api_keys"]["ticketmaster"] == "********"
    assert admin.put("/api/admin/crawler/settings", json={"interval_minutes": 1}).status_code == 422
    audit = admin.get("/api/admin/audit", params={"action": "admin.crawler_settings"}).json()
    assert audit["items"] and "abc123" not in str(audit["items"])


def test_sources_admin(admin) -> None:
    listing = admin.get("/api/admin/sources", params={"scope": "venue"}).json()
    assert listing["total"] > 10
    source = next(s for s in listing["items"] if s["venue_name"] == "Rockhal")
    upd = admin.patch(f"/api/admin/sources/{source['id']}", json={"is_enabled": False})
    assert upd.json()["is_enabled"] is False and upd.json()["status"] == "disabled"
    check = admin.post(f"/api/admin/sources/{source['id']}/check").json()
    assert admin.get(f"/api/admin/crawler/jobs/{check['job_id']}").json()["job_type"] == "source_check"


def test_explain_for_user(admin, make_user) -> None:
    from tourdesk_crawler.jobs.runner import run_job_inline

    alice = make_user("alice")
    band = alice.post("/api/artists", json={"name": "Beispielband"}).json()
    run_job_inline("artist_crawl", artist_id=band["id"])
    uid = _user_id(admin, "alice")
    event = admin.get("/api/admin/events").json()["items"][0]
    exp = admin.get(f"/api/admin/events/{event['id']}/explain", params={"user_id": uid}).json()
    assert exp["checks"][0]["message"].startswith("Künstler überwacht")
    detail = admin.get(f"/api/admin/events/{event['id']}", params={"user_id": uid}).json()
    assert detail["observations"] and detail["explanation"]


def test_audit_log_records_admin_actions(admin) -> None:
    admin.post("/api/admin/users", json={"username": "frank", "email": "frank@example.org"})
    actions = [a["action"] for a in admin.get("/api/admin/audit").json()["items"]]
    assert "admin.user_create" in actions and "auth.setup" in actions


def test_logs_endpoint(admin) -> None:
    assert admin.get("/api/admin/logs", params={"file": "api"}).status_code == 200
    assert admin.get("/api/admin/logs", params={"file": "../../etc/passwd"}).status_code == 404
