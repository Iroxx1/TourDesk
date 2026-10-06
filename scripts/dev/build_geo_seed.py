#!/usr/bin/env python3
"""Build the geographic seed data shipped in ``database/seed/geo``.

This is a *developer* tool. It is not needed at runtime. It reads the GeoNames
extracts bundled in the ``geonamescache`` package (CC-BY 4.0, GeoNames.org) and
country/subdivision names from ``pycountry`` and writes:

* ``countries.json``   – all ISO countries with German/English names and aliases
* ``regions.json``     – first-level regions (Bundesländer, Kantone, Regionen …)
* ``cities.jsonl.gz``  – cities with region, coordinates, population, timezone, aliases

Usage::

    pip install geonamescache pycountry
    python scripts/dev/build_geo_seed.py
"""

from __future__ import annotations

import gettext
import gzip
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import geonamescache
import pycountry

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "database" / "seed" / "geo"
DATA = Path(os.path.dirname(geonamescache.__file__)) / "data"

# --------------------------------------------------------------------------------------
# Country tiers
# --------------------------------------------------------------------------------------
# Tier 1: full coverage (population >= 1000, selected areas >= 500)
TIER1 = ["DE", "LU", "FR", "BE", "NL", "AT", "CH"]
# Tier 1 areas with population >= 500 (home area of the primary user: Saarland, RLP,
# Luxembourg, Grand Est, Wallonia)
TIER1_DETAIL = {("LU", None), ("DE", "08"), ("DE", "09"), ("FR", "44"), ("BE", "WAL")}
# Tier 2: population >= 15000
TIER2 = [
    "GB", "IE", "IT", "ES", "PT", "DK", "SE", "NO", "FI", "PL", "CZ", "HU", "SK",
    "SI", "HR", "GR", "US", "CA", "AU",
]
# Everything else: population >= 100000
REST_MIN_POP = 100_000

# Sorting priority for country pickers (lower = earlier)
COUNTRY_PRIORITY = {
    "DE": 1, "LU": 2, "FR": 3, "BE": 4, "NL": 5, "AT": 6, "CH": 7, "GB": 10, "IT": 11,
    "ES": 12, "PL": 13, "CZ": 14, "DK": 15, "US": 20,
}

COUNTRY_NAME_DE_OVERRIDES = {
    "GB": "Vereinigtes Königreich", "US": "USA", "KR": "Südkorea", "KP": "Nordkorea",
    "RU": "Russland", "IR": "Iran", "SY": "Syrien", "TW": "Taiwan", "VN": "Vietnam",
    "BO": "Bolivien", "VE": "Venezuela", "TZ": "Tansania", "MD": "Moldau", "LA": "Laos",
    "CZ": "Tschechien", "MK": "Nordmazedonien", "PS": "Palästina", "VA": "Vatikanstadt",
    "FM": "Mikronesien", "BN": "Brunei", "CD": "Demokratische Republik Kongo",
    "CG": "Republik Kongo", "CI": "Elfenbeinküste",
}
COUNTRY_NAME_EN_OVERRIDES = {
    "GB": "United Kingdom", "US": "United States", "KR": "South Korea", "KP": "North Korea",
    "RU": "Russia", "IR": "Iran", "SY": "Syria", "TW": "Taiwan", "VN": "Vietnam",
    "BO": "Bolivia", "VE": "Venezuela", "TZ": "Tanzania", "MD": "Moldova", "LA": "Laos",
    "CZ": "Czechia", "MK": "North Macedonia", "PS": "Palestine", "VA": "Vatican City",
    "FM": "Micronesia", "BN": "Brunei",
}
# Additional names used on concert/ticket websites
COUNTRY_EXTRA_ALIASES = {
    "DE": ["Deutschland", "Germany", "Allemagne", "Duitsland", "Germania", "Alemania", "Däitschland", "BRD"],
    "LU": ["Luxembourg", "Luxemburg", "Lëtzebuerg", "Letzebuerg", "Großherzogtum Luxemburg", "Lussemburgo"],
    "FR": ["France", "Frankreich", "Frankrijk", "Francia", "Frankräich"],
    "BE": ["Belgium", "Belgien", "Belgique", "België", "Belgie", "Belgio", "Bélgica"],
    "NL": ["Netherlands", "The Netherlands", "Niederlande", "Nederland", "Holland", "Pays-Bas", "Paesi Bassi"],
    "AT": ["Austria", "Österreich", "Oesterreich", "Autriche", "Oostenrijk"],
    "CH": ["Switzerland", "Schweiz", "Suisse", "Svizzera", "Zwitserland", "Confoederatio Helvetica"],
    "GB": ["UK", "U.K.", "Great Britain", "Britain", "England", "Scotland", "Wales", "Northern Ireland",
           "Großbritannien", "Royaume-Uni", "Verenigd Koninkrijk", "United Kingdom"],
    "US": ["USA", "U.S.A.", "U.S.", "United States of America", "Vereinigte Staaten", "États-Unis", "America"],
    "IT": ["Italy", "Italien", "Italie", "Italia", "Italië"],
    "ES": ["Spain", "Spanien", "Espagne", "España", "Spanje"],
    "PT": ["Portugal"],
    "PL": ["Poland", "Polen", "Pologne", "Polska"],
    "CZ": ["Czech Republic", "Tschechische Republik", "Česko", "République tchèque"],
    "DK": ["Denmark", "Dänemark", "Danemark", "Danmark"],
    "SE": ["Sweden", "Schweden", "Suède", "Sverige"],
    "NO": ["Norway", "Norwegen", "Norvège", "Norge"],
    "FI": ["Finland", "Finnland", "Suomi"],
    "IE": ["Ireland", "Irland", "Irlande", "Éire"],
    "HU": ["Hungary", "Ungarn", "Hongrie", "Magyarország"],
    "GR": ["Greece", "Griechenland", "Grèce", "Hellas"],
    "CA": ["Canada", "Kanada"],
    "AU": ["Australia", "Australien"],
    "JP": ["Japan", "Japon"],
    "BR": ["Brazil", "Brasilien", "Brésil", "Brasil"],
    "MX": ["Mexico", "Mexiko", "Mexique", "México"],
}

