"""Artist names offered in the venue programme ("Hinzufügen")."""

from __future__ import annotations

import pytest

from tourdesk.services.programme import guess_artists, split_genre


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Testband – Live 2027", ["Testband"]),
        ("Testband - Die Jubiläumstour", ["Testband"]),
        ("Testband: Tour 2027", ["Testband"]),
        ("Band A + Band B", ["Band A", "Band B"]),
        ("Headliner feat. Gast", ["Headliner", "Gast"]),
        ("Headliner – Support: Vorband", ["Headliner", "Vorband"]),
        ("Mumford & Sons", ["Mumford & Sons"]),
        ("Simon und Garfunkel Revival (Tribute)", ["Simon und Garfunkel Revival"]),
        ("Rockhal presents: Neue Band", ["Neue Band"]),
        ("AUSVERKAUFT: Große Band", ["Große Band"]),
        ("Earth, Wind & Fire Experience", ["Earth, Wind & Fire Experience"]),
        ("AC/DC Tribute Night 2027", ["AC/DC Tribute Night"]),
        ("", []),
    ],
)
def test_guess_from_title(title: str, expected: list[str]) -> None:
    assert guess_artists(title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # so stehen die Termine auf rockhal.lu
        ("URIAH HEEP Rock", ("URIAH HEEP", "Rock")),
        ("TIMMY TRUMPET Electro/Clubbing", ("TIMMY TRUMPET", "Electro/Clubbing")),
        ("VÉRONIQUE SANSON French Pop", ("VÉRONIQUE SANSON", "French Pop")),
        ("GUY2BEZBAR Hip-Hop/Rap", ("GUY2BEZBAR", "Hip-Hop/Rap")),
        ("JAY PARK with special guests LNGSHOT Pop", ("JAY PARK with special guests LNGSHOT", "Pop")),
        # echte Namen bleiben
        ("Kid Rock", ("Kid Rock", None)),
        ("Iggy Pop", ("Iggy Pop", None)),
        ("KID ROCK", ("KID ROCK", None)),
        ("STING", ("STING", None)),
    ],
)
def test_split_genre(title: str, expected: tuple) -> None:
    assert split_genre(title) == expected


def test_rockhal_titles() -> None:
    title, _genre = split_genre("JAY PARK with special guests LNGSHOT Pop")
    assert guess_artists(title) == ["JAY PARK", "LNGSHOT"]
    title, _genre = split_genre("SUPERDRIVE + PILOT LIGHT Alternative")
    assert guess_artists(title) == ["SUPERDRIVE", "PILOT LIGHT"]


def test_performers_win_over_title() -> None:
    assert guess_artists("Irgendein Titel – Tour", ["Band A", "band a", "Band B"]) == ["Band A", "Band B"]


def test_at_most_six_names() -> None:
    assert len(guess_artists(" + ".join(f"Band {i}" for i in range(10)))) == 6
