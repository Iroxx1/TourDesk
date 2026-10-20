"""E2E fixture: fills the Künstlerkatalog with fictional and well-known entries – no network access.

Called by ``catalog.spec.ts`` with the environment of ``scripts/run-e2e.sh``. Every genre counts as
imported, the details of each entry (website, Wikipedia text) are already stored and pictures are
marked as missing, so neither MusicBrainz, Wikipedia nor Deezer are asked.

    python tests/e2e/fixtures/catalog.py
"""

from __future__ import annotations

import string
import uuid

from sqlalchemy import delete

from tourdesk.core.db import session_scope
from tourdesk.core.timeutil import utcnow
from tourdesk.models import CatalogEntry, CatalogGenre
from tourdesk.services.catalog import letter_of, sort_key_of
from tourdesk.services.catalog_genres import GENRES

# name, sort name, kind, country, begin, genres, description
KNOWN = [
    ("10cc", "10cc", "Group", "GB", 1972, ["rock", "pop"], None),
    ("ABBA", "ABBA", "Group", "SE", 1972, ["pop"], "ABBA ist eine schwedische Popgruppe."),
    ("Die Ärzte", "Ärzte, Die", "Group", "DE", 1982, ["punk", "rock"], "Die Ärzte sind eine Berliner Rockband."),
    ("Beatsteaks", "Beatsteaks", "Group", "DE", 1995, ["rock", "punk"], None),
    ("Helene Fischer", "Fischer, Helene", "Person", "DE", 1984, ["schlager", "pop"], "Helene Fischer ist eine deutsche Sängerin."),
    ("Kraftklub", "Kraftklub", "Group", "DE", 2008, ["rock", "indie"], "Kraftklub ist eine deutsche Band aus Chemnitz."),
    ("Roland Kaiser", "Kaiser, Roland", "Person", "DE", 1952, ["schlager"], None),
    ("The Kinks", "Kinks, The", "Group", "GB", 1963, ["rock"], "The Kinks waren eine britische Rockband."),
    ("Metallica", "Metallica", "Group", "US", 1981, ["metal", "rock"], None),
    ("Udo Lindenberg", "Lindenberg, Udo", "Person", "DE", 1946, ["rock"], None),
    ("Wanda", "Wanda", "Group", "AT", 2012, ["indie", "rock"], None),
    ("Züri West", "Züri West", "Group", "CH", 1984, ["rock"], None),
]


def mbid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "tourdesk-e2e-catalog/" + name))


def main() -> None:
    now = utcnow()
    rows = list(KNOWN)
    # zwei erfundene Bands je Buchstabe, damit es mehrere Doppelseiten gibt
    for i, letter in enumerate(string.ascii_uppercase):
        for n in (1, 2):
            country = ("DE", "US", "FR", "AT")[(i + n) % 4]
            rows.append((f"{letter}-Testband {n}", f"{letter}-Testband {n}", "Group", country, 1990 + i, ["rock"], None))
    with session_scope() as db:
        db.execute(delete(CatalogEntry))
        db.execute(delete(CatalogGenre))
        for name, sort_name, kind, country, begin, genres, description in rows:
            letter = letter_of(sort_name)
            website = f"https://{name.lower().replace(' ', '-').replace('ä', 'ae').replace('ü', 'ue')}.e2e.test/"
            db.add(CatalogEntry(
                mbid=mbid(name), name=name, sort_name=sort_name, sort_key=sort_key_of(sort_name, letter), letter=letter,
                kind=kind, country=country, is_dach=country in ("DE", "AT", "CH"), begin_year=begin, ended=False,
                genres=genres, genre_ranks={g: 1 for g in genres}, tags=list(genres),
                image_status="missing", image_checked_at=now,
                details={"website": website, "wikidata": None, "description": description, "description_lang": "de" if description else None,
                         "wikipedia_url": "https://de.wikipedia.org/wiki/" + name.replace(" ", "_") if description else None},
                details_fetched_at=now, seen_at=now,
            ))
        for genre in GENRES:
            count = sum(1 for r in rows if genre.key in r[5])
            db.add(CatalogGenre(key=genre.key, status="ok", entry_count=count, imported_at=now, last_attempt_at=now))
    print(f"Katalog-Fixture: {len(rows)} Einträge")


if __name__ == "__main__":
    main()