# --------------------------------------------------------------------------------------
# Region mappings (GeoNames admin1 code -> ISO 3166-2 code, German name, local name, kind)
# --------------------------------------------------------------------------------------
REGIONS: dict[str, dict[str, tuple[str, str, str, str]]] = {
    "DE": {
        "01": ("DE-BW", "Baden-Württemberg", "Baden-Württemberg", "Bundesland"),
        "02": ("DE-BY", "Bayern", "Bayern", "Bundesland"),
        "03": ("DE-HB", "Bremen", "Bremen", "Bundesland"),
        "04": ("DE-HH", "Hamburg", "Hamburg", "Bundesland"),
        "05": ("DE-HE", "Hessen", "Hessen", "Bundesland"),
        "06": ("DE-NI", "Niedersachsen", "Niedersachsen", "Bundesland"),
        "07": ("DE-NW", "Nordrhein-Westfalen", "Nordrhein-Westfalen", "Bundesland"),
        "08": ("DE-RP", "Rheinland-Pfalz", "Rheinland-Pfalz", "Bundesland"),
        "09": ("DE-SL", "Saarland", "Saarland", "Bundesland"),
        "10": ("DE-SH", "Schleswig-Holstein", "Schleswig-Holstein", "Bundesland"),
        "11": ("DE-BB", "Brandenburg", "Brandenburg", "Bundesland"),
        "12": ("DE-MV", "Mecklenburg-Vorpommern", "Mecklenburg-Vorpommern", "Bundesland"),
        "13": ("DE-SN", "Sachsen", "Sachsen", "Bundesland"),
        "14": ("DE-ST", "Sachsen-Anhalt", "Sachsen-Anhalt", "Bundesland"),
        "15": ("DE-TH", "Thüringen", "Thüringen", "Bundesland"),
        "16": ("DE-BE", "Berlin", "Berlin", "Bundesland"),
    },
    "LU": {
        "CA": ("LU-CA", "Kanton Capellen", "Capellen", "Kanton"),
        "CL": ("LU-CL", "Kanton Clerf", "Clervaux", "Kanton"),
        "DI": ("LU-DI", "Kanton Diekirch", "Diekirch", "Kanton"),
        "EC": ("LU-EC", "Kanton Echternach", "Echternach", "Kanton"),
        "ES": ("LU-ES", "Kanton Esch an der Alzette", "Esch-sur-Alzette", "Kanton"),
        "GR": ("LU-GR", "Kanton Grevenmacher", "Grevenmacher", "Kanton"),
        "LU": ("LU-LU", "Kanton Luxemburg", "Luxembourg", "Kanton"),
        "ME": ("LU-ME", "Kanton Mersch", "Mersch", "Kanton"),
        "RD": ("LU-RD", "Kanton Redingen", "Redange", "Kanton"),
        "RM": ("LU-RM", "Kanton Remich", "Remich", "Kanton"),
        "VD": ("LU-VD", "Kanton Vianden", "Vianden", "Kanton"),
        "WI": ("LU-WI", "Kanton Wiltz", "Wiltz", "Kanton"),
    },
    "FR": {
        "11": ("FR-IDF", "Île-de-France", "Île-de-France", "Region"),
        "24": ("FR-CVL", "Centre-Val de Loire", "Centre-Val de Loire", "Region"),
        "27": ("FR-BFC", "Bourgogne-Franche-Comté", "Bourgogne-Franche-Comté", "Region"),
        "28": ("FR-NOR", "Normandie", "Normandie", "Region"),
        "32": ("FR-HDF", "Hauts-de-France", "Hauts-de-France", "Region"),
        "44": ("FR-GES", "Grand Est", "Grand Est", "Region"),
        "52": ("FR-PDL", "Pays de la Loire", "Pays de la Loire", "Region"),
        "53": ("FR-BRE", "Bretagne", "Bretagne", "Region"),
        "75": ("FR-NAQ", "Nouvelle-Aquitaine", "Nouvelle-Aquitaine", "Region"),
        "76": ("FR-OCC", "Okzitanien", "Occitanie", "Region"),
        "84": ("FR-ARA", "Auvergne-Rhône-Alpes", "Auvergne-Rhône-Alpes", "Region"),
        "93": ("FR-PAC", "Provence-Alpes-Côte d’Azur", "Provence-Alpes-Côte d'Azur", "Region"),
        "94": ("FR-20R", "Korsika", "Corse", "Region"),
    },
    "BE": {
        "BRU": ("BE-BRU", "Region Brüssel-Hauptstadt", "Région de Bruxelles-Capitale", "Region"),
        "VLG": ("BE-VLG", "Flandern", "Vlaanderen", "Region"),
        "WAL": ("BE-WAL", "Wallonien", "Wallonie", "Region"),
    },
    "NL": {
        "01": ("NL-DR", "Drenthe", "Drenthe", "Provinz"),
        "02": ("NL-FR", "Friesland", "Fryslân", "Provinz"),
        "03": ("NL-GE", "Gelderland", "Gelderland", "Provinz"),
        "04": ("NL-GR", "Groningen", "Groningen", "Provinz"),
        "05": ("NL-LI", "Limburg (NL)", "Limburg", "Provinz"),
        "06": ("NL-NB", "Nordbrabant", "Noord-Brabant", "Provinz"),
        "07": ("NL-NH", "Nordholland", "Noord-Holland", "Provinz"),
        "09": ("NL-UT", "Utrecht", "Utrecht", "Provinz"),
        "10": ("NL-ZE", "Zeeland", "Zeeland", "Provinz"),
        "11": ("NL-ZH", "Südholland", "Zuid-Holland", "Provinz"),
        "15": ("NL-OV", "Overijssel", "Overijssel", "Provinz"),
        "16": ("NL-FL", "Flevoland", "Flevoland", "Provinz"),
    },
    "AT": {
        "01": ("AT-1", "Burgenland", "Burgenland", "Bundesland"),
        "02": ("AT-2", "Kärnten", "Kärnten", "Bundesland"),
        "03": ("AT-3", "Niederösterreich", "Niederösterreich", "Bundesland"),
        "04": ("AT-4", "Oberösterreich", "Oberösterreich", "Bundesland"),
        "05": ("AT-5", "Salzburg", "Salzburg", "Bundesland"),
        "06": ("AT-6", "Steiermark", "Steiermark", "Bundesland"),
        "07": ("AT-7", "Tirol", "Tirol", "Bundesland"),
        "08": ("AT-8", "Vorarlberg", "Vorarlberg", "Bundesland"),
        "09": ("AT-9", "Wien", "Wien", "Bundesland"),
    },
    "CH": {
        "AG": ("CH-AG", "Aargau", "Aargau", "Kanton"),
        "AI": ("CH-AI", "Appenzell Innerrhoden", "Appenzell Innerrhoden", "Kanton"),
        "AR": ("CH-AR", "Appenzell Ausserrhoden", "Appenzell Ausserrhoden", "Kanton"),
        "BE": ("CH-BE", "Bern", "Bern", "Kanton"),
        "BL": ("CH-BL", "Basel-Landschaft", "Basel-Landschaft", "Kanton"),
        "BS": ("CH-BS", "Basel-Stadt", "Basel-Stadt", "Kanton"),
        "FR": ("CH-FR", "Freiburg", "Fribourg", "Kanton"),
        "GE": ("CH-GE", "Genf", "Genève", "Kanton"),
        "GL": ("CH-GL", "Glarus", "Glarus", "Kanton"),
        "GR": ("CH-GR", "Graubünden", "Graubünden", "Kanton"),
        "JU": ("CH-JU", "Jura", "Jura", "Kanton"),
        "LU": ("CH-LU", "Luzern", "Luzern", "Kanton"),
        "NE": ("CH-NE", "Neuenburg", "Neuchâtel", "Kanton"),
        "NW": ("CH-NW", "Nidwalden", "Nidwalden", "Kanton"),
        "OW": ("CH-OW", "Obwalden", "Obwalden", "Kanton"),
        "SG": ("CH-SG", "St. Gallen", "St. Gallen", "Kanton"),
        "SH": ("CH-SH", "Schaffhausen", "Schaffhausen", "Kanton"),
        "SO": ("CH-SO", "Solothurn", "Solothurn", "Kanton"),
        "SZ": ("CH-SZ", "Schwyz", "Schwyz", "Kanton"),
        "TG": ("CH-TG", "Thurgau", "Thurgau", "Kanton"),
        "TI": ("CH-TI", "Tessin", "Ticino", "Kanton"),
        "UR": ("CH-UR", "Uri", "Uri", "Kanton"),
        "VD": ("CH-VD", "Waadt", "Vaud", "Kanton"),
        "VS": ("CH-VS", "Wallis", "Valais", "Kanton"),
        "ZG": ("CH-ZG", "Zug", "Zug", "Kanton"),
        "ZH": ("CH-ZH", "Zürich", "Zürich", "Kanton"),
    },
    "GB": {
        "ENG": ("GB-ENG", "England", "England", "Landesteil"),
        "NIR": ("GB-NIR", "Nordirland", "Northern Ireland", "Landesteil"),
        "SCT": ("GB-SCT", "Schottland", "Scotland", "Landesteil"),
        "WLS": ("GB-WLS", "Wales", "Wales", "Landesteil"),
    },
    "IE": {
        "C": ("IE-C", "Connacht", "Connacht", "Provinz"),
        "L": ("IE-L", "Leinster", "Leinster", "Provinz"),
        "M": ("IE-M", "Munster", "Munster", "Provinz"),
        "U": ("IE-U", "Ulster", "Ulster", "Provinz"),
    },
    "IT": {
        "01": ("IT-65", "Abruzzen", "Abruzzo", "Region"),
        "02": ("IT-77", "Basilikata", "Basilicata", "Region"),
        "03": ("IT-78", "Kalabrien", "Calabria", "Region"),
        "04": ("IT-72", "Kampanien", "Campania", "Region"),
        "05": ("IT-45", "Emilia-Romagna", "Emilia-Romagna", "Region"),
        "06": ("IT-36", "Friaul-Julisch Venetien", "Friuli-Venezia Giulia", "Region"),
        "07": ("IT-62", "Latium", "Lazio", "Region"),
        "08": ("IT-42", "Ligurien", "Liguria", "Region"),
        "09": ("IT-25", "Lombardei", "Lombardia", "Region"),
        "10": ("IT-57", "Marken", "Marche", "Region"),
        "11": ("IT-67", "Molise", "Molise", "Region"),
        "12": ("IT-21", "Piemont", "Piemonte", "Region"),
        "13": ("IT-75", "Apulien", "Puglia", "Region"),
        "14": ("IT-88", "Sardinien", "Sardegna", "Region"),
        "15": ("IT-82", "Sizilien", "Sicilia", "Region"),
        "16": ("IT-52", "Toskana", "Toscana", "Region"),
        "17": ("IT-32", "Trentino-Südtirol", "Trentino-Alto Adige", "Region"),
        "18": ("IT-55", "Umbrien", "Umbria", "Region"),
        "19": ("IT-23", "Aostatal", "Valle d'Aosta", "Region"),
        "20": ("IT-34", "Venetien", "Veneto", "Region"),
    },
    "ES": {
        "07": ("ES-IB", "Balearen", "Illes Balears", "Autonome Gemeinschaft"),
        "27": ("ES-RI", "La Rioja", "La Rioja", "Autonome Gemeinschaft"),
        "29": ("ES-MD", "Madrid (Region)", "Comunidad de Madrid", "Autonome Gemeinschaft"),
        "31": ("ES-MC", "Murcia (Region)", "Región de Murcia", "Autonome Gemeinschaft"),
        "32": ("ES-NC", "Navarra", "Navarra", "Autonome Gemeinschaft"),
        "34": ("ES-AS", "Asturien", "Asturias", "Autonome Gemeinschaft"),
        "39": ("ES-CB", "Kantabrien", "Cantabria", "Autonome Gemeinschaft"),
        "51": ("ES-AN", "Andalusien", "Andalucía", "Autonome Gemeinschaft"),
        "52": ("ES-AR", "Aragonien", "Aragón", "Autonome Gemeinschaft"),
        "53": ("ES-CN", "Kanarische Inseln", "Canarias", "Autonome Gemeinschaft"),
        "54": ("ES-CM", "Kastilien-La Mancha", "Castilla-La Mancha", "Autonome Gemeinschaft"),
        "55": ("ES-CL", "Kastilien und León", "Castilla y León", "Autonome Gemeinschaft"),
        "56": ("ES-CT", "Katalonien", "Catalunya", "Autonome Gemeinschaft"),
        "57": ("ES-EX", "Extremadura", "Extremadura", "Autonome Gemeinschaft"),
        "58": ("ES-GA", "Galicien", "Galicia", "Autonome Gemeinschaft"),
        "59": ("ES-PV", "Baskenland", "Euskadi", "Autonome Gemeinschaft"),
        "60": ("ES-VC", "Valencianische Gemeinschaft", "Comunitat Valenciana", "Autonome Gemeinschaft"),
        "CE": ("ES-CE", "Ceuta", "Ceuta", "Autonome Stadt"),
        "ML": ("ES-ML", "Melilla", "Melilla", "Autonome Stadt"),
    },
    "PT": {
        "02": ("PT-01", "Aveiro", "Aveiro", "Distrikt"),
        "03": ("PT-02", "Beja", "Beja", "Distrikt"),
        "04": ("PT-03", "Braga", "Braga", "Distrikt"),
        "05": ("PT-04", "Bragança", "Bragança", "Distrikt"),
        "06": ("PT-05", "Castelo Branco", "Castelo Branco", "Distrikt"),
        "07": ("PT-06", "Coimbra", "Coimbra", "Distrikt"),
        "08": ("PT-07", "Évora", "Évora", "Distrikt"),
        "09": ("PT-08", "Faro", "Faro", "Distrikt"),
        "10": ("PT-30", "Madeira", "Madeira", "Autonome Region"),
        "11": ("PT-09", "Guarda", "Guarda", "Distrikt"),
        "13": ("PT-10", "Leiria", "Leiria", "Distrikt"),
        "14": ("PT-11", "Lissabon (Distrikt)", "Lisboa", "Distrikt"),
        "16": ("PT-12", "Portalegre", "Portalegre", "Distrikt"),
        "17": ("PT-13", "Porto (Distrikt)", "Porto", "Distrikt"),
        "18": ("PT-14", "Santarém", "Santarém", "Distrikt"),
        "19": ("PT-15", "Setúbal", "Setúbal", "Distrikt"),
        "20": ("PT-16", "Viana do Castelo", "Viana do Castelo", "Distrikt"),
        "21": ("PT-17", "Vila Real", "Vila Real", "Distrikt"),
        "22": ("PT-18", "Viseu", "Viseu", "Distrikt"),
        "23": ("PT-20", "Azoren", "Açores", "Autonome Region"),
    },
    "DK": {
        "17": ("DK-84", "Hauptstadtregion", "Hovedstaden", "Region"),
        "18": ("DK-82", "Midtjylland", "Midtjylland", "Region"),
        "19": ("DK-81", "Nordjylland", "Nordjylland", "Region"),
        "20": ("DK-85", "Seeland", "Sjælland", "Region"),
        "21": ("DK-83", "Süddänemark", "Syddanmark", "Region"),
    },
    "SE": {
        "02": ("SE-K", "Blekinge län", "Blekinge län", "Provinz"),
        "03": ("SE-X", "Gävleborgs län", "Gävleborgs län", "Provinz"),
        "05": ("SE-I", "Gotlands län", "Gotlands län", "Provinz"),
        "06": ("SE-N", "Hallands län", "Hallands län", "Provinz"),
        "07": ("SE-Z", "Jämtlands län", "Jämtlands län", "Provinz"),
        "08": ("SE-F", "Jönköpings län", "Jönköpings län", "Provinz"),
        "09": ("SE-H", "Kalmar län", "Kalmar län", "Provinz"),
        "10": ("SE-W", "Dalarnas län", "Dalarnas län", "Provinz"),
        "12": ("SE-G", "Kronobergs län", "Kronobergs län", "Provinz"),
        "14": ("SE-BD", "Norrbottens län", "Norrbottens län", "Provinz"),
        "15": ("SE-T", "Örebro län", "Örebro län", "Provinz"),
        "16": ("SE-E", "Östergötlands län", "Östergötlands län", "Provinz"),
        "18": ("SE-D", "Södermanlands län", "Södermanlands län", "Provinz"),
        "21": ("SE-C", "Uppsala län", "Uppsala län", "Provinz"),
        "22": ("SE-S", "Värmlands län", "Värmlands län", "Provinz"),
        "23": ("SE-AC", "Västerbottens län", "Västerbottens län", "Provinz"),
        "24": ("SE-Y", "Västernorrlands län", "Västernorrlands län", "Provinz"),
        "25": ("SE-U", "Västmanlands län", "Västmanlands län", "Provinz"),
        "26": ("SE-AB", "Stockholms län", "Stockholms län", "Provinz"),
        "27": ("SE-M", "Skåne län", "Skåne län", "Provinz"),
        "28": ("SE-O", "Västra Götalands län", "Västra Götalands län", "Provinz"),
    },
    "NO": {
        "01": ("NO-32", "Akershus", "Akershus", "Provinz"),
        "04": ("NO-33", "Buskerud", "Buskerud", "Provinz"),
        "05": ("NO-56", "Finnmark", "Finnmark", "Provinz"),
        "08": ("NO-15", "Møre og Romsdal", "Møre og Romsdal", "Provinz"),
        "09": ("NO-18", "Nordland", "Nordland", "Provinz"),
        "12": ("NO-03", "Oslo", "Oslo", "Provinz"),
        "13": ("NO-31", "Østfold", "Østfold", "Provinz"),
        "14": ("NO-11", "Rogaland", "Rogaland", "Provinz"),
        "17": ("NO-40", "Telemark", "Telemark", "Provinz"),
        "18": ("NO-55", "Troms", "Troms", "Provinz"),
        "20": ("NO-39", "Vestfold", "Vestfold", "Provinz"),
        "21": ("NO-50", "Trøndelag", "Trøndelag", "Provinz"),
        "34": ("NO-34", "Innlandet", "Innlandet", "Provinz"),
        "42": ("NO-42", "Agder", "Agder", "Provinz"),
        "46": ("NO-46", "Vestland", "Vestland", "Provinz"),
    },
    "PL": {
        "72": ("PL-02", "Niederschlesien", "Dolnośląskie", "Woiwodschaft"),
        "73": ("PL-04", "Kujawien-Pommern", "Kujawsko-Pomorskie", "Woiwodschaft"),
        "74": ("PL-10", "Łódź (Woiwodschaft)", "Łódzkie", "Woiwodschaft"),
        "75": ("PL-06", "Lublin (Woiwodschaft)", "Lubelskie", "Woiwodschaft"),
        "76": ("PL-08", "Lebus", "Lubuskie", "Woiwodschaft"),
        "77": ("PL-12", "Kleinpolen", "Małopolskie", "Woiwodschaft"),
        "78": ("PL-14", "Masowien", "Mazowieckie", "Woiwodschaft"),
        "79": ("PL-16", "Oppeln", "Opolskie", "Woiwodschaft"),
        "80": ("PL-18", "Karpatenvorland", "Podkarpackie", "Woiwodschaft"),
        "81": ("PL-20", "Podlachien", "Podlaskie", "Woiwodschaft"),
        "82": ("PL-22", "Pommern", "Pomorskie", "Woiwodschaft"),
        "83": ("PL-24", "Schlesien", "Śląskie", "Woiwodschaft"),
        "84": ("PL-26", "Heiligkreuz", "Świętokrzyskie", "Woiwodschaft"),
        "85": ("PL-28", "Ermland-Masuren", "Warmińsko-Mazurskie", "Woiwodschaft"),
        "86": ("PL-30", "Großpolen", "Wielkopolskie", "Woiwodschaft"),
        "87": ("PL-32", "Westpommern", "Zachodniopomorskie", "Woiwodschaft"),
    },
    "CZ": {
        "52": ("CZ-10", "Prag", "Praha", "Region"),
        "78": ("CZ-64", "Südmähren", "Jihomoravský kraj", "Region"),
        "79": ("CZ-31", "Südböhmen", "Jihočeský kraj", "Region"),
        "80": ("CZ-63", "Vysočina", "Kraj Vysočina", "Region"),
        "81": ("CZ-41", "Karlsbad (Region)", "Karlovarský kraj", "Region"),
        "82": ("CZ-52", "Königgrätz (Region)", "Královéhradecký kraj", "Region"),
        "83": ("CZ-51", "Reichenberg (Region)", "Liberecký kraj", "Region"),
        "84": ("CZ-71", "Olmütz (Region)", "Olomoucký kraj", "Region"),
        "85": ("CZ-80", "Mährisch-Schlesien", "Moravskoslezský kraj", "Region"),
        "86": ("CZ-53", "Pardubitz (Region)", "Pardubický kraj", "Region"),
        "87": ("CZ-32", "Pilsen (Region)", "Plzeňský kraj", "Region"),
        "88": ("CZ-20", "Mittelböhmen", "Středočeský kraj", "Region"),
        "89": ("CZ-42", "Aussig (Region)", "Ústecký kraj", "Region"),
        "90": ("CZ-72", "Zlín (Region)", "Zlínský kraj", "Region"),
    },
    "CA": {
        "01": ("CA-AB", "Alberta", "Alberta", "Provinz"),
        "02": ("CA-BC", "British Columbia", "British Columbia", "Provinz"),
        "03": ("CA-MB", "Manitoba", "Manitoba", "Provinz"),
        "04": ("CA-NB", "New Brunswick", "New Brunswick", "Provinz"),
        "05": ("CA-NL", "Neufundland und Labrador", "Newfoundland and Labrador", "Provinz"),
        "07": ("CA-NS", "Nova Scotia", "Nova Scotia", "Provinz"),
        "08": ("CA-ON", "Ontario", "Ontario", "Provinz"),
        "09": ("CA-PE", "Prince Edward Island", "Prince Edward Island", "Provinz"),
        "10": ("CA-QC", "Québec", "Québec", "Provinz"),
        "11": ("CA-SK", "Saskatchewan", "Saskatchewan", "Provinz"),
        "12": ("CA-YT", "Yukon", "Yukon", "Territorium"),
        "13": ("CA-NT", "Nordwest-Territorien", "Northwest Territories", "Territorium"),
        "14": ("CA-NU", "Nunavut", "Nunavut", "Territorium"),
    },
    "AU": {
        "01": ("AU-ACT", "Australian Capital Territory", "Australian Capital Territory", "Territorium"),
        "02": ("AU-NSW", "New South Wales", "New South Wales", "Bundesstaat"),
        "03": ("AU-NT", "Northern Territory", "Northern Territory", "Territorium"),
        "04": ("AU-QLD", "Queensland", "Queensland", "Bundesstaat"),
        "05": ("AU-SA", "South Australia", "South Australia", "Bundesstaat"),
        "06": ("AU-TAS", "Tasmanien", "Tasmania", "Bundesstaat"),
        "07": ("AU-VIC", "Victoria", "Victoria", "Bundesstaat"),
        "08": ("AU-WA", "Western Australia", "Western Australia", "Bundesstaat"),
    },
}

