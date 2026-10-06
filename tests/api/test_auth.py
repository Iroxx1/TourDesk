"""Login, setup, sessions, CSRF, lockout and rate limiting."""

from __future__ import annotations

from tests.conftest import ADMIN_PASSWORD, USER_PASSWORD, ApiClient


def test_setup_only_once_and_only_from_lan(app, client) -> None:
    remote = ApiClient(app, ip="8.8.8.8")
    status = remote.get("/api/auth/setup-status").json()
    assert status["needs_setup"] is True and status["setup_allowed"] is False
    resp = remote.post("/api/auth/setup", json={"username": "evil", "email": "evil@example.org", "password": "Sehr-Langes-Passwort-1"})
    assert resp.status_code == 403

    ok = client.post("/api/auth/setup", json={"username": "admin", "email": "admin@example.org", "password": ADMIN_PASSWORD})
    assert ok.status_code == 201
    assert ok.json()["is_admin"] is True
    again = client.post("/api/auth/setup", json={"username": "admin2", "email": "a2@example.org", "password": ADMIN_PASSWORD})
    assert again.status_code == 409
    assert client.get("/api/auth/setup-status").json()["needs_setup"] is False


def test_setup_rejects_weak_password(client) -> None:
    resp = client.post("/api/auth/setup", json={"username": "admin", "email": "admin@example.org", "password": "kurz"})
    assert resp.status_code == 422


def test_login_logout_and_me(app, admin, make_user) -> None:
    make_user("alice")
    c = ApiClient(app)
    assert c.get("/api/auth/me").status_code == 401
    assert c.login("alice", "falsch").status_code == 401
    resp = c.login("ALICE@example.org", USER_PASSWORD)
    assert resp.status_code == 200
    me = c.get("/api/auth/me").json()
    assert me["user"]["username"] == "alice" and me["is_admin"] is False
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_password_hash_is_argon2(db, admin) -> None:
    from tourdesk.models import User

    user = db.query(User).filter_by(username_norm="admin").one()
    assert user.password_hash.startswith("$argon2id$")
    assert ADMIN_PASSWORD not in user.password_hash


def test_generic_error_for_unknown_user(client, admin) -> None:
    a = client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    b = client.post("/api/auth/login", json={"username": "admin", "password": "x"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_csrf_and_origin_required(admin) -> None:
    no_csrf = admin.client.put("/api/settings", json={"theme": "dark"})
    assert no_csrf.status_code == 403
    wrong = admin.client.put("/api/settings", json={"theme": "dark"}, headers={"X-CSRF-Token": "falsch"})
    assert wrong.status_code == 403
    foreign = admin.put("/api/settings", json={"theme": "dark"}, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403
    ok = admin.put("/api/settings", json={"theme": "dark"}, headers={"Origin": "http://localhost"})
    assert ok.status_code == 200 and ok.json()["theme"] == "dark"


def test_account_lockout_after_failures(app, admin, make_user) -> None:
    make_user("bob")
    c = ApiClient(app, ip="10.0.0.5")
    for _ in range(5):
        assert c.login("bob", "falsch").status_code == 401
    # the correct password is rejected while locked
    assert c.login("bob", USER_PASSWORD).status_code == 429


def test_login_rate_limit_per_ip(app, admin) -> None:
    c = ApiClient(app, ip="10.9.9.9")
    codes = [c.login(f"user{i}", "x").status_code for i in range(25)]
    assert 429 in codes


def test_inactive_user_cannot_login_and_sessions_end(app, admin, make_user, db) -> None:
    alice = make_user("alice")
    users = admin.get("/api/admin/users").json()
    alice_id = next(u["id"] for u in users if u["username"] == "alice")
    assert admin.patch(f"/api/admin/users/{alice_id}", json={"is_active": False}).status_code == 200
    assert alice.get("/api/auth/me").status_code == 401
    c = ApiClient(app)
    assert c.login("alice", USER_PASSWORD).status_code == 403


def test_password_change_revokes_other_sessions(app, admin, make_user) -> None:
    first = make_user("carol")
    second = ApiClient(app)
    second.login("carol", USER_PASSWORD)
    resp = first.post("/api/users/me/password", json={"current_password": USER_PASSWORD, "new_password": "Neues-Passwort-456"})
    assert resp.status_code == 200
    assert first.get("/api/auth/me").status_code == 200
    assert second.get("/api/auth/me").status_code == 401


def test_must_change_password_blocks_api(app, admin) -> None:
    resp = admin.post("/api/admin/users", json={"username": "dave", "email": "dave@example.org"})
    assert resp.status_code == 201
    temp = resp.json()["temporary_password"]
    assert temp
    c = ApiClient(app)
    assert c.login("dave", temp).status_code == 200
    assert c.get("/api/auth/me").json()["user"]["must_change_password"] is True
    blocked = c.get("/api/artists")
    assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"
    assert c.post("/api/users/me/password", json={"current_password": temp, "new_password": "Dave-Neues-Passwort-1"}).status_code == 200
    assert c.get("/api/artists").status_code == 200


def test_security_headers(client) -> None:
    resp = client.get("/api/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["cache-control"] == "no-store"


def test_proxy_headers_from_trusted_proxy(app, admin) -> None:
    """Behind cloudflared (127.0.0.1) the real client IP comes from CF-Connecting-IP and https is detected."""
    c = ApiClient(app, ip="127.0.0.1")
    resp = c.client.post(
        "/api/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
        headers={"CF-Connecting-IP": "198.51.100.23", "X-Forwarded-Proto": "https"},
    )
    assert resp.status_code == 200
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith("__Host-td_session=") and "Secure" in cookie
    assert "strict-transport-security" in resp.headers


def test_untrusted_peer_cannot_spoof_ip(app, admin) -> None:
    """A direct client (not a trusted proxy) cannot fake its IP to get around setup restrictions."""
    c = ApiClient(app, ip="8.8.4.4")
    status = c.client.get("/api/auth/setup-status", headers={"X-Forwarded-For": "192.168.1.10"}).json()
    assert status["setup_allowed"] is False
