"""DemoProvider – deterministic tour data for the fictional "Beispielband".

It lets a fresh installation show working tiles, filters, festival switch and
tour status without depending on external websites. Real artists never use it.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from tourdesk_crawler.pipeline.models import ArtistSpec, ProviderResult, RawEvent, SourceSpec
from tourdesk_crawler.providers.base import CrawlerProvider, ProviderContext, register

# (day offset, venue, city, country, ticket status, extra)
_TOUR = [
    (-8, "Zénith Paris – La Villette", "Paris", "FR", "sold_out", {}),
    (-6, "Melkweg", "Amsterdam", "NL", "available", {}),
    (-4, "Ancienne Belgique", "Brüssel", "BE", "available", {}),
    (-2, "Palladium Köln", "Köln", "DE", "available", {}),
    (3, "Rockhal", "Esch-sur-Alzette", "LU", "sold_out", {}),
    (5, "Garage", "Saarbrücken", "DE", "limited", {}),
    (7, "Neue Gebläsehalle", "Neunkirchen", "DE", "available", {"region": "Saarland"}),
    (10, "Luxexpo The Box", "Luxembourg", "LU", "available", {}),
    (11, "den Atelier", "Luxembourg", "LU", "available", {}),
    (13, "Arena Trier", "Trier", "DE", "available", {}),
    (15, "BAM – Boîte à Musiques", "Metz", "FR", "available", {}),
    (17, "La Laiterie", "Strasbourg", "FR", "not_on_sale", {}),
    (18, "L'Autre Canal", "Nancy", "FR", "available", {}),
    (21, "Zenith München", "München", "DE", "available", {"status": "cancelled"}),
    (23, "Gasometer Wien", "Wien", "AT", "available", {}),
    (25, "Hallenstadion", "Zürich", "CH", "available", {"support": True}),
    (48, "E-Werk Saarbrücken", "Saarbrücken", "DE", "not_on_sale", {"special": True}),
]


def _next_weekday(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday()) % 7)


@register
class DemoProvider(CrawlerProvider):
    key = "demo"
    label = "Demo-Quelle"
    scopes = ("artist",)
    default_trust = 1

    def fetch(self, ctx: ProviderContext, source: SourceSpec, artist: ArtistSpec | None) -> ProviderResult:
        assert artist is not None
        anchor_raw = source.config.get("anchor")
        anchor = date.fromisoformat(anchor_raw) if anchor_raw else ctx.today
        result = ProviderResult(method="demo", pages=0, http_status=200)
        if not anchor_raw:
            result.discovered["anchor"] = anchor.isoformat()
        tour_name = f"Lichter der Stadt Tour {anchor.year}"
        base = "https://example.org/beispielband"
        for offset, venue, city, country, ticket, extra in _TOUR:
            d = anchor + timedelta(days=offset)
            title = f"{artist.name} – {tour_name}"
            performers = [artist.name]
            hint = None
            if extra.get("support"):
                title = f"Die Nachtfalter – Europa Tour · Support: {artist.name}"
                performers = ["Die Nachtfalter", artist.name]
                hint = "support"
            if extra.get("special"):
                title = f"{artist.name} – Akustik-Release-Party"
                hint = "special"
            result.events.append(
                RawEvent(
                    start_date=d,
                    start_time=time(20, 0),
                    doors_time=time(19, 0),
                    title=title,
                    performers=performers,
                    venue_name=venue,
                    city=city,
                    region=extra.get("region"),
                    country=country,
                    url=f"{base}/tour#{d.isoformat()}",
                    ticket_url=None if ticket == "not_on_sale" else f"https://example.org/tickets/beispielband/{d.isoformat()}",
                    ticket_status=ticket,
                    ticket_provider="Beispiel-Tickets",
                    status=extra.get("status"),
                    tour_name=tour_name if not hint else None,
                    event_type_hint=hint,
                    external_id=f"demo-{d.isoformat()}-{city.lower()}",
                    method="demo",
                    confidence=1.0,
                )
            )
        # festival appearances next summer: Rock am Ring (RLP) and Rocco del Schlacko (Saarland)
        june = date(anchor.year + (1 if anchor.month >= 6 else 0), 6, 1)
        rar = _next_weekday(june, 4)
        august = date(anchor.year + (1 if anchor.month >= 8 else 0), 8, 6)
        rds = _next_weekday(august, 4)
        for d, fest, city, country, region in (
            (rar, "Rock am Ring", "Nürburg", "DE", "Rheinland-Pfalz"),
            (rds, "Rocco del Schlacko", "Püttlingen", "DE", "Saarland"),
        ):
            result.events.append(
                RawEvent(
                    start_date=d,
                    end_date=d + timedelta(days=2),
                    title=fest,
                    performers=["Headliner", artist.name],
                    city=city,
                    region=region,
                    country=country,
                    url=f"{base}/festivals",
                    ticket_status="available",
                    event_type_hint="festival",
                    festival_name=fest,
                    external_id=f"demo-fest-{d.isoformat()}",
                    method="demo",
                    confidence=1.0,
                )
            )
        return result
