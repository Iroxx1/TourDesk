# TourDesk – Technische Architektur

Dieses Dokument beschreibt die Architektur von TourDesk (Phase 1). Es ist bewusst kompakt
gehalten. Details zu Betrieb und Installation stehen in der [README](../README.md).

---

## 1. Überblick

```text
                 Browser (Desktop / Smartphone)
                              │  HTTPS (Cloudflare Tunnel) oder HTTP (LAN)
                              ▼
┌────────────────────────── LXC-Container (Proxmox) ──────────────────────────┐
│                                                                             │
│   ┌──────────────────────┐        ┌──────────────────────┐                  │
│   │  app  (FastAPI)      │        │  scheduler           │                  │
│   │  • REST-API /api/*   │        │  • plant Crawl-Jobs  │                  │
│   │  • liefert Frontend  │        │  • Wartung, Heartbeat│                  │
│   │  • /media (Bilder)   │        └──────────┬───────────┘                  │
│   └──────────┬───────────┘                   │ INSERT crawler_jobs          │
│              │ SQL                           ▼                              │
│              │                 ┌──────────────────────────────┐             │
│              └───────────────► │  PostgreSQL 16               │ ◄───┐       │
│                                │  Daten + Job-Queue           │     │ SQL   │
│                                └──────────────────────────────┘     │       │
│                                                         ┌───────────┴─────┐ │
│                                                         │ worker (Crawler)│ │
│                                                         │ • Provider      │─┼──► Internet
│                                                         │ • Normalizer    │ │   (Künstler-,
│                                                         │ • Deduplicator  │ │    Venue-,
│                                                         └─────────────────┘ │    Ticketseiten)
└─────────────────────────────────────────────────────────────────────────────┘
```

* **Web/API, Worker und Scheduler sind getrennte Prozesse.** Sie kommunizieren ausschließlich
  über die Datenbank. Ein hängender oder abstürzender Crawler kann die Weboberfläche nicht
  blockieren.
* Die Job-Queue liegt in PostgreSQL (`SELECT … FOR UPDATE SKIP LOCKED`). Dadurch braucht es
  **kein Redis/RabbitMQ** – weniger Komponenten im LXC, Jobs sind transaktional und
  überleben Neustarts.
* Das Backend liefert das gebaute Frontend selbst aus. Es gibt genau **einen HTTP-Port**
  (Standard `8080`), auf den später der Cloudflare Tunnel zeigt.

## 2. Tech-Stack

| Bereich        | Technologie                                                                  |
|----------------|------------------------------------------------------------------------------|
| Frontend       | React 19, TypeScript, Vite, TanStack Query, Zustand, lucide-Icons, eigenes CSS-Designsystem (Fluent/Windows 11-inspiriert, kein UI-Framework) |
| Backend/API    | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (psycopg 3), Alembic           |
| Auth           | Serverseitige Sessions (HttpOnly-Cookie), Argon2id (argon2-cffi), CSRF-Token   |
| Crawler        | Python, httpx, BeautifulSoup4 + lxml, rapidfuzz, icalendar, Pillow; Playwright optional |
| Scheduler      | eigener, schlanker Python-Prozess (DB-basiert)                                 |
| Datenbank      | PostgreSQL 16 (Erweiterung `pg_trgm` für die Suche)                            |
| Deployment     | Docker Compose im LXC (empfohlen) **oder** nativ mit systemd                   |
| Tests          | pytest (gegen echtes PostgreSQL), respx, Vitest, Playwright                    |

### Begründete Abweichungen / Entscheidungen

1. **Sessions statt JWT** – Sessions sind sofort widerrufbar (Benutzer deaktivieren,
   Passwort-Reset, Rollenwechsel), das Token liegt in einem HttpOnly-Cookie und ist für
   JavaScript unerreichbar. Für eine Same-Origin-SPA ist das sicherer und einfacher als JWT.
2. **PostgreSQL als Job-Queue statt Redis/Celery** – siehe oben.
3. **Synchrones SQLAlchemy** – FastAPI führt synchrone Endpunkte im Threadpool aus, der Worker
   nutzt Threads. Das ist für die erwartete Last (wenige Benutzer, stündliche Crawls) mehr als
   ausreichend und deutlich einfacher zu warten und zu testen als ein durchgehend asynchroner Stack.