# Aliases for regions frequently written differently on ticket/venue pages
REGION_EXTRA_ALIASES = {
    "DE-SL": ["Saar", "SL", "Saarland (DE)"],
    "DE-RP": ["RLP", "RP", "Rhineland-Palatinate", "Rhénanie-Palatinat"],
    "DE-NW": ["NRW", "North Rhine-Westphalia"],
    "DE-BW": ["BW", "BaWü"],
    "DE-BY": ["Bavaria", "Bavière", "BY"],
    "DE-HE": ["Hesse"],
    "DE-NI": ["Lower Saxony", "Basse-Saxe"],
    "DE-SN": ["Saxony", "Saxe"],
    "DE-TH": ["Thuringia", "Thüringen"],
    "DE-ST": ["Saxony-Anhalt"],
    "DE-MV": ["Mecklenburg-Western Pomerania", "MV"],
    "FR-GES": ["Grand-Est", "Lorraine", "Alsace", "Champagne-Ardenne", "Lothringen", "Elsass"],
    "FR-IDF": ["Ile-de-France", "Paris Region"],
    "FR-HDF": ["Nord-Pas-de-Calais", "Picardie"],
    "FR-ARA": ["Rhône-Alpes", "Auvergne"],
    "FR-OCC": ["Occitanie", "Languedoc-Roussillon", "Midi-Pyrénées", "Occitania"],
    "FR-NAQ": ["Aquitaine", "Limousin", "Poitou-Charentes"],
    "FR-BFC": ["Bourgogne", "Franche-Comté", "Burgund"],
    "FR-PAC": ["PACA", "Provence", "Côte d'Azur"],
    "BE-WAL": ["Wallonie", "Wallonia", "Walloon Region", "Région wallonne", "Wallonien"],
    "BE-VLG": ["Flanders", "Vlaanderen", "Flandre", "Vlaams Gewest", "Flemish Region"],
    "BE-BRU": ["Brussels", "Bruxelles", "Brussel", "Brussels-Capital Region", "Brüssel"],
    "LU-LU": ["Luxembourg (canton)", "Luxemburg (Kanton)"],
    "LU-ES": ["Esch", "Canton d'Esch-sur-Alzette"],
    "GB-ENG": ["England"],
    "GB-SCT": ["Scotland"],
    "AT-9": ["Vienna", "Wien"],
    "AT-3": ["Lower Austria"],
    "AT-4": ["Upper Austria"],
    "AT-6": ["Styria"],
    "AT-7": ["Tyrol"],
    "AT-2": ["Carinthia"],
    "CH-ZH": ["Zurich"],
    "CH-GE": ["Geneva", "Genève"],
    "CH-VD": ["Vaud"],
    "CH-BE": ["Berne"],
    "NL-NH": ["North Holland", "Noord-Holland"],
    "NL-ZH": ["South Holland", "Zuid-Holland"],
    "NL-NB": ["North Brabant", "Noord-Brabant"],
    "NL-LI": ["Limburg"],
}

