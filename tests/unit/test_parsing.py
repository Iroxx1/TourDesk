"""Dates, times, text normalisation, matcher and tour-name extraction."""

from __future__ import annotations

from datetime import date, time

import pytest

from tourdesk.core.text import is_http_url, normalize_name, normalize_variants, safe_url
from tourdesk_crawler.extract.dates import find_dates, find_times, parse_iso_datetime
from tourdesk_crawler.pipeline.matcher import ArtistMatcher
from tourdesk_crawler.pipeline.models import ArtistSpec, RawEvent
from tourdesk_crawler.pipeline.normalizer import extract_tour_name

TODAY = date(2026, 10, 6)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12.03.2027", date(2027, 3, 12)),
        ("Do, 12. März 2027", date(2027, 3, 12)),
        ("March 12, 2027", date(2027, 3, 12)),
        ("12 mars 2027", date(2027, 3, 12)),
        ("12 maart 2027", date(2027, 3, 12)),
        ("Sat 15th Mar 2027", date(2027, 3, 15)),
        ("2027-03-12T20:00:00+01:00", date(2027, 3, 12)),
        ("1er juin 2027", date(2027, 6, 1)),
        ("03/25/2027", date(2027, 3, 25)),
        ("12. Januar", date(2027, 1, 12)),  # year inferred (next occurrence)
        ("20.10.", date(2026, 10, 20)),
    ],
)
def test_find_dates(text: str, expected: date) -> None:
    matches = find_dates(text, today=TODAY)
    assert matches and matches[0].start == expected


def test_date_ranges() -> None:
    m = find_dates("12.–14. Juni 2027", today=TODAY)[0]
    assert (m.start, m.end) == (date(2027, 6, 12), date(2027, 6, 14))
    m = find_dates("June 5-7, 2027", today=TODAY)[0]
    assert (m.start, m.end) == (date(2027, 6, 5), date(2027, 6, 7))


def test_times() -> None:
    assert find_times("Einlass: 19:00 Uhr, Beginn: 20:00 Uhr") == (time(20, 0), time(19, 0))
    assert find_times("Doors 7pm / Show 8:30 PM") == (time(20, 30), time(19, 0))
    assert find_times("Beginn 20 Uhr")[0] == time(20, 0)
    assert find_times("Tickets ab 49,90 €") == (None, None)


def test_iso_datetime() -> None:
    d, t, tz = parse_iso_datetime("2027-03-12T20:00:00+01:00")
    assert d == date(2027, 3, 12) and t == time(20, 0) and tz is not None
    assert parse_iso_datetime("2027-03-12") == (date(2027, 3, 12), None, None)


def test_normalize_names() -> None:
    assert normalize_name("Sankt Ingbert") == normalize_name("St. Ingbert") == "st ingbert"
    assert normalize_name("Saarbrücken") == "saarbrucken"
    assert "saarbruecken" in normalize_variants("Saarbrücken")
    assert "rolling stones" in normalize_variants("The Rolling Stones")
    assert normalize_name("Simon & Garfunkel") == normalize_name("Simon and Garfunkel")


def test_url_safety() -> None:
    assert safe_url("javascript:alert(1)") is None
    assert safe_url("https://example.org/a") == "https://example.org/a"
    assert not is_http_url("https://exa mple.org")
    assert not is_http_url("ftp://example.org")


MATCHER = ArtistMatcher([
    ArtistSpec(1, "Metallica"), ArtistSpec(2, "Linkin Park"), ArtistSpec(3, "Backstreet Boys", aliases=("BSB",)),
    ArtistSpec(4, "Kiss"), ArtistSpec(5, "Yes"),
])


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Metallica – M72 World Tour", {(1, "headliner")}),
        ("Ghost + special guest Metallica", {(1, "support")}),
        ("The Backstreet Boys", {(3, "headliner")}),
        ("KISS - End of the Road", {(4, "headliner")}),
        ("Kiss me once", set()),
        ("Say yes to the party", set()),
        ("Linkin Park Tribute Show", set()),
        ("Metallica Night im Rockclub", set()),
    ],
)
def test_matcher(title: str, expected: set) -> None:
    assert {(m.artist_id, m.role) for m in MATCHER.match(RawEvent(title=title))} == expected


def test_matcher_performers() -> None:
    res = MATCHER.match(RawEvent(performers=["Iron Maiden", "Linkin Park"]))
    assert [(m.artist_id, m.role) for m in res] == [(2, "support")]


def test_tour_name_extraction() -> None:
    artist = ArtistSpec(1, "Metallica")
    assert extract_tour_name("Metallica: M72 World Tour", artist) == "M72 World Tour"
    assert extract_tour_name("Metallica – Live", artist) is None
    assert extract_tour_name("Tour", artist) is None
    bsb = ArtistSpec(2, "Backstreet Boys")
    assert extract_tour_name("Backstreet Boys - DNA World Tour 2027", bsb) == "DNA World Tour 2027"