4. **Künstler als gemeinsamer Katalog** – `artists` existiert einmal pro Künstler, Benutzer
   abonnieren ihn über `user_artists` (mit eigenen Einstellungen: aktiv, Festival-Schalter,
   eigene Suchbegriffe). Folgen zwei Benutzer Metallica, wird Metallica nur einmal gecrawlt.
   Benutzer sehen niemals, wer sonst einem Künstler folgt.
5. **Eine gemeinsame Tabelle `sources`** für alle Crawl-Quellen (Künstler-, Venue-, Festival-,
   Veranstalter- und Ticketquellen). „artist_sources“ ist logisch `sources` mit
   `scope = 'artist'`. So gibt es genau einen Provider-Mechanismus und eine einheitliche
   Fehler-/Gesundheitsüberwachung.
6. **Kein nginx nötig** – FastAPI liefert die statischen Dateien mit korrekten Cache-Headern.
   Ein Reverse Proxy (Cloudflare Tunnel, nginx, Caddy, Traefik) kann davor geschaltet werden.
7. **Geodaten lokal** – Länder, Regionen und ca. 30.000 Städte (GeoNames, CC-BY 4.0) werden
   als Seed mitgeliefert. Unbekannte Orte werden optional per Nominatim (OpenStreetMap)
   nachgeschlagen und gecacht. Ohne Geocoder funktioniert alles weiter, nur ohne
   automatische Regionszuordnung neuer Orte.

## 3. Verzeichnisstruktur

```text
tourdesk/
├── backend/                 Python-Paket „tourdesk“ (Core, API, Services, CLI)
│   └── tourdesk/
│       ├── core/            Konfiguration, DB, Logging, Text-/Normalisierungshelfer
│       ├── models/          SQLAlchemy-Modelle
│       ├── schemas/         Pydantic-Schemas (API-Verträge)
│       ├── security/        Passwörter, Sessions, CSRF, Rate-Limits, Middleware
│       ├── services/        Filter-Engine, Tourstatus, Dashboard, Suche, Notifications …
│       ├── api/             FastAPI-Router (/api/…)
│       ├── seed/            Seed-Loader (Geodaten, Venues, Festivals)
│       ├── cli.py           Verwaltungsbefehle (migrate, seed, create-admin, …)
│       └── main.py          ASGI-App
├── crawler/                 Python-Paket „tourdesk_crawler“
│   └── tourdesk_crawler/
│       ├── http/            Höflicher HTTP-Client (robots.txt, Rate-Limit, Cache, SSRF-Schutz)
│       ├── extract/         JSON-LD, Microdata, eingebettetes JSON, iCal, Text-Heuristiken
│       ├── providers/       Provider/Adapter (ein Modul pro Quelle)
│       ├── pipeline/        Normalizer, ArtistMatcher, GeoResolver, Deduplicator, Merger
│       ├── images.py        Künstlerbild-Suche und lokaler Bild-Cache
│       ├── worker.py        Job-Worker
│       └── scheduler.py     Scheduler
├── frontend/                React/Vite-App (Windows-11-Desktop)
├── migrations/              Alembic-Migrationen
├── database/                Seed-Daten (Geo, Venues, Festivals)
├── docker/                  Dockerfile, Entrypoint
├── scripts/                 backup, restore, update, Hilfsskripte
├── tests/                   pytest-Suite (Unit, API, Crawler, E2E)
├── docs/                    Architektur, Provider-Entwicklung
├── .env.example
├── docker-compose.yml
├── install.sh
├── README.md
└── QUICKSTART.md
```

## 4. Datenbankmodell

