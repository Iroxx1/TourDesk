"""Creates the example configuration from the requirements (section 43).

User with artists Backstreet Boys (festivals ON), Metallica (OFF), Linkin Park (ON) and
the fictional "Beispielband" (demo tour data), regions: Saarland complete; Luxembourg
only Rockhal and Luxexpo The Box; France only Metz and Strasbourg.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tourdesk.core.text import normalize_name
from tourdesk.models import City, Country, Region, UserCity, UserRegion, UserVenue, Venue
from tourdesk.services.artists import create_catalog_artist, find_catalog_artist, follow_artist, schedule_initial_jobs
from tourdesk.services.filters import get_default_filter
from tourdesk.services.users import create_user, find_user_by_login, generate_temporary_password

EXAMPLE_ARTISTS = [
    ("Backstreet Boys", "https://www.backstreetboys.com", "Pop", True, ["BSB"]),
    ("Metallica", "https://www.metallica.com", "Metal", False, []),
    ("Linkin Park", "https://www.linkinpark.com", "Rock", True, []),
    ("Beispielband", None, "Indie-Rock", True, []),
]


def _city(db: Session, name: str, country_code: str) -> City | None:
    country = db.execute(select(Country).where(Country.code == country_code)).scalar_one()
    return db.execute(
        select(City).where(City.country_id == country.id, City.name_norm == normalize_name(name)).order_by(City.population.desc())
    ).unique().scalars().first()


def _venue(db: Session, name: str) -> Venue | None:
    return db.execute(select(Venue).where(Venue.name_norm == normalize_name(name))).unique().scalars().first()


def create_example_user(db: Session, *, username: str = "beispiel", email: str = "beispiel@tourdesk.local",
                        password: str | None = None) -> dict[str, Any]:
    user = find_user_by_login(db, username)
    generated = None
    if user is None:
        generated = password or generate_temporary_password()
        user = create_user(db, username=username, email=email, password=generated, role="user",
                           display_name="Beispielbenutzer", must_change_password=password is None)
    f = get_default_filter(db, user.id)
    artists = []
    for name, website, genre, festivals, aliases in EXAMPLE_ARTISTS:
        artist = find_catalog_artist(db, name)
        if artist is None:
            artist = create_catalog_artist(db, name=name, website=website, genre=genre, aliases=aliases, search_terms=[],
                                           musicbrainz_id=None, created_by=user)
            schedule_initial_jobs(db, artist, user.id)
        ua, _new = follow_artist(db, user, artist, show_festivals=festivals)
        ua.show_festivals = festivals
        artists.append({"name": artist.name, "festivals": festivals})

    saarland = db.execute(select(Region).where(Region.code == "DE-SL")).scalar_one()
    if not db.execute(select(UserRegion.id).where(UserRegion.filter_id == f.id, UserRegion.region_id == saarland.id)).first():
        db.add(UserRegion(user_id=user.id, filter_id=f.id, region_id=saarland.id))
    venues = []
    for venue_name in ("Rockhal", "Luxexpo The Box"):
        venue = _venue(db, venue_name)
        if venue and not db.execute(select(UserVenue.id).where(UserVenue.filter_id == f.id, UserVenue.venue_id == venue.id)).first():
            db.add(UserVenue(user_id=user.id, filter_id=f.id, venue_id=venue.id))
        venues.append(venue_name if venue else f"{venue_name} (nicht gefunden)")
    cities = []
    for city_name in ("Metz", "Strasbourg"):
        city = _city(db, city_name, "FR")
        if city and not db.execute(select(UserCity.id).where(UserCity.filter_id == f.id, UserCity.city_id == city.id)).first():
            db.add(UserCity(user_id=user.id, filter_id=f.id, city_id=city.id))
        cities.append(city_name if city else f"{city_name} (nicht gefunden)")
    db.flush()
    return {
        "username": user.username,
        "password": generated,
        "artists": artists,
        "regions": ["Saarland (komplett)"],
        "venues": venues,
        "cities": cities,
    }
