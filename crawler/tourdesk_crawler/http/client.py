"""Polite HTTP client for the crawler.

* robots.txt (cached 24 h, RFC 9309 semantics)
* per-domain rate limit shared by all threads/processes (slot reservation in
  ``crawler_domains``) + at most one in-flight request per domain and process
* timeouts, size limit, retries with exponential backoff and ``Retry-After``
* HTTP caching (fresh-cache window, ETag / Last-Modified revalidation)
* SSRF protection on every redirect hop
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import ssl
import threading
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from tourdesk.core.timeutil import utcnow
from tourdesk.models import CrawlerDomain, HttpCacheEntry
from tourdesk.security.netsafety import UnsafeURLError, assert_public_url
from tourdesk_crawler.http.errors import CrawlError

log = logging.getLogger("tourdesk.crawler")

ROBOTS_TOKEN = "TourDeskBot"
ROBOTS_TTL = timedelta(hours=24)
MAX_REDIRECTS = 5
MAX_SLOT_WAIT = 120.0
CACHEABLE_TYPES = ("text/", "application/json", "application/ld+json", "application/xml", "application/rss", "application/atom", "text/calendar", "application/xhtml")

_domain_locks: dict[str, threading.Lock] = {}
_domain_locks_guard = threading.Lock()
_robots_mem: dict[str, tuple[float, RobotFileParser | None, float | None, bool]] = {}
_robots_guard = threading.Lock()


def _domain_lock(domain: str) -> threading.Lock:
    with _domain_locks_guard:
        lock = _domain_locks.get(domain)
        if lock is None:
            lock = _domain_locks[domain] = threading.Lock()
        return lock


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str | None
    content: bytes
    elapsed_ms: int
    from_cache: bool = False
    not_modified: bool = False
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return decode_body(self.content, self.content_type)

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise CrawlError("parse_error", f"Ungültiges JSON: {exc}", url=self.url) from exc


_META_CHARSET = re.compile(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_\-]+)", re.I)


def decode_body(content: bytes, content_type: str | None) -> str:
    charset = None
    if content_type and "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=")[-1].split(";")[0].strip().strip('"')
    if charset:
        try:
            return content.decode(charset, errors="replace")
        except LookupError:
            pass
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        m = _META_CHARSET.search(content[:4096])
        if m:
            try:
                return content.decode(m.group(1).decode(), errors="replace")
            except LookupError:
                pass
        return content.decode("cp1252", errors="replace")


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


class PoliteHttpClient:
    def __init__(self, session_factory: sessionmaker[Session], settings: dict[str, Any], *, transport: httpx.BaseTransport | None = None) -> None:
        self.sf = session_factory
        self.settings = settings
        contact = (settings.get("contact") or "").strip()
        ua = settings.get("user_agent") or "TourDeskBot/1.0"
        if contact:
            ua = f"{ua} (contact: {contact})"
        self.user_agent = ua
        timeout = float(settings.get("timeout_s", 20))
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            follow_redirects=False,
            headers={
                "User-Agent": ua,
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8,fr;q=0.7,nl;q=0.5",
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            },
            transport=transport,
        )
        self.max_bytes = int(float(settings.get("max_response_mb", 5)) * 1024 * 1024)
        self.min_interval = float(settings.get("min_domain_interval_s", 3.0))
        self.max_retries = int(settings.get("max_retries", 2))
        self.cache_ttl = timedelta(minutes=int(settings.get("cache_ttl_minutes", 30)))
        self.respect_robots = bool(settings.get("respect_robots", True))
        self.allow_private = bool(settings.get("allow_private_networks", False))
        self.stats = {"requests": 0, "cache_hits": 0, "not_modified": 0, "bytes": 0, "retries": 0}

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> PoliteHttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ public API
    def fetch(
        self,
        url: str,
        *,
        api: bool = False,
        use_cache: bool = True,
        accept: str | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        max_bytes: int | None = None,
        min_interval: float | None = None,
    ) -> FetchResult:
        if params:
            url = str(httpx.URL(url, params=params))
        self._check_url(url)
        cache_key = url
        cached = self._cache_get(cache_key) if use_cache else None
        if cached is not None and utcnow() - cached.fetched_at < self.cache_ttl and cached.body is not None:
            self.stats["cache_hits"] += 1
            return FetchResult(
                url=url, final_url=cached.final_url or url, status=cached.status, content_type=cached.content_type,
                content=zlib.decompress(cached.body), elapsed_ms=0, from_cache=True,
            )
        if not api and self.respect_robots:
            allowed, delay = self._robots(url)
            if not allowed:
                raise CrawlError("robots_blocked", "Abruf laut robots.txt nicht erlaubt", url=url)
        else:
            delay = None
        req_headers = dict(headers or {})
        if accept:
            req_headers["Accept"] = accept
        if cached is not None and cached.body is not None:
            if cached.etag:
                req_headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                req_headers["If-Modified-Since"] = cached.last_modified
        result = self._request_with_retries(url, req_headers, max_bytes or self.max_bytes, max(min_interval or self.min_interval, delay or 0), api=api)
        if result.status == 304 and cached is not None and cached.body is not None:
            self.stats["not_modified"] += 1
            self._cache_touch(cache_key)
            return FetchResult(
                url=url, final_url=cached.final_url or url, status=200, content_type=cached.content_type,
                content=zlib.decompress(cached.body), elapsed_ms=result.elapsed_ms, from_cache=True, not_modified=True,
            )
        if result.status >= 400:
            raise CrawlError("http_error", f"HTTP {result.status}", url=url, status_code=result.status)
        if use_cache and result.status == 200:
            self._cache_put(cache_key, result)
        return result

    def fetch_json(self, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("accept", "application/json")
        return self.fetch(url, **kwargs).json()

    # ------------------------------------------------------------------ internals
    def _check_url(self, url: str) -> None:
        try:
            assert_public_url(url, allow_private=self.allow_private)
        except UnsafeURLError as exc:
            raise CrawlError("ssrf_blocked", str(exc), url=url) from exc

    def _request_with_retries(self, url: str, headers: dict[str, str], max_bytes: int, interval: float, *, api: bool) -> FetchResult:
        attempt = 0
        while True:
            try:
                result = self._request(url, headers, max_bytes, interval, api=api)
            except CrawlError as exc:
                if exc.transient and attempt < self.max_retries:
                    attempt += 1
                    self.stats["retries"] += 1
                    time.sleep(min(30.0, exc.retry_after or (2 ** attempt + random.random())))
                    continue
                self._record_domain_error(url, str(exc))
                raise
            if result.status in (429, 502, 503, 504) and attempt < self.max_retries:
                retry_after = _retry_after(result.headers)
                if result.status == 429 and retry_after and retry_after > 30:
                    self._block_domain(url, retry_after)
                    raise CrawlError("rate_limited", f"Website verlangt Pause ({int(retry_after)} s)", url=url, status_code=429, retry_after=retry_after)
                attempt += 1
                self.stats["retries"] += 1
                time.sleep(min(30.0, retry_after or (2 ** attempt + random.random())))
                continue
            if result.status == 429:
                self._block_domain(url, _retry_after(result.headers) or 600)
                raise CrawlError("rate_limited", "Zu viele Anfragen (HTTP 429)", url=url, status_code=429)
            if result.status >= 500:
                self._record_domain_error(url, f"HTTP {result.status}")
            return result

    def _request(self, url: str, headers: dict[str, str], max_bytes: int, interval: float, *, api: bool) -> FetchResult:
        current = url
        start = time.perf_counter()
        for _hop in range(MAX_REDIRECTS + 1):
            self._check_url(current)
            domain = (urlsplit(current).hostname or "").lower()
            redirect_to: str | None = None
            with _domain_lock(domain):
                self._wait_for_slot(domain, interval)
                try:
                    with self.client.stream("GET", current, headers=headers) as resp:
                        self.stats["requests"] += 1
                        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                            redirect_to = urljoin(current, resp.headers["location"])
                        else:
                            return self._read(url, resp, max_bytes, start)
                except httpx.TimeoutException as exc:
                    raise CrawlError("timeout", "Zeitüberschreitung beim Abruf", url=current) from exc
                except httpx.ConnectError as exc:
                    msg = str(exc)
                    if "Name or service not known" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg or "No address" in msg:
                        raise CrawlError("dns", "Domain nicht auflösbar", url=current) from exc
                    if "CERTIFICATE" in msg.upper() or "SSL" in msg.upper():
                        raise CrawlError("tls", "TLS/Zertifikatsfehler", url=current) from exc
                    raise CrawlError("connection", f"Verbindung fehlgeschlagen: {msg[:200]}", url=current) from exc
                except ssl.SSLError as exc:
                    raise CrawlError("tls", f"TLS-Fehler: {exc}", url=current) from exc
                except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.ProxyError) as exc:
                    raise CrawlError("connection", f"Verbindung abgebrochen: {str(exc)[:200]}", url=current) from exc
                except httpx.HTTPError as exc:
                    raise CrawlError("connection", f"HTTP-Fehler: {str(exc)[:200]}", url=current) from exc
            # follow the redirect outside of the domain lock
            if not api and self.respect_robots and urlsplit(redirect_to).hostname != urlsplit(current).hostname:
                allowed, _ = self._robots(redirect_to)
                if not allowed:
                    raise CrawlError("robots_blocked", "Weiterleitung auf durch robots.txt gesperrte Seite", url=redirect_to)
            current = redirect_to
        raise CrawlError("http_error", "Zu viele Weiterleitungen", url=url)

    def _read(self, url: str, resp: httpx.Response, max_bytes: int, start: float) -> FetchResult:
        chunks: list[bytes] = []
        size = 0
        declared = resp.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise CrawlError("too_large", f"Antwort größer als {max_bytes // 1024 // 1024} MB", url=str(resp.url))
        for chunk in resp.iter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise CrawlError("too_large", f"Antwort größer als {max_bytes // 1024 // 1024} MB", url=str(resp.url))
            chunks.append(chunk)
        self.stats["bytes"] += size
        return FetchResult(
            url=url,
            final_url=str(resp.url),
            status=resp.status_code,
            content_type=resp.headers.get("content-type"),
            content=b"".join(chunks),
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            headers={k.lower(): v for k, v in resp.headers.items()},
        )

    def _wait_for_slot(self, domain: str, interval: float) -> None:
        with self.sf() as s:
            row = s.execute(
                text(
                    """
                    INSERT INTO crawler_domains (domain, next_allowed_at, request_count, error_count, last_request_at)
                    VALUES (:d, now() + make_interval(secs => :i), 1, 0, now())
                    ON CONFLICT (domain) DO UPDATE SET
                        next_allowed_at = GREATEST(crawler_domains.next_allowed_at, now()) + make_interval(secs => :i),
                        request_count = crawler_domains.request_count + 1,
                        last_request_at = GREATEST(crawler_domains.next_allowed_at, now())
                    RETURNING next_allowed_at - make_interval(secs => :i) AS slot, now() AS db_now, blocked_until
                    """
                ),
                {"d": domain[:253], "i": float(interval)},
            ).one()
            s.commit()
        if row.blocked_until is not None and row.blocked_until > row.db_now:
            raise CrawlError("rate_limited", f"Domain pausiert bis {row.blocked_until:%H:%M} (Rate-Limit)", url=domain)
        wait = (row.slot - row.db_now).total_seconds()
        if wait > MAX_SLOT_WAIT:
            raise CrawlError("rate_limited", "Zu viele wartende Anfragen für diese Domain", url=domain)
        if wait > 0:
            time.sleep(wait)

    def _record_domain_error(self, url: str, message: str) -> None:
        domain = (urlsplit(url).hostname or "").lower()
        if not domain:
            return
        try:
            with self.sf() as s:
                s.execute(
                    text("UPDATE crawler_domains SET error_count = error_count + 1, last_error = :m WHERE domain = :d"),
                    {"m": message[:500], "d": domain},
                )
                s.commit()
        except Exception:  # pragma: no cover - logging only
            log.debug("could not record domain error", exc_info=True)

    def _block_domain(self, url: str, seconds: float) -> None:
        domain = (urlsplit(url).hostname or "").lower()
        with self.sf() as s:
            s.execute(
                text("UPDATE crawler_domains SET blocked_until = now() + make_interval(secs => :s) WHERE domain = :d"),
                {"s": float(min(seconds, 6 * 3600)), "d": domain},
            )
            s.commit()

    # ------------------------------------------------------------------ robots.txt
    def _robots(self, url: str) -> tuple[bool, float | None]:
        parts = urlsplit(url)
        domain = (parts.hostname or "").lower()
        origin = f"{parts.scheme}://{parts.netloc}"
        now = time.monotonic()
        with _robots_guard:
            cached = _robots_mem.get(origin)
        if cached is None or cached[0] < now:
            cached = self._load_robots(origin, domain)
            with _robots_guard:
                _robots_mem[origin] = cached
        _expires, parser, delay, disallow_all = cached
        if disallow_all:
            return False, delay
        if parser is None:
            return True, delay
        return parser.can_fetch(ROBOTS_TOKEN, url), delay

    def _load_robots(self, origin: str, domain: str) -> tuple[float, RobotFileParser | None, float | None, bool]:
        with self.sf() as s:
            row = s.get(CrawlerDomain, domain)
            if row is not None and row.robots_fetched_at and utcnow() - row.robots_fetched_at < ROBOTS_TTL:
                return self._build_robots(row.robots_status, row.robots_txt)
        status: int | None
        body = ""
        try:
            result = self._request(origin + "/robots.txt", {"Accept": "text/plain"}, 512 * 1024, self.min_interval, api=True)
            status = result.status
            body = result.text if status == 200 else ""
        except CrawlError as exc:
            if exc.error_type in ("dns", "connection", "timeout", "tls"):
                # site unreachable – the actual request will report the problem
                return (time.monotonic() + 600, None, None, False)
            status = 599
        with self.sf() as s:
            s.execute(
                text(
                    """
                    INSERT INTO crawler_domains (domain, next_allowed_at, request_count, error_count, robots_txt, robots_status, robots_fetched_at)
                    VALUES (:d, now(), 0, 0, :t, :s, now())
                    ON CONFLICT (domain) DO UPDATE SET robots_txt = :t, robots_status = :s, robots_fetched_at = now()
                    """
                ),
                {"d": domain, "t": body[:200_000], "s": status},
            )
            s.commit()
        return self._build_robots(status, body)

    def _build_robots(self, status: int | None, body: str | None) -> tuple[float, RobotFileParser | None, float | None, bool]:
        expires = time.monotonic() + 3600
        if status is None or 400 <= status < 500:
            return (expires, None, None, False)  # no robots.txt -> everything allowed
        if status >= 500:
            return (time.monotonic() + 1800, None, None, True)  # server error -> assume disallow (RFC 9309)
        parser = RobotFileParser()
        parser.parse((body or "").splitlines())
        delay = parser.crawl_delay(ROBOTS_TOKEN) or parser.crawl_delay("*")
        try:
            delay_f = float(delay) if delay is not None else None
        except (TypeError, ValueError):
            delay_f = None
        if delay_f is not None:
            delay_f = min(delay_f, 60.0)
        return (expires, parser, delay_f, False)

    # ------------------------------------------------------------------ cache
    def _cache_get(self, url: str) -> HttpCacheEntry | None:
        with self.sf() as s:
            entry = s.get(HttpCacheEntry, _url_hash(url))
            if entry is not None:
                s.expunge(entry)
            return entry

    def _cache_touch(self, url: str) -> None:
        with self.sf() as s:
            s.execute(text("UPDATE http_cache SET fetched_at = now() WHERE url_hash = :h"), {"h": _url_hash(url)})
            s.commit()

    def _cache_put(self, url: str, result: FetchResult) -> None:
        ctype = (result.content_type or "").lower()
        if not any(t in ctype for t in CACHEABLE_TYPES) or len(result.content) > 4 * 1024 * 1024:
            return
        body = zlib.compress(result.content, 6)
        with self.sf() as s:
            s.execute(
                text(
                    """
                    INSERT INTO http_cache (url_hash, url, final_url, status, etag, last_modified, content_type, body, size, fetched_at)
                    VALUES (:h, :u, :f, :st, :e, :lm, :ct, :b, :sz, now())
                    ON CONFLICT (url_hash) DO UPDATE SET final_url = :f, status = :st, etag = :e, last_modified = :lm,
                        content_type = :ct, body = :b, size = :sz, fetched_at = now()
                    """
                ),
                {
                    "h": _url_hash(url), "u": url, "f": result.final_url, "st": result.status,
                    "e": (result.headers.get("etag") or "")[:255] or None,
                    "lm": (result.headers.get("last-modified") or "")[:100] or None,
                    "ct": (result.content_type or "")[:255] or None, "b": body, "sz": len(result.content),
                },
            )
            s.commit()


def _retry_after(headers: dict[str, str]) -> float | None:
    value = headers.get("retry-after")
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(value)
        return max(0.0, (dt - datetime.now(tz=dt.tzinfo)).total_seconds())
    except (TypeError, ValueError):
        return None


def reset_robots_cache() -> None:
    with _robots_guard:
        _robots_mem.clear()