```text
roles ──< users ──1 user_settings
            │ ├──< sessions
            │ ├──< user_artists >── artists ──< artist_aliases
            │ ├──1 user_filters (Filterprofil)        │ ├──< sources (scope=artist)
            │ │      ├──< user_countries >── countries │ ├──< tours
            │ │      ├──< user_regions   >── regions  │ └──< events
            │ │      ├──< user_cities    >── cities   │
            │ │      └──< user_venues    >── venues   │
            │ └──< notifications                       │
            └──< audit_logs                            │
countries ──< regions (hierarchisch, parent_id) ──< cities ──< venues
festivals (Serie, Ort, Website) ──< sources (scope=festival)
venues ──< sources (scope=venue)
events: artist, tour?, festival?, venue?, city?, region?, country?, Datum, Uhrzeit,
        Typ (concert|festival|support|special), Status (scheduled|cancelled|postponed|rescheduled),
        Ticketstatus, bestätigt, Konfidenz, gelistet, first/last_seen, last_checked
events ──< event_sources >── sources        (welche Quelle hat das Event wann gemeldet)
events ──< ticket_sources                   (Ticketangebote/Links je Anbieter)
crawler_jobs ──< crawler_runs ──< crawler_errors
app_settings (zentrale Crawler-Konfiguration), crawler_domains (Rate-Limit/robots je Domain),
http_cache (ETag/Last-Modified), geocode_cache, system_heartbeats
```

Wichtige Punkte:

* Fremdschlüssel überall mit sinnvollem `ON DELETE` (Benutzer löschen entfernt seine Abos,
  Filter, Sessions, Benachrichtigungen; Audit-Logs behalten einen Namens-Snapshot).
* Events speichern die aufgelöste Ortshierarchie denormalisiert
  (`venue_id`, `city_id`, `region_id`, `country_id`) → Filterabfragen sind einfache Index-Lookups.
* Normalisierte Namensspalten (`name_norm`) mit Trigram-Indizes für Suche und Matching.
* Indizes auf allen Fremdschlüsseln, `events(artist_id, event_date)`, `events(event_date)`,
  Job-Queue `(status, run_after, priority)`, Benachrichtigungen `(user_id, read_at)`.

## 5. API-Struktur (REST, JSON, Präfix `/api`)

| Bereich            | Endpunkte (Auszug)                                                              |
|--------------------|----------------------------------------------------------------------------------|
| `/auth`            | `GET setup-status`, `POST setup`, `POST login`, `POST logout`, `GET me`           |
| `/users`           | `GET/PATCH me`, `POST me/password`, `POST/DELETE me/avatar`                       |
| `/settings`        | `GET/PUT` (Design, Hintergrund, Dark Mode, Ansicht, Benachrichtigungen)           |
| `/artists`         | Liste/Anlegen/Bearbeiten/Entfernen, `events`, `sources`, `refresh`, `image`, `lookup` |
| `/countries` `/regions` `/cities` `/venues` | Geodaten & Veranstaltungsorte (lesen, anlegen)          |
| `/filters`         | Filterprofil (`GET/PUT`), Ortsregeln `locations` (`GET/POST/DELETE`)              |
| `/events` `/tours` `/festivals` | passende Termine (paginiert), Details, „Warum angezeigt?“          |
| `/dashboard`       | Kacheln für alle abonnierten Künstler                                             |
| `/search`          | globale Suche (Künstler, Events, Venues, Städte, Regionen)                        |
| `/notifications`   | Liste, gelesen markieren                                                          |
| `/crawler`         | Crawler-Status für eigene Künstler                                                |
| `/admin/*`         | Übersicht, Benutzer, Impersonation, Events, Crawler (Jobs/Runs/Fehler/Einstellungen), Quellen, System, Logs, Audit |

* Jeder Endpunkt erfordert eine gültige Session (außer Setup/Login/Health).
* Benutzerbezogene Abfragen filtern **immer** serverseitig nach `user_id` der Session –
  IDs anderer Benutzer führen zu `404`.
* `/admin/*` ist zusätzlich durch eine Rollenprüfung geschützt; jede schreibende Admin-Aktion
  wird im Audit-Log protokolliert.

## 6. Crawler-Architektur

