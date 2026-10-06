"""Static application constants shared with the frontend via ``/api/settings/options``."""

from __future__ import annotations

WALLPAPERS: list[dict[str, str]] = [
    {"key": "bloom", "name": "Blaue Blüte", "theme": "dark", "description": "Modernes abstraktes Blau"},
    {"key": "nightfall", "name": "Neon-Horizont", "theme": "dark", "description": "Dunkles futuristisches Design"},
    {"key": "glass", "name": "Glas", "theme": "light", "description": "Minimalistisches Glasdesign"},
    {"key": "stage", "name": "Bühne", "theme": "dark", "description": "Konzertbühne mit Scheinwerfern"},
    {"key": "neon", "name": "Neonlichter", "theme": "dark", "description": "Abstrakte Neonlichter"},
    {"key": "alps", "name": "Bergsee", "theme": "dark", "description": "Landschaft in der Dämmerung"},
    {"key": "skyline", "name": "Stadt bei Nacht", "theme": "dark", "description": "Skyline bei Nacht"},
    {"key": "nebula", "name": "Weltraum", "theme": "dark", "description": "Nebel und Sterne"},
    {"key": "geometry", "name": "Dunkle Geometrie", "theme": "dark", "description": "Dunkle geometrische Formen"},
    {"key": "daylight", "name": "Tageslicht", "theme": "light", "description": "Helles, Windows-artiges abstraktes Design"},
    {"key": "aurora", "name": "Polarlicht", "theme": "dark", "description": "Nordlichter über dem Fjord"},
    {"key": "sunset", "name": "Sonnenuntergang", "theme": "light", "description": "Warme Wellen im Abendlicht"},
]
WALLPAPER_KEYS = {w["key"] for w in WALLPAPERS}

ACCENT_COLORS: list[dict[str, str]] = [
    {"key": "#0067c0", "name": "Blau"},
    {"key": "#0078d4", "name": "Himmelblau"},
    {"key": "#4f46e5", "name": "Indigo"},
    {"key": "#8b5cf6", "name": "Violett"},
    {"key": "#c239b3", "name": "Orchidee"},
    {"key": "#e3008c", "name": "Magenta"},
    {"key": "#e81123", "name": "Rot"},
    {"key": "#f7630c", "name": "Orange"},
    {"key": "#ca8a04", "name": "Gold"},
    {"key": "#10893e", "name": "Grün"},
    {"key": "#00897b", "name": "Petrol"},
    {"key": "#525e75", "name": "Schiefer"},
]

# Crawler providers known to the system (implemented in the crawler package).
PROVIDERS: dict[str, dict[str, object]] = {
    "official_website": {"label": "Offizielle Website", "scope": "artist", "trust": 1, "user_addable": False},
    "tour_page": {"label": "Tourseite", "scope": "artist", "trust": 1, "user_addable": True},
    "generic_web": {"label": "Webseite", "scope": "artist", "trust": 6, "user_addable": True},
    "ical_feed": {"label": "iCal-Feed", "scope": "any", "trust": 2, "user_addable": True},
    "ticketmaster": {"label": "Ticketmaster", "scope": "artist", "trust": 4, "user_addable": False},
    "bandsintown": {"label": "Bandsintown", "scope": "artist", "trust": 4, "user_addable": False},
    "songkick": {"label": "Songkick", "scope": "artist", "trust": 5, "user_addable": False},
    "venue_website": {"label": "Veranstaltungsort", "scope": "venue", "trust": 2, "user_addable": False},
    "festival_lineup": {"label": "Festival-Line-up", "scope": "festival", "trust": 3, "user_addable": False},
    "promoter_website": {"label": "Veranstalter", "scope": "global", "trust": 3, "user_addable": False},
    "ticket_listing": {"label": "Ticketseite", "scope": "global", "trust": 4, "user_addable": False},
    "demo": {"label": "Demo-Quelle", "scope": "artist", "trust": 1, "user_addable": False},
}


def provider_label(key: str) -> str:
    info = PROVIDERS.get(key)
    return str(info["label"]) if info else key