# Display names commonly used in German for foreign cities (GeoNames name -> German)
CITY_DE_NAMES = {
    ("DE", "Munich"): "München", ("DE", "Nuremberg"): "Nürnberg", ("DE", "Cologne"): "Köln",
    ("DE", "Hanover"): "Hannover", ("DE", "Brunswick"): "Braunschweig",
    ("AT", "Vienna"): "Wien",
    ("CH", "Geneva"): "Genf", ("CH", "Lucerne"): "Luzern", ("CH", "Zurich"): "Zürich",
    ("BE", "Brussels"): "Brüssel", ("BE", "Antwerp"): "Antwerpen", ("BE", "Brugge"): "Brügge",
    ("BE", "Liège"): "Lüttich", ("BE", "Ostend"): "Ostende",
    ("LU", "Luxembourg"): "Luxemburg",
    ("FR", "Strasbourg"): "Straßburg", ("FR", "Nice"): "Nizza",
    ("IT", "Rome"): "Rom", ("IT", "Milan"): "Mailand", ("IT", "Naples"): "Neapel",
    ("IT", "Venice"): "Venedig", ("IT", "Florence"): "Florenz", ("IT", "Turin"): "Turin",
    ("IT", "Genoa"): "Genua", ("IT", "Padua"): "Padua", ("IT", "Bolzano"): "Bozen",
    ("IT", "Merano"): "Meran", ("IT", "Trento"): "Trient",
    ("CZ", "Prague"): "Prag", ("CZ", "Brno"): "Brünn", ("CZ", "Pilsen"): "Pilsen",
    ("CZ", "Karlovy Vary"): "Karlsbad",
    ("PL", "Warsaw"): "Warschau", ("PL", "Kraków"): "Krakau",
    ("DK", "Copenhagen"): "Kopenhagen", ("DK", "Århus"): "Aarhus",
    ("PT", "Lisbon"): "Lissabon",
    ("NL", "The Hague"): "Den Haag",
    ("SE", "Gothenburg"): "Göteborg",
    ("GR", "Athens"): "Athen",
    ("RU", "Moscow"): "Moskau",
}

