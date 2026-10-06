"""Test fixtures.

Database tests need PostgreSQL. Set ``TOURDESK_TEST_DATABASE_URL`` (default:
``postgresql+psycopg://tourdesk:tourdesk@127.0.0.1:5432/tourdesk_test``) – the database
is migrated and seeded once and cleaned between tests. ``scripts/run-tests.sh``
starts a throw-away PostgreSQL automatically if none is configured.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

TEST_DB_URL = os.environ.get(
    "TOURDESK_TEST_DATABASE_URL", "postgresql+psycopg://tourdesk:tourdesk@127.0.0.1:5432/tourdesk_test"
)
_DATA_DIR = Path(tempfile.mkdtemp(prefix="tourdesk-test-"))

os.environ["TOURDESK_DATABASE_URL"] = TEST_DB_URL
os.environ["TOURDESK_ENV"] = "test"
os.environ["TOURDESK_DATA_DIR"] = str(_DATA_DIR)
os.environ["TOURDESK_LOG_TO_FILE"] = "false"
os.environ["TOURDESK_LOG_LEVEL"] = "WARNING"
os.environ["TOURDESK_SECRET_KEY"] = "test-secret-key-for-unit-tests-only-0123456789"
os.environ["TOURDESK_GEOCODER_ENABLED"] = "false"
os.environ.setdefault("TOURDESK_API_RATE_LIMIT_PER_MINUTE", "100000")

CLEAN_STATEMENTS = [
    "DELETE FROM notification_deliveries",
    "DELETE FROM notification_channels",
    "DELETE FROM notifications",
    "DELETE FROM crawler_errors",
    "DELETE FROM crawler_runs",
    "DELETE FROM crawler_jobs",
    "DELETE FROM event_sources",
    "DELETE FROM ticket_sources",
    "DELETE FROM events",
    "DELETE FROM tours",
    "DELETE FROM sources WHERE NOT (is_auto AND scope IN ('venue', 'festival'))",
    "UPDATE sources SET status = 'new', consecutive_failures = 0, total_failures = 0, total_runs = 0, next_attempt_at = NULL,"
    " last_attempt_at = NULL, last_success_at = NULL, last_error = NULL, last_event_count = NULL",
    "DELETE FROM artists",
    "DELETE FROM audit_logs",
    "DELETE FROM sessions",
    "DELETE FROM users",
    "DELETE FROM festivals WHERE is_auto",
    "DELETE FROM venues WHERE is_auto OR created_by_user_id IS NOT NULL",
    "DELETE FROM cities WHERE is_auto OR (geonames_id IS NULL AND id NOT IN (SELECT city_id FROM venues WHERE city_id IS NOT NULL) "
    "AND id NOT IN (SELECT city_id FROM festivals WHERE city_id IS NOT NULL))",
    "DELETE FROM http_cache",
    "DELETE FROM crawler_domains",
    "DELETE FROM geocode_cache",
    "DELETE FROM system_heartbeats",
    "DELETE FROM app_settings WHERE key NOT IN ('seed_version')",
]


def _db_available() -> bool:
    try:
        import psycopg

        url = TEST_DB_URL.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(url, connect_timeout=3):
            return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    if not DB_AVAILABLE:
        pytest.skip("PostgreSQL für Tests nicht erreichbar (TOURDESK_TEST_DATABASE_URL)")
    from alembic import command

    from tourdesk.cli import _alembic_config
    from tourdesk.core.config import reset_settings_cache
    from tourdesk.core.db import dispose_engine, session_scope
    from tourdesk.seed.loader import seed_all

    reset_settings_cache()
    dispose_engine()
    command.upgrade(_alembic_config(), "head")
    with session_scope() as db:
        seed_all(db)
    yield
    dispose_engine()


@pytest.fixture()
def db(database: None) -> Iterator:
    from sqlalchemy import text

    from tourdesk.core.db import get_engine, get_session_factory
    from tourdesk.security.ratelimit import reset_all_limiters
    from tourdesk.services.app_settings import invalidate_cache
    from tourdesk_crawler.http.client import reset_robots_cache

    with get_engine().begin() as conn:
        for stmt in CLEAN_STATEMENTS:
            conn.execute(text(stmt))
    reset_all_limiters()
    invalidate_cache()
    reset_robots_cache()
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def app(db):
    from tourdesk.main import create_app

    return create_app()


class ApiClient:
    """TestClient wrapper that keeps the CSRF token of the current session."""

    def __init__(self, app, ip: str = "127.0.0.1") -> None:
        from fastapi.testclient import TestClient

        self.client = TestClient(app, base_url="http://localhost", client=(ip, 50000))
        self.csrf: str | None = None

    def _headers(self, headers: dict | None) -> dict:
        out = dict(headers or {})
        if self.csrf and "X-CSRF-Token" not in out:
            out["X-CSRF-Token"] = self.csrf
        return out

    def get(self, url: str, **kw):
        return self.client.get(url, **kw)

    def post(self, url: str, headers: dict | None = None, **kw):
        return self.client.post(url, headers=self._headers(headers), **kw)

    def put(self, url: str, headers: dict | None = None, **kw):
        return self.client.put(url, headers=self._headers(headers), **kw)

    def patch(self, url: str, headers: dict | None = None, **kw):
        return self.client.patch(url, headers=self._headers(headers), **kw)

    def delete(self, url: str, headers: dict | None = None, **kw):
        return self.client.delete(url, headers=self._headers(headers), **kw)

    def login(self, username: str, password: str):
        resp = self.client.post("/api/auth/login", json={"username": username, "password": password})
        if resp.status_code == 200:
            self.csrf = resp.json()["csrf_token"]
        return resp


ADMIN_PASSWORD = "Admin-Passwort-123"
USER_PASSWORD = "Benutzer-Passwort-123"


@pytest.fixture()
def client(app) -> ApiClient:
    return ApiClient(app)


@pytest.fixture()
def admin(app) -> ApiClient:
    c = ApiClient(app)
    resp = c.post("/api/auth/setup", json={"username": "admin", "email": "admin@example.org", "password": ADMIN_PASSWORD})
    assert resp.status_code == 201, resp.text
    c.csrf = resp.json()["csrf_token"]
    return c


@pytest.fixture()
def make_user(app, admin):
    def factory(username: str = "alice", password: str = USER_PASSWORD) -> ApiClient:
        resp = admin.post(
            "/api/admin/users",
            json={"username": username, "email": f"{username}@example.org", "password": password, "must_change_password": False},
        )
        assert resp.status_code == 201, resp.text
        c = ApiClient(app)
        assert c.login(username, password).status_code == 200
        return c

    return factory