```text
Scheduler ──(fällige Künstler/Quellen)──► crawler_jobs ◄──claim── Worker (N Threads)
                                                                     │
          ┌──────────────────────────────────────────────────────────┘
          ▼
   CrawlJob ──► ProviderRegistry ──► CrawlerProvider (Adapter)
                                      ├── ArtistWebsiteProvider   offizielle Website/Tourseite
                                      ├── VenueWebsiteProvider    Venue-Programm (alle Künstler)
                                      ├── FestivalProvider        Festival-Line-up
                                      ├── TicketProvider          Ticketmaster (API), Ticketseiten
                                      ├── BandsintownProvider / SongkickProvider (API-Key)
                                      ├── ICalProvider            iCal-Feeds
                                      ├── GenericWebProvider      beliebige URL
                                      └── DemoProvider            „Beispielband“
                    │ RawEvent[]
                    ▼
   EventNormalizer (Datum, Uhrzeit, Ort → GeoResolver, Typ, Status, Ticketstatus, Tour)
                    ▼
   ArtistMatcher (für Venue-/Festivalquellen: Line-up ↔ überwachte Künstler, Support-Erkennung)
                    ▼
   EventDeduplicator (Künstler + Datum + Venue/Stadt, Fuzzy-Matching) → EventMerger
     • Feldwerte der vertrauenswürdigsten Quelle gewinnen
     • „n Quellen bestätigen diesen Termin“
     • nicht mehr gelistete Termine → „nicht mehr gelistet“ (nie bei Quellenfehlern)
                    ▼
   Change-Events ──► NotificationService (In-App; Kanäle erweiterbar)
```

**Höflichkeit & Robustheit:** robots.txt (gecacht), Rate-Limit pro Domain über die DB
(funktioniert über Threads und Prozesse hinweg), max. eine Anfrage pro Domain gleichzeitig,
Timeouts, Retry mit exponentiellem Backoff (+ `Retry-After`), HTTP-Caching per
ETag/Last-Modified, Größenlimit, eindeutiger User-Agent, SSRF-Schutz (keine Anfragen an
private Netze). Fehlerhafte Quellen bekommen einen Backoff (`next_attempt_at`), werden aber nie
gelöscht. Die gesamte Konfiguration ist zentral im Adminbereich (`app_settings`) einstellbar.

**Vertrauensstufen:** 1 offizielle Künstlerseite · 2 offizieller Veranstaltungsort ·
3 Veranstalter/Festival · 4 offizieller Ticketanbieter · 5 Ticketbörse/Plattform · 6 Sonstige.
Ein Event gilt als **bestätigt**, wenn mindestens eine Quelle der Stufe 1–4 es meldet oder
zwei unabhängige Quellen. Festivalauftritte gelten nur mit Quelle der Stufe 1–4 als bestätigt –
Gerüchte werden nie als bestätigter Termin angezeigt.

## 7. Authentifizierung & Sicherheit

* Argon2id-Passwort-Hashes, Mindestlänge, Rehash bei geänderten Parametern.
* Session-Token (256 Bit) nur als SHA-256-Hash in der DB; Cookie `HttpOnly`, `SameSite=Lax`,
  `Secure` automatisch bei HTTPS (Cloudflare) bzw. `__Host-`-Präfix.
* CSRF: Double-Submit-Token (an Session gebunden) + Origin-Prüfung für schreibende Requests.
* Login-Rate-Limit pro IP und Konto-Sperre mit exponentiellem Backoff; generisches API-Rate-Limit.
* Security-Header (CSP, HSTS bei HTTPS, `X-Frame-Options`, `nosniff`, Referrer-/Permissions-Policy).
* Vertrauenswürdige Proxys konfigurierbar (`TRUSTED_PROXIES`), echte Client-IP über
  `CF-Connecting-IP`/`X-Forwarded-For`.
* Rollen `user` und `admin`; Admin-Impersonation ist **read-only**, deutlich gekennzeichnet und
  wird im Audit-Log protokolliert.
* Keine Secrets im Repository – `.env` wird beim Installieren mit Zufallswerten erzeugt.

## 8. Deployment-Architektur

```text
Proxmox VE ── LXC „tourdesk“ (Debian 12/13, unprivileged, nesting=1)
                 ├── Docker Compose: db · app(:8080) · worker · scheduler · [cloudflared]
                 └── oder nativ: postgresql · tourdesk-api · tourdesk-worker · tourdesk-scheduler (systemd)
LAN:     http://<LXC-IP>:8080
Extern:  https://tourdesk.meinedomain.de ──Cloudflare Tunnel──► http://localhost:8080
```

`./install.sh` installiert alle Pakete, erzeugt die Konfiguration, richtet die Datenbank ein,
führt Migrationen und Seeds aus, legt optional den Admin an und startet alle Dienste.

## 9. Frontend-Komponenten

