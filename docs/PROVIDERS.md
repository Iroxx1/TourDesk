# Crawler-Provider – Quellen anbinden und erweitern

TourDesk bindet jede Art von Quelle über einen **Provider** (Adapter) an. Ein Provider weiß nur,
wie man Termine von *einer Art* Quelle holt – alles andere (Höflichkeit gegenüber Websites,
Ortserkennung, Deduplizierung, Vertrauensstufen, Absagen, Benachrichtigungen) erledigt die
gemeinsame Pipeline.

```text
Scheduler ──► crawler_jobs ──► Worker
                                 │  Job „artist_crawl“ / „source_crawl“
                                 ▼
                       Provider.fetch(ctx, source, artist) ──► ProviderResult(RawEvent…)
                                 │
                 ┌───────────────┼──────────────────────────────────────────────┐
                 ▼               ▼                ▼                ▼            ▼
          ArtistMatcher    EventNormalizer   GeoResolver     EventDeduplicator   Store
          (nur bei Seiten  (Datum, Uhrzeit,  (Venue → Stadt  (Künstler + Datum  (event_sources,
          mit vielen       Typ, Status,      → Region →      + Venue/Stadt)     ticket_sources,
          Künstlern)       Tickets, Tour)    Land)                              Bestätigung,
                                                                                Absagen, Delisting,
                                                                                Benachrichtigungen)
```

## Vorhandene Provider

| Key                | Bezeichnung              | Bereich           | Vertrauen | Hinweise |
|--------------------|--------------------------|-------------------|:---------:|----------|
| `official_website` | Offizielle Website       | Künstler          | 1 | wird automatisch aus der Künstler-Website angelegt, sucht Tour-/Live-Unterseiten |
| `tour_page`        | Tourseite                | Künstler          | 1 | vom Benutzer eingetragene Tourseite |
| `ical_feed`        | iCal-Feed                | Künstler, Venue, global | 2 | `.ics`-Kalender |
| `venue_website`    | Veranstaltungsort        | Venue             | 2 | Programmseiten der Venues, Abgleich mit überwachten Künstlern |
| `festival_lineup`  | Festival-Line-up         | Festival          | 3 | Line-up-Seiten; nur bestätigte Auftritte werden Termine |
| `promoter_website` | Veranstalter             | global            | 3 | Veranstalterkalender |
| `ticketmaster`     | Ticketmaster             | Künstler          | 4 | Discovery-API, API-Schlüssel nötig |
| `bandsintown`      | Bandsintown              | Künstler          | 4 | App-ID nötig |
| `ticket_listing`   | Ticketseite              | global, Künstler  | 4 | öffentliche Ticketlisten |
| `songkick`         | Songkick                 | Künstler          | 5 | API-Schlüssel nötig |
| `generic_web`      | Webseite                 | Künstler, global  | 6 | beliebige Seite mit Terminliste |
| `demo`             | Demo-Quelle              | Künstler          | 1 | erzeugt die Tour der fiktiven „Beispielband“ |

Die Vertrauensstufen entsprechen der Vorgabe: 1 offizielle Künstlerwebsite, 2 offizieller
Veranstaltungsort, 3 Veranstalter/Festival, 4 offizieller Ticketanbieter, 5 Ticketbörse/Plattform,
6 sonstige Quelle. Ein Termin gilt als **bestätigt**, wenn er von einer Quelle der Stufe 1–4
stammt oder von mindestens zwei unabhängigen Quellen gemeldet wird („3 Quellen bestätigen
diesen Termin“). Unbestätigte Festival-Gerüchte werden nie als bestätigte Termine angezeigt.

Die Seiten-Provider (`official_website`, `tour_page`, `venue_website`, …) werten der Reihe nach
aus: JSON-LD (`schema.org/Event`), Microdata, eingebettete JSON-Daten (z. B. Next.js/Nuxt),
iCal-Links und zuletzt eine Heuristik für Terminlisten. Ein Headless-Browser ist dafür nicht
nötig; Seiten, die Termine ausschließlich per JavaScript nachladen, liefern ihre Daten fast immer
über eine JSON-Schnittstelle oder einen Kalender-Feed – dafür schreibt man besser einen kleinen
API-Provider (siehe unten).

## Einen neuen Provider hinzufügen

### 1. Klasse schreiben

Neue Datei `crawler/tourdesk_crawler/providers/mein_anbieter.py`:

```python
"""Beispiel: Konzertkalender eines Veranstalters mit JSON-API."""

from __future__ import annotations

from datetime import date, time

from tourdesk_crawler.http.errors import CrawlError
from tourdesk_crawler.pipeline.models import ArtistSpec, ProviderResult, RawEvent, SourceSpec
from tourdesk_crawler.providers.base import CrawlerProvider, ProviderContext, register


@register
class MeinAnbieterProvider(CrawlerProvider):
    key = "mein_anbieter"              # eindeutiger Schlüssel (sources.provider)
    label = "Mein Anbieter"            # Anzeige im Admin-Bereich
    scopes = ("global",)               # artist | venue | festival | global
    default_trust = 3                  # 1 (offiziell) … 6 (sonstige)
    needs_artist_match = True          # Seite listet viele Künstler → mit überwachten abgleichen
    api_key_name = None                # z. B. "mein_anbieter", wenn ein Schlüssel nötig ist

    def fetch(self, ctx: ProviderContext, source: SourceSpec, artist: ArtistSpec | None) -> ProviderResult:
        if not source.url:
            raise CrawlError("config", "Keine URL hinterlegt")
        # Immer ctx.http verwenden: robots.txt, Rate-Limit pro Domain, Timeouts, Retries,
        # Caching (ETag/Last-Modified), Größenlimit und SSRF-Schutz sind dort eingebaut.
        page = ctx.http.fetch(source.url, api=True, params={"from": ctx.today.isoformat()})
        data = page.json()
        result = ProviderResult(method="api", pages=1, http_status=page.status)
        for item in data.get("events", []):
            try:
                day = date.fromisoformat(item["date"][:10])
            except (KeyError, ValueError):
                result.warnings.append(f"Unlesbares Datum: {item.get('date')!r}")
                continue
            result.events.append(
                RawEvent(
                    start_date=day,
                    start_time=time.fromisoformat(item["time"]) if item.get("time") else None,
                    title=item.get("title"),
                    performers=[p["name"] for p in item.get("artists", [])],
                    venue_name=item.get("venue"),
                    city=item.get("city"),
                    country=item.get("country"),          # ISO-Code oder Name
                    url=item.get("url"),                  # Original-Eintrag
                    ticket_url=item.get("ticket_url"),    # echte Ticketseite
                    ticket_status=item.get("availability"),
                    status="cancelled" if item.get("cancelled") else None,
                    event_type_hint="festival" if item.get("is_festival") else None,
                    method="api",
                    confidence=0.85,
                )
            )
        ctx.log.ok(f"{len(result.events)} Termine von {source.name}")
        return result
```

Wichtige Regeln:

* **Nur `ctx.http` für Netzwerkzugriffe** – niemals direkt `httpx`/`requests`. Nur so gelten
  Höflichkeitsregeln, Caching und der Schutz vor Zugriffen auf interne Adressen.
* **Fehler als `CrawlError(typ, meldung)` werfen** (`http_error`, `timeout`, `parse_error`,
  `config`, `auth`, `no_events`, …). Die Pipeline protokolliert sie, erhöht den Fehlerzähler der
  Quelle, plant den nächsten Versuch mit Backoff und **löscht keine Termine** wegen eines Fehlers.
* **Nichts erfinden** – fehlende Felder bleiben `None`. Status- und Ticketwerte dürfen im
  Klartext kommen („ausverkauft“, „sold out“, „SoldOut“), der Normalizer übersetzt sie.
* Bei Seiten mit vielen Künstlern `needs_artist_match = True` setzen und `performers` bzw.
  `title` befüllen; der Matcher ordnet die Termine den überwachten Künstlern zu (inkl.
  Aliasse, Tribute-/Cover-Erkennung).
* Festival-Line-ups ohne konkreten Auftrittstag gehören in `result.lineup` (Liste von Namen),
  nicht als Termin.

### 2. Registrieren

1. Modul in `crawler/tourdesk_crawler/providers/base.py` in `_load_all()` importieren.
2. Eintrag in `backend/tourdesk/core/constants.py` → `PROVIDERS` ergänzen
   (`label`, `scope`, `trust`, `user_addable`). `user_addable: True` erlaubt Benutzern, die
   Quelle selbst beim Künstler einzutragen.
3. In `backend/tourdesk/services/app_settings.py` den Provider in `_defaults()["providers"]`
   aufnehmen (ein/aus im Admin-Bereich), ggf. den API-Schlüssel unter `api_keys`.

### 3. Quelle anlegen

* **Admin-Bereich → Quellen → „+ Quelle“**: Bereich, Provider, Name, URL und Vertrauensstufe
  wählen. Mit **„Prüfen (Probelauf)“** wird die Quelle abgerufen und ausgewertet, ohne Termine
  zu speichern – ideal zum Testen.
* Künstlerquellen können Benutzer im Künstlerfenster unter **Quellen** eintragen
  (nur Provider mit `user_addable`).
* Venue-Programme entstehen automatisch beim Anlegen eines Veranstaltungsorts mit
  Programm-URL.

### 4. Testen

Tests laufen gegen eine echte PostgreSQL-Testdatenbank; das Internet wird mit
`httpx.MockTransport` ersetzt (siehe `tests/crawler/test_pipeline.py`):

```python
import httpx
import tourdesk_crawler.jobs.context as job_context
from tourdesk_crawler.jobs.runner import run_job_inline

def test_mein_anbieter(db, monkeypatch, make_user):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, json={"events": [{"date": "2027-03-12", "venue": "Rockhal",
                                                      "city": "Esch-sur-Alzette", "country": "LU",
                                                      "artists": [{"name": "Testband"}]}]})
    monkeypatch.setattr(job_context, "TRANSPORT_OVERRIDE", httpx.MockTransport(handler))
    ...  # Quelle anlegen, dann:
    result = run_job_inline("source_crawl", source_id=source_id)
    assert result["events_found"] == 1
```

Einen einzelnen Künstler kann man auch auf der Kommandozeile synchron crawlen:

```bash
tourdesk crawl --artist "Beispielband"
```

## Crawler-Einstellungen

Zentral im Admin-Bereich unter **Crawler-Einstellungen** (gespeichert in der Datenbank):
Intervall, User-Agent und Kontaktadresse, robots.txt, Mindestabstand je Domain, Timeout,
Wiederholungen, maximale Antwortgröße, HTTP-Cache, Seiten je Quelle, Worker-Threads, Backoff,
Geocoder, Bildquellen, Ticketmaster-Länder, Aufbewahrung der Läufe, Provider ein/aus und
API-Schlüssel. Werte aus der `.env` dienen als Standard.
