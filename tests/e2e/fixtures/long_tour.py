"""E2E fixture: lets a user follow a fictional artist with a long tour (34 dates by default).

Called by ``layout.spec.ts`` with the environment of ``scripts/run-e2e.sh`` (database URL,
data directory). The dates are stored by a regular crawl of the artist's website, which is
served from memory – no network access.

    python tests/e2e/fixtures/long_tour.py --user maria --artist "Die Tourneeband" --dates 34
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

import httpx

import tourdesk_crawler.jobs.context as job_context
from tourdesk.core.db import session_scope
from tourdesk.services.artists import create_catalog_artist, find_catalog_artist, follow_artist
from tourdesk.services.users import find_user_by_login
from tourdesk_crawler.http.client import PoliteHttpClient
from tourdesk_crawler.jobs.runner import run_job_inline

WEBSITE = "https://tourneeband.e2e.test"

# venue, city, country, kind – the Saarland dates and the Rockhal match the E2E user's filters
STOPS = [
    ("Saarlandhalle", "Saarbrücken", "DE", ""),
    ("Rockhal", "Esch-sur-Alzette", "LU", ""),
    ("LANXESS arena", "Köln", "DE", ""),
    ("Barclays Arena", "Hamburg", "DE", ""),
    ("Max-Schmeling-Halle", "Berlin", "DE", ""),
    ("Olympiahalle", "München", "DE", ""),
    ("Festhalle", "Frankfurt am Main", "DE", ""),
    ("Mehrzweckhalle am Stadtpark – Großer Saal mit Empore und Foyer", "Sankt Wendel", "DE", ""),
    ("Porsche-Arena", "Stuttgart", "DE", ""),
    ("Messe Dresden", "Dresden", "DE", ""),
    ("ZAG Arena", "Hannover", "DE", ""),
    ("Rocco del Schlacko", "Püttlingen", "DE", "festival"),
    ("ÖVB-Arena", "Bremen", "DE", ""),
    ("Westfalenhalle", "Dortmund", "DE", ""),
    ("Mitsubishi Electric HALLE", "Düsseldorf", "DE", ""),
    ("Seidensticker Halle", "Bielefeld", "DE", "cancelled"),
    ("SAP Arena", "Mannheim", "DE", ""),
    ("Arena Trier", "Trier", "DE", ""),
    ("Wiener Stadthalle", "Wien", "AT", ""),
    ("Stadthalle Graz", "Graz", "AT", ""),
    ("Hallenstadion", "Zürich", "CH", ""),
    ("St. Jakobshalle", "Basel", "CH", ""),
    ("den Atelier", "Luxembourg", "LU", ""),
    ("Neue Gebläsehalle", "Neunkirchen", "DE", ""),
    ("Messehalle", "Erfurt", "DE", ""),
    ("GETEC Arena", "Magdeburg", "DE", ""),
    ("Stadthalle Rostock", "Rostock", "DE", ""),
    ("Das Fest", "Karlsruhe", "DE", "festival"),
    ("Wunderino Arena", "Kiel", "DE", ""),
    ("Halle Münsterland", "Münster", "DE", ""),
    ("Sick-Arena", "Freiburg im Breisgau", "DE", ""),
    ("KIA Metropol Arena", "Nürnberg", "DE", ""),
    ("Fruchthalle", "Kaiserslautern", "DE", ""),
    ("E-Werk", "Saarbrücken", "DE", ""),
]


def tour_page(artist: str, dates: int) -> str:
    start = date.today() + timedelta(days=14)
    graph = []
    for i in range(dates):
        venue, city, country, kind = STOPS[i % len(STOPS)]
        item = {
            "@type": "Festival" if kind == "festival" else "MusicEvent",
            "name": venue if kind == "festival" else f"{artist} – Live {start.year}",
            "startDate": (start + timedelta(days=7 * i)).isoformat() + "T20:00:00",
            "location": {"@type": "Place", "name": venue, "address": {"addressLocality": city, "addressCountry": country}},
            "performer": [{"@type": "MusicGroup", "name": artist}],
        }
        if kind == "cancelled":
            item["eventStatus"] = "https://schema.org/EventCancelled"
        graph.append(item)
    return f'<html><head><script type="application/ld+json">{json.dumps({"@graph": graph})}</script></head></html>'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user", required=True)
    parser.add_argument("--artist", default="Die Tourneeband")
    parser.add_argument("--dates", type=int, default=34)
    args = parser.parse_args()

    with session_scope() as db:
        user = find_user_by_login(db, args.user)
        if user is None:
            print(f"Benutzer {args.user} existiert nicht", file=sys.stderr)
            return 1
        # idempotent: Playwright repeats beforeAll in a new worker after a failed test
        artist = find_catalog_artist(db, args.artist) or create_catalog_artist(
            db, name=args.artist, website=WEBSITE, genre="Pop", aliases=[], search_terms=[], musicbrainz_id=None, created_by=user)
        follow_artist(db, user, artist, show_festivals=True)
        db.commit()
        artist_id = artist.id

    page = tour_page(args.artist, args.dates)

    def website(request: httpx.Request) -> httpx.Response:
        if request.url.host == "tourneeband.e2e.test" and request.url.path == "/":
            return httpx.Response(200, text=page, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404)

    job_context.TRANSPORT_OVERRIDE = httpx.MockTransport(website)
    PoliteHttpClient._wait_for_slot = lambda self, domain, interval: None  # type: ignore[method-assign]
    result = run_job_inline("artist_crawl", artist_id=artist_id)
    print(json.dumps({"artist_id": artist_id, **{k: result.get(k) for k in ("status", "events_found", "events_new", "error")}}))
    return 0 if result.get("events_found") == args.dates else 1


if __name__ == "__main__":
    sys.exit(main())
