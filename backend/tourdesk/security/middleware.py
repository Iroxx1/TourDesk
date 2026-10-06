"""Pure ASGI middlewares: proxy headers, security headers, access log, rate limit."""

from __future__ import annotations

import ipaddress
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from tourdesk.core.config import get_settings
from tourdesk.security.netsafety import parse_ip
from tourdesk.security.ratelimit import get_limiter

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

access_log = logging.getLogger("tourdesk.http")


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return None


class ProxyHeadersMiddleware:
    """Derive the real client IP and scheme when the direct peer is a trusted proxy
    (Cloudflare Tunnel / cloudflared, nginx, Caddy, Traefik …)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.trusted = get_settings().trusted_proxy_networks

    def _is_trusted(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None) -> bool:
        return bool(ip) and any(ip in net for net in self.trusted if ip.version == net.version)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            peer = parse_ip(client[0]) if client else None
            scope.setdefault("state", {})["peer_ip"] = str(peer) if peer else None
            if self._is_trusted(peer):
                real_ip: str | None = None
                cf_ip = _header(scope, b"cf-connecting-ip")
                if cf_ip and parse_ip(cf_ip):
                    real_ip = str(parse_ip(cf_ip))
                else:
                    xff = _header(scope, b"x-forwarded-for")
                    if xff:
                        for part in reversed([p.strip() for p in xff.split(",") if p.strip()]):
                            ip = parse_ip(part)
                            if ip is None:
                                break
                            real_ip = str(ip)
                            if not self._is_trusted(ip):
                                break
                    if real_ip is None:
                        xri = _header(scope, b"x-real-ip")
                        if xri and parse_ip(xri):
                            real_ip = str(parse_ip(xri))
                if real_ip:
                    scope["client"] = (real_ip, 0)
                proto = _header(scope, b"x-forwarded-proto")
                if proto:
                    proto = proto.split(",")[0].strip().lower()
                    if proto in ("http", "https"):
                        scope["scheme"] = proto if scope["type"] == "http" else ("wss" if proto == "https" else "ws")
        await self.app(scope, receive, send)


_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: blob:; "
    "style-src 'self'; "
    "font-src 'self' data:; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "manifest-src 'self'; "
    "worker-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        is_https = scope.get("scheme") == "https"

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                existing = {k.lower() for k, _ in headers}

                def add(name: str, value: str) -> None:
                    if name.encode() not in existing:
                        headers.append((name.encode(), value.encode()))

                add("x-content-type-options", "nosniff")
                add("x-frame-options", "DENY")
                add("referrer-policy", "strict-origin-when-cross-origin")
                add("permissions-policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()")
                add("cross-origin-opener-policy", "same-origin")
                add("cross-origin-resource-policy", "same-origin")
                add("content-security-policy", _CSP)
                if is_https:
                    add("strict-transport-security", "max-age=15552000")
                if path.startswith("/api/"):
                    add("cache-control", "no-store")
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class AccessLogMiddleware:
    """Structured access log + request id."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        request_id = _header(scope, b"x-request-id") or uuid.uuid4().hex[:16]
        request_id = "".join(ch for ch in request_id if ch.isalnum() or ch in "-_")[:64] or uuid.uuid4().hex[:16]
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        status_holder = {"status": 500, "size": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            elif message["type"] == "http.response.body":
                status_holder["size"] += len(message.get("body") or b"")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if not (path.startswith("/assets/") or path == "/api/health"):
                duration = round((time.perf_counter() - start) * 1000, 1)
                client = scope.get("client")
                status = status_holder["status"]
                level = logging.WARNING if status >= 500 else logging.INFO
                access_log.log(
                    level,
                    "%s %s %s",
                    scope.get("method"),
                    path,
                    status,
                    extra={
                        "event": "http.request",
                        "method": scope.get("method"),
                        "path": path,
                        "status": status,
                        "duration_ms": duration,
                        "bytes": status_holder["size"],
                        "client_ip": client[0] if client else None,
                        "user_id": state.get("user_id"),
                        "request_id": request_id,
                    },
                )


class ApiRateLimitMiddleware:
    """Coarse per-IP limit for the API (defence in depth)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "").startswith("/api/"):
            settings = get_settings()
            limit = settings.api_rate_limit_per_minute
            if limit > 0:
                client = scope.get("client")
                key = client[0] if client else "unknown"
                limiter = get_limiter("api", limit, 60)
                if not limiter.hit(key):
                    body = json.dumps({"detail": "Zu viele Anfragen. Bitte kurz warten."}).encode()
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 429,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"retry-after", str(limiter.retry_after(key)).encode()),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": body})
                    return
        await self.app(scope, receive, send)
