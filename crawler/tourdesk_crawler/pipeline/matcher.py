"""Match performer names / event titles against monitored artists.

Used for venue agendas, festival line-ups and generic pages that list events of
many artists. Matching is conservative to avoid false positives:

* exact (normalised) performer names or aliases always match
* titles match on whole-word sequences; very short or generic names only match
  at the start of a title or as an exact title
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tourdesk.core.text import normalize_name, normalize_variants
from tourdesk_crawler.pipeline.models import ArtistSpec, RawEvent

GENERIC_NAMES = {
    "live", "band", "home", "time", "yes", "air", "love", "beach", "fire", "sun", "light", "music", "sound", "the band",
    "future", "crowd", "night", "party", "festival", "tour", "special", "guest", "guests", "support", "dj", "duo", "trio",
}
SUPPORT_MARKERS = ("support", "special guest", "special guests", "supported by", "mit", "with", "w", "plus", "and guests",
                   "vorband", "opening", "en premiere partie", "voorprogramma", "featuring", "feat", "ft")
# titles of tribute/cover/party events must not count as appearances of the artist
NOT_THE_ARTIST = re.compile(
    r"\b(tribute|cover|coverband|covers|plays|performs|performing|salute|revival|experience|hommage|tributo|"
    r"musical|karaoke|party|night|nacht|abend|soirée|soiree|klassik|symphonic|in concert by|songs of|the music of|"
    r"lookalike|double|show band|showband)\b",
    re.I,
)
ARTICLES = {"the", "die", "der", "das", "le", "la", "les", "de", "het", "il", "el"}
_SPLIT_PERFORMERS = re.compile(r"\s(?:\+|&|/|,|und|and|with|w/|mit|feat\.?|ft\.?|x)\s", re.I)


@dataclass(frozen=True)
class MatchResult:
    artist_id: int
    role: str  # headliner | support | unknown
    via: str  # performer | title


class ArtistMatcher:
    def __init__(self, artists: list[ArtistSpec]) -> None:
        self.artists = {a.id: a for a in artists}
        self._index: dict[str, set[int]] = {}
        self._short: set[str] = set()
        for artist in artists:
            for name in (*artist.all_names, *artist.search_terms):
                for v in normalize_variants(name):
                    if not v:
                        continue
                    self._index.setdefault(v, set()).add(artist.id)
                    if len(v) <= 3 or v in GENERIC_NAMES or (" " not in v and len(v) <= 5):
                        self._short.add(v)
        self._max_tokens = max((len(k.split()) for k in self._index), default=1)

    def __len__(self) -> int:
        return len(self.artists)

    def match_name(self, name: str) -> set[int]:
        out: set[int] = set()
        for v in normalize_variants(name):
            out |= self._index.get(v, set())
        return out

    def _title_matches(self, title: str) -> list[tuple[int, int, str]]:
        """(artist_id, token position, matched key) for whole-word occurrences in ``title``."""
        tokens = normalize_name(title).split()
        found: list[tuple[int, int, str]] = []
        for i in range(len(tokens)):
            for n in range(min(self._max_tokens, len(tokens) - i), 0, -1):
                key = " ".join(tokens[i : i + n])
                ids = self._index.get(key)
                if not ids:
                    continue
                if key in self._short:
                    # generic/short names: only exact title or at title start before a delimiter
                    if not (i == 0 and (n == len(tokens) or _delimited(title, key))):
                        continue
                for artist_id in ids:
                    found.append((artist_id, i, key))
                break
        return found

    def match(self, ev: RawEvent) -> list[MatchResult]:
        results: dict[int, MatchResult] = {}
        for idx, performer in enumerate(ev.performers):
            for artist_id in self.match_name(performer):
                role = "headliner" if idx == 0 else "support"
                if ev.role == "festival":
                    role = "festival"
                results.setdefault(artist_id, MatchResult(artist_id, role, "performer"))
            # "Artist A + Artist B" packed into one performer string
            if not results and _SPLIT_PERFORMERS.search(performer):
                for j, part in enumerate(_SPLIT_PERFORMERS.split(performer)):
                    for artist_id in self.match_name(part):
                        results.setdefault(artist_id, MatchResult(artist_id, "headliner" if idx == 0 and j == 0 else "support", "performer"))
        if results:
            return list(results.values())
        for text in (ev.title, ev.description if not ev.title else None):
            if not text or NOT_THE_ARTIST.search(text):
                continue
            for artist_id, pos, _key in self._title_matches(text):
                prefix_tokens = normalize_name(text).split()[:pos]
                prefix = " ".join(prefix_tokens)
                if pos == 0 or all(t in ARTICLES for t in prefix_tokens):
                    role = "headliner"
                else:
                    role = "support" if _ends_with_marker(prefix) else "unknown"
                results.setdefault(artist_id, MatchResult(artist_id, role, "title"))
            if results:
                break
        return list(results.values())


def _delimited(title: str, key: str) -> bool:
    norm_title = normalize_name(title)
    if not norm_title.startswith(key):
        return False
    rest = title.strip()
    # find delimiter after the artist name in the original title
    m = re.match(r"^[^:\-–|(]+?\s*([:\-–|(]|$)", rest)
    return bool(m and normalize_name(m.group(0).rstrip(":-–|( ")) == key)


def _ends_with_marker(prefix: str) -> bool:
    tokens = prefix.split()
    for marker in SUPPORT_MARKERS:
        m = marker.split()
        if len(tokens) >= len(m) and tokens[-len(m):] == m:
            return True
    return False
