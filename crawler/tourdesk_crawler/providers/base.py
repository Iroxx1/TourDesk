"""Provider (adapter) base classes and registry.

Adding a new source = subclass :class:`CrawlerProvider`, implement ``fetch`` and
decorate it with :func:`register`. See ``docs/PROVIDERS.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar

from sqlalchemy.orm import Session

from tourdesk_crawler.http.client import PoliteHttpClient
from tourdesk_crawler.pipeline.geo_resolver import GeoResolver
from tourdesk_crawler.pipeline.models import ArtistSpec, ProviderResult, SourceSpec


@dataclass
class RunLog:
    lines: list[str] = field(default_factory=list)

    def info(self, msg: str) -> None:
        self.lines.append(msg)

    def ok(self, msg: str) -> None:
        self.lines.append(f"  ✓ {msg}")

    def warn(self, msg: str) -> None:
        self.lines.append(f"  ! {msg}")

    def fail(self, msg: str) -> None:
        self.lines.append(f"  ✗ {msg}")

    def text(self, limit: int = 60_000) -> str:
        out = "\n".join(self.lines)
        return out if len(out) <= limit else out[: limit - 20] + "\n… (gekürzt)"


@dataclass
class ProviderContext:
    db: Session
    http: PoliteHttpClient
    settings: dict[str, Any]
    today: date
    geo: GeoResolver
    log: RunLog
    api_key: Callable[[str], str | None]
    dry_run: bool = False


class CrawlerProvider:
    key: ClassVar[str] = ""
    label: ClassVar[str] = ""
    scopes: ClassVar[tuple[str, ...]] = ("artist",)
    default_trust: ClassVar[int] = 6
    #: events must be matched against monitored artists (pages listing many artists)
    needs_artist_match: ClassVar[bool] = False
    #: API key name in the crawler settings, if any
    api_key_name: ClassVar[str | None] = None

    def unavailable_reason(self, ctx: ProviderContext) -> str | None:
        if self.api_key_name and not ctx.api_key(self.api_key_name):
            return f"Kein API-Schlüssel für {self.label} hinterlegt"
        if not ctx.settings.get("providers", {}).get(self.key, True):
            return f"{self.label} ist in den Crawler-Einstellungen deaktiviert"
        return None

    def fetch(self, ctx: ProviderContext, source: SourceSpec, artist: ArtistSpec | None) -> ProviderResult:  # pragma: no cover
        raise NotImplementedError


_REGISTRY: dict[str, CrawlerProvider] = {}


def register(cls: type[CrawlerProvider]) -> type[CrawlerProvider]:
    _REGISTRY[cls.key] = cls()
    return cls


def get_provider(key: str) -> CrawlerProvider | None:
    _load_all()
    return _REGISTRY.get(key)


def all_providers() -> dict[str, CrawlerProvider]:
    _load_all()
    return dict(_REGISTRY)


_loaded = False


def _load_all() -> None:
    global _loaded
    if _loaded:
        return
    # import modules for their @register side effects
    from tourdesk_crawler.providers import apis, demo, festival, ical, web  # noqa: F401

    _loaded = True
