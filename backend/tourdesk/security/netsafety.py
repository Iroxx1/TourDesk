"""Network safety helpers (client IP classification, SSRF protection)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet")


def parse_ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not value:
        return None
    try:
        ip = ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


def is_private_client(value: str | None) -> bool:
    """True for loopback/LAN client addresses (used to allow the first-run setup)."""
    ip = parse_ip(value)
    return bool(ip and (ip.is_private or ip.is_loopback or ip.is_link_local))


class UnsafeURLError(ValueError):
    pass


def assert_public_url(url: str, *, allow_private: bool = False, resolve: bool = True) -> None:
    """Raise :class:`UnsafeURLError` if ``url`` targets a non-public address.

    Prevents server-side request forgery against the LAN (router, Proxmox UI …).
    Hostnames are resolved; every resolved address must be public.
    """
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise UnsafeURLError("Ungültige URL") from exc
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError("Nur http(s)-URLs sind erlaubt")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURLError("URL ohne Host")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs mit Zugangsdaten sind nicht erlaubt")
    if allow_private:
        return
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURLError("Interne Hostnamen sind nicht erlaubt")
    literal = parse_ip(host)
    if literal is not None:
        if is_private_ip(literal):
            raise UnsafeURLError("Private oder lokale IP-Adressen sind nicht erlaubt")
        return
    if not resolve:
        return
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # Name could not be resolved locally. When an outbound proxy resolves names for
        # us this is expected; the request itself will fail otherwise.
        return
    for info in infos:
        ip = parse_ip(info[4][0])
        if ip is not None and is_private_ip(ip):
            raise UnsafeURLError("Der Host zeigt auf eine private oder lokale Adresse")
