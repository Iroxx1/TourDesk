"""Crawler error types (stored in ``crawler_errors.error_type``)."""

from __future__ import annotations

ERROR_LABELS = {
    "http_error": "HTTP-Fehler",
    "timeout": "Zeitüberschreitung",
    "connection": "Verbindungsfehler",
    "dns": "DNS-Fehler",
    "tls": "TLS/SSL-Fehler",
    "robots_blocked": "Durch robots.txt gesperrt",
    "rate_limited": "Rate-Limit der Website",
    "too_large": "Antwort zu groß",
    "ssrf_blocked": "Interne Adresse blockiert",
    "parse_error": "Inhalt nicht auswertbar",
    "no_events": "Keine Termine gefunden",
    "config": "Konfigurationsfehler",
    "auth": "Zugangsdaten ungültig",
    "unsupported": "Nicht unterstützt",
    "unknown": "Unbekannter Fehler",
}

TRANSIENT = {"timeout", "connection", "dns", "rate_limited"}


class CrawlError(Exception):
    def __init__(
        self,
        error_type: str,
        message: str,
        *,
        url: str | None = None,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type if error_type in ERROR_LABELS else "unknown"
        self.message = message
        self.url = url
        self.status_code = status_code
        self.retry_after = retry_after

    @property
    def transient(self) -> bool:
        if self.error_type in TRANSIENT:
            return True
        return self.error_type == "http_error" and (self.status_code or 0) >= 500

    def __str__(self) -> str:  # pragma: no cover - formatting
        code = f" (HTTP {self.status_code})" if self.status_code else ""
        return f"{ERROR_LABELS.get(self.error_type, self.error_type)}{code}: {self.message}"
