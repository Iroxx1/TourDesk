"""Politeness and safety of the crawler HTTP client (mocked transport, real DB for state)."""

from __future__ import annotations

import time

import httpx
import pytest

from tourdesk.core.db import get_session_factory
from tourdesk_crawler.http.client import PoliteHttpClient
from tourdesk_crawler.http.errors import CrawlError

BASE_SETTINGS = {
    "user_agent": "TourDeskBot/1.0", "contact": "admin@example.org", "timeout_s": 5, "max_retries": 2,
    "max_response_mb": 1, "cache_ttl_minutes": 30, "min_domain_interval_s": 0.0, "respect_robots": True,
    "allow_private_networks": False,
}


def make_client(handler, **overrides) -> PoliteHttpClient:
    return PoliteHttpClient(get_session_factory(), {**BASE_SETTINGS, **overrides}, transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("tourdesk_crawler.http.client.time.sleep", lambda s: sleeps.append(s))
    return sleeps


def test_user_agent_and_robots_allow(db) -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})

    with make_client(handler) as http:
        res = http.fetch("https://band-a.test/tour")
        assert res.status == 200 and "ok" in res.text
        assert "TourDeskBot" in seen["ua"] and "admin@example.org" in seen["ua"]
        with pytest.raises(CrawlError) as exc:
            http.fetch("https://band-a.test/private/page")
        assert exc.value.error_type == "robots_blocked"


def test_robots_disallow_for_our_bot(db) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: TourDeskBot\nDisallow: /\n")
        return httpx.Response(200, text="should not be fetched")

    with make_client(handler) as http, pytest.raises(CrawlError) as exc:
        http.fetch("https://band-b.test/")
    assert exc.value.error_type == "robots_blocked"


def test_retry_with_backoff_on_503(db, _no_sleep) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, headers={"retry-after": "2"})
        return httpx.Response(200, text="finally", headers={"content-type": "text/html"})

    with make_client(handler) as http:
        assert http.fetch("https://band-c.test/tour").text == "finally"
    assert calls["n"] == 3
    assert 2.0 in _no_sleep  # Retry-After honoured


def test_gives_up_after_retries(db) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ConnectTimeout("timeout", request=request)

    with make_client(handler) as http, pytest.raises(CrawlError) as exc:
        http.fetch("https://band-d.test/tour")
    assert exc.value.error_type == "timeout"


def test_conditional_request_and_cache(db) -> None:
    calls = {"plain": 0, "conditional": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.headers.get("if-none-match") == '"v1"':
            calls["conditional"] += 1
            return httpx.Response(304)
        calls["plain"] += 1
        return httpx.Response(200, text="<p>dates</p>", headers={"content-type": "text/html", "etag": '"v1"'})

    with make_client(handler, cache_ttl_minutes=0) as http:
        first = http.fetch("https://band-e.test/tour")
        second = http.fetch("https://band-e.test/tour")
    assert first.text == second.text == "<p>dates</p>"
    assert second.not_modified and calls == {"plain": 1, "conditional": 1}

    with make_client(handler, cache_ttl_minutes=30) as http:
        third = http.fetch("https://band-e.test/tour")
    assert third.from_cache and calls == {"plain": 1, "conditional": 1}  # served from fresh cache


def test_size_limit(db) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024), headers={"content-type": "text/html"})

    with make_client(handler) as http, pytest.raises(CrawlError) as exc:
        http.fetch("https://band-f.test/huge")
    assert exc.value.error_type == "too_large"


def test_ssrf_protection(db) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8006/api2/json"})

    with make_client(handler) as http:
        for url in ("http://192.168.1.1/", "http://10.0.0.1/admin", "http://localhost:8080/", "http://router.local/"):
            with pytest.raises(CrawlError) as exc:
                http.fetch(url)
            assert exc.value.error_type == "ssrf_blocked"
        with pytest.raises(CrawlError) as exc:
            http.fetch("https://evil-redirect.test/")
        assert exc.value.error_type == "ssrf_blocked"


def test_per_domain_spacing(db, monkeypatch) -> None:
    """Requests to the same domain are spaced by the configured interval (shared via the DB)."""
    monkeypatch.undo()  # real sleeping for this test
    stamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        stamps.append(time.monotonic())
        return httpx.Response(200, text="ok", headers={"content-type": "text/html"})

    with make_client(handler, min_domain_interval_s=1.0, cache_ttl_minutes=0) as http:
        http.fetch("https://other-domain.test/warm", use_cache=False)
        http.fetch("https://spaced.test/a", use_cache=False)
        http.fetch("https://spaced.test/b", use_cache=False)
        http.fetch("https://other-domain.test/c", use_cache=False)
    assert stamps[2] - stamps[1] >= 0.9  # same domain: spaced
    assert stamps[3] - stamps[2] < 0.9  # other domains are not delayed


def test_429_blocks_domain(db) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(429, headers={"retry-after": "3600"})

    with make_client(handler) as http:
        with pytest.raises(CrawlError) as exc:
            http.fetch("https://busy.test/x")
        assert exc.value.error_type == "rate_limited"
        with pytest.raises(CrawlError) as exc2:
            http.fetch("https://busy.test/y")
        assert exc2.value.error_type == "rate_limited"