# Aliases that matter for concert listings but are not in GeoNames
CITY_EXTRA_ALIASES = {
    ("LU", "Luxembourg"): ["Luxembourg City", "Luxembourg-Ville", "Luxemburg-Stadt", "Lëtzebuerg",
                           "Luxembourg-Kirchberg", "Kirchberg Luxembourg"],
    ("LU", "Esch-sur-Alzette"): ["Esch-Belval", "Belval", "Esch/Alzette", "Esch Alzette"],
    ("FR", "Strasbourg"): ["Straßburg", "Strassburg"],
    ("DE", "Saarbrücken"): ["Saarbruecken", "Sarrebruck"],
    ("DE", "Sankt Ingbert"): ["St. Ingbert", "St Ingbert"],
    ("DE", "Sankt Wendel"): ["St. Wendel", "St Wendel"],
    ("DE", "Frankfurt am Main"): ["Frankfurt", "Frankfurt/Main", "Frankfurt a. M.", "Frankfurt a.M."],
    ("DE", "Köln"): ["Cologne", "Koeln"],
    ("DE", "Munich"): ["München", "Muenchen"],
    ("DE", "Nuremberg"): ["Nürnberg", "Nuernberg"],
    ("DE", "Düsseldorf"): ["Duesseldorf"],
    ("DE", "Halle (Saale)"): ["Halle", "Halle/Saale"],
    ("DE", "Neunkirchen"): ["Neunkirchen (Saar)", "Neunkirchen/Saar"],
    ("BE", "Brussels"): ["Bruxelles", "Brussel", "Brüssel", "Forest", "Vorst"],
    ("BE", "Antwerp"): ["Antwerpen", "Anvers", "Merksem"],
    ("BE", "Liège"): ["Lüttich", "Luik", "Liege"],
    ("NL", "The Hague"): ["Den Haag", "'s-Gravenhage"],
    ("AT", "Vienna"): ["Wien"],
    ("CH", "Geneva"): ["Genève", "Genf"],
    ("CH", "Zürich"): ["Zurich"],
    ("FR", "Paris"): ["Paris (France)"],
}