```text
App
├── LoginScreen / SetupScreen (Ersteinrichtung) / PasswordChangeScreen
└── Desktop
    ├── Wallpaper
    ├── DesktopTiles ── ArtistTile (Bild, Tourstatus, passende Termine, aufklappbar: gesamte Tour)
    ├── WindowManager ── Window (verschieben, minimieren, maximieren, schließen, Fokus/Z-Order)
    │     └── Apps: ArtistApp, EventDetails, AgendaApp (Termine), ArtistsApp, FiltersApp,
    │               PlacesApp (Orte), VenuesApp, SettingsApp (Konto, Design, …), AdminApp
    ├── Taskbar (Startbutton = TourDesk-Logo, Suche, Künstler-Icons, offene Apps, Tray, Uhr)
    ├── StartMenu (angeheftete Apps, Empfohlen, Benutzer, Abmelden)
    ├── SearchFlyout, NotificationCenter, QuickSettings
    └── ImpersonationBanner
Mobile (< 768 px): gleiche Apps als Vollbild-Ansichten, große Karten, untere Navigationsleiste.
```

## 10. Filterlogik

Ein Benutzer hat ein Filterprofil mit **Ortsregeln** auf genau einer Ebene je Regel:

| Ebene    | Bedeutung                                    | Beispiel                          |
|----------|----------------------------------------------|-----------------------------------|
| Land     | das ganze Land                               | Deutschland komplett              |
| Region   | ganze Region inkl. aller Städte und Venues   | Saarland komplett                 |
| Stadt    | alle Venues dieser Stadt                     | Metz, Strasbourg                  |
| Venue    | nur dieser Veranstaltungsort                 | Rockhal, Luxexpo The Box          |

* Regeln werden mit **ODER** verknüpft – sie sind beliebig kombinierbar
  (Saarland + Rheinland-Pfalz komplett, in Luxemburg nur Rockhal und Luxexpo, in Frankreich nur
  Metz und Strasbourg …).
* Eine Regel wirkt **nur nach unten**: Region ⇒ alle Städte/Venues darin; Venue ⇒ nur dieses
  Venue (niemals automatisch die ganze Stadt oder das ganze Land).
* Keine Ortsregeln ⇒ keine Ortseinschränkung.
* Zusätzlich: Zeitraum, Event-Typen (Konzert, Support, Special), Festival-Modus
  (Künstler-Schalter · immer · nie), Festivals optional unabhängig vom Ort, abgesagte und
  unbestätigte Termine ein-/ausblenden.
* Der **Festival-Schalter je Künstler** entscheidet (im Modus „Künstler-Schalter“), ob bestätigte
  Festivalauftritte erscheinen.

Die Filter-Engine (`services/filter_engine.py`) ist eine reine Funktion und liefert neben
„passt/passt nicht“ eine **Begründung** (z. B. „✓ Saarland ist bevorzugte Region“,
„✗ Luxemburg ist nicht komplett ausgewählt – nur: Rockhal, Luxexpo The Box“). Für paginierte
Listen erzeugt dieselbe Regelmenge ein SQL-Prädikat; Tests stellen sicher, dass beide
Implementierungen identische Ergebnisse liefern.

**Tourstatus** wird über alle bekannten Termine (nicht nur die gefilterten) berechnet:
Termine werden zu Clustern (gleiche Tour oder Lücken ≤ 45 Tage) zusammengefasst.
Liegt heute in einem Cluster mit ≥ 2 Terminen → 🟢 *Aktuell auf Tour*; gibt es nur zukünftige
Cluster → 🔵 *Tour angekündigt*; sonst ⚪ *Derzeit nicht auf Tour*.

## 11. Erweiterbarkeit

* **Benachrichtigungen:** `NotificationService` erzeugt typisierte Benachrichtigungen;
  Kanäle implementieren ein `NotificationChannel`-Interface (In-App fertig; E-Mail, Telegram,
  Discord, Push, WhatsApp als weitere Kanäle).
* **Kalender:** Events besitzen stabile IDs und vollständige Zeit-/Ortsdaten → iCal-Export bzw.
  Google/Outlook-Sync als zusätzlicher Router.
* **Ticketpreise/-verfügbarkeit:** `ticket_sources` speichert Preis- und Statusfelder je Anbieter.
* **Mehrere Filterprofile:** Ortsregeln hängen bereits an `user_filters` (Profil-ID).
* **Neue Quellen:** neuer Provider = eine Klasse + Registrierung (siehe `docs/PROVIDERS.md`).
