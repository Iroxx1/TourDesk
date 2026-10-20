"""Kuratierte Genres des Künstlerkatalogs.

Jedes Genre hat einen deutschen Namen und die MusicBrainz-Schlagworte (Tags), über die seine
Künstler gesucht werden. Ein Künstler zählt nur dann zu einem Genre, wenn eines dieser
Schlagworte zu seinen wichtigsten gehört (siehe ``TOP_TAGS``) – sonst landen z. B. die Beatles
wegen eines einzelnen „heavy metal“-Tags im Metal-Katalog.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Genre:
    key: str
    label: str
    tags: tuple[str, ...]


GENRES: tuple[Genre, ...] = (
    Genre("rock", "Rock", ("rock", "hard rock", "classic rock")),
    Genre("pop", "Pop", ("pop", "pop rock", "dance-pop")),
    Genre("metal", "Metal", ("heavy metal", "metal", "thrash metal", "death metal", "black metal", "power metal")),
    Genre("hiphop", "Hip-Hop & Rap", ("hip hop", "rap", "german hip hop", "trap")),
    Genre("indie", "Indie", ("indie rock", "indie", "indie pop")),
    Genre("alternative", "Alternative", ("alternative rock", "alternative", "grunge", "post-grunge")),
    Genre("punk", "Punk", ("punk", "punk rock", "pop punk")),
    Genre("hardcore", "Hardcore & Metalcore", ("hardcore punk", "hardcore", "metalcore", "post-hardcore")),
    Genre("elektro", "Elektro & Dance", ("electronic", "techno", "house", "edm", "trance", "dance")),
    Genre("schlager", "Schlager", ("schlager",)),
    Genre("ndw", "Neue Deutsche Welle", ("neue deutsche welle",)),
    Genre("liedermacher", "Liedermacher", ("liedermacher",)),
    Genre("singer_songwriter", "Singer-Songwriter", ("singer-songwriter", "singer/songwriter")),
    Genre("soul", "R&B & Soul", ("soul", "r&b", "contemporary r&b", "funk")),
    Genre("jazz", "Jazz", ("jazz",)),
    Genre("klassik", "Klassik", ("classical",)),
    Genre("country", "Country", ("country",)),
    Genre("folk", "Folk", ("folk", "folk rock")),
    Genre("blues", "Blues", ("blues", "blues rock")),
    Genre("reggae", "Reggae & Ska", ("reggae", "ska")),
)

GENRES_BY_KEY: dict[str, Genre] = {g.key: g for g in GENRES}

# how many of an artist's most used tags are considered for the genre assignment
TOP_TAGS = 6
# MusicBrainz liefert pro Suche höchstens 500 Treffer (offset + limit <= 500). Pro Genre wird deshalb
# jedes Schlagwort einzeln abgefragt (die bekanntesten weltweit) plus eine Suche auf DE/AT/CH.
SEARCH_MAX = 500
DACH_COUNTRIES = ("DE", "AT", "CH")

ORIGINS = {"all": "Alle", "dach": "Deutschsprachig", "intl": "International"}


def genre_label(key: str) -> str:
    genre = GENRES_BY_KEY.get(key)
    return genre.label if genre else key


def tag_query(genre: Genre, tag: str | None = None) -> str:
    """Lucene query for MusicBrainz' artist search: one tag or all tags of the genre."""
    if tag is not None:
        return f'tag:"{tag}"'
    return "(" + " OR ".join(f'tag:"{t}"' for t in genre.tags) + ")"