LATIN_RE = re.compile(r"^[A-Za-zÀ-ɏḀ-ỿ' .\-’()/]+$")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s.replace("ß", "ss")).strip()


def clean_aliases(name: str, alternates: list[str], extra: list[str], limit: int) -> list[str]:
    seen = {norm(name)}
    out: list[str] = []
    extra_set = set(extra)
    for alias in list(extra) + list(alternates):
        alias = alias.strip()
        if alias not in extra_set:
            # curated aliases bypass these heuristics
            if len(alias) < 3 or len(alias) > 60:
                continue
            if not LATIN_RE.match(alias):
                continue
            if any(ch.isdigit() for ch in alias):
                continue
            if alias.isupper() and len(alias) <= 4:
                continue  # IATA codes and similar
            if not alias[0].isupper():
                continue  # romanised transliterations ("sa er bu lu ken")
        key = norm(alias)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(alias)
    # extra aliases always survive, others are capped
    return out[: max(limit, len(extra))]


def load_cities(name: str) -> list[dict]:
    with open(DATA / name, encoding="utf-8") as fh:
        return list(json.load(fh).values())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    de1 = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["de"])

    # ---------------------------------------------------------------- countries
    gn_countries = json.load(open(DATA / "countries.json", encoding="utf-8"))
    countries = []
    for iso, info in sorted(gn_countries.items()):
        pc = pycountry.countries.get(alpha_2=iso)
        if pc is None:
            continue
        name_en = COUNTRY_NAME_EN_OVERRIDES.get(iso) or getattr(pc, "common_name", None) or pc.name
        name_de = COUNTRY_NAME_DE_OVERRIDES.get(iso) or de1.gettext(pc.name)
        aliases = [pc.name, getattr(pc, "official_name", None), info.get("name"), name_en, name_de]
        aliases += COUNTRY_EXTRA_ALIASES.get(iso, [])
        aliases = clean_aliases(name_de, [], [a for a in aliases if a], limit=40)
        countries.append(
            {
                "code": iso,
                "code3": pc.alpha_3,
                "name_de": name_de,
                "name_en": name_en,
                "aliases": aliases,
                "continent": info.get("continentcode"),
                "priority": COUNTRY_PRIORITY.get(iso, 100),
            }
        )
    (OUT / "countries.json").write_text(json.dumps(countries, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------------------------------------------------------- regions
    us_states = json.load(open(DATA / "us_states.json", encoding="utf-8"))
    REGIONS["US"] = {
        code: (f"US-{code}", info["name"], info["name"], "Bundesstaat") for code, info in us_states.items()
    }
    regions = []
    for cc, mapping in sorted(REGIONS.items()):
        for gn_code, (iso, name_de, name_local, kind) in sorted(mapping.items()):
            aliases = [name_local, name_de, iso.split("-", 1)[1]] + REGION_EXTRA_ALIASES.get(iso, [])
            regions.append(
                {
                    "code": iso,
                    "country": cc,
                    "geonames": f"{cc}.{gn_code}",
                    "name": name_local,
                    "name_de": name_de,
                    "kind": kind,
                    "aliases": clean_aliases(name_de, [], aliases, limit=20),
                }
            )
    (OUT / "regions.json").write_text(json.dumps(regions, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------------------------------------------------------- cities
    c500 = load_cities("cities500.json")
    c1000 = load_cities("cities1000.json")
    c15000 = load_cities("cities15000.json")

    selected: dict[int, dict] = {}

    def add(city: dict) -> None:
        selected.setdefault(city["geonameid"], city)

    tier1 = set(TIER1)
    for c in c1000:
        if c["countrycode"] in tier1:
            add(c)
    for c in c500:
        cc, a1 = c["countrycode"], c["admin1code"]
        if (cc, None) in TIER1_DETAIL or (cc, a1) in TIER1_DETAIL:
            add(c)
    tier2 = set(TIER2)
    for c in c15000:
        if c["countrycode"] in tier2:
            add(c)
        elif c["countrycode"] not in tier1 and c["population"] >= REST_MIN_POP:
            add(c)

    valid_countries = {c["code"] for c in countries}
    count = 0
    seen_names: set[tuple[str, str]] = set()
    with gzip.open(OUT / "cities.jsonl.gz", "wt", encoding="utf-8", compresslevel=9) as fh:
        for city in sorted(selected.values(), key=lambda c: (c["countrycode"], -c["population"], c["name"])):
            cc = city["countrycode"]
            if cc not in valid_countries:
                continue
            region = REGIONS.get(cc, {}).get(city["admin1code"])
            name = city["name"]
            # curated aliases/German names only apply to the most populous city of that name
            key = (cc, name)
            first_of_name = key not in seen_names
            seen_names.add(key)
            extra = CITY_EXTRA_ALIASES.get(key, []) if first_of_name else []
            limit = 25 if cc in tier1 else 12
            record = {
                "gid": city["geonameid"],
                "cc": cc,
                "r": region[0] if region else None,
                "n": name,
                "de": CITY_DE_NAMES.get(key) if first_of_name else None,
                "a": clean_aliases(name, city.get("alternatenames") or [], extra, limit),
                "lat": round(city["latitude"], 5),
                "lon": round(city["longitude"], 5),
                "p": city["population"],
                "tz": city["timezone"],
            }
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1

    print(f"countries: {len(countries)}  regions: {len(regions)}  cities: {count}")
    print(f"output: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
