"""Multilingual date and time parsing for concert listings (de, en, fr, nl, it, es, lb)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from dateutil import parser as dateutil_parser

_MONTH_NAMES: dict[str, int] = {}


def _add(month: int, *names: str) -> None:
    for name in names:
        _MONTH_NAMES[name] = month


_add(1, "januar", "jan", "january", "janvier", "janv", "januari", "gennaio", "enero", "jänner", "jaenner", "janner")
_add(2, "februar", "feb", "febr", "february", "février", "fevrier", "févr", "fevr", "februari", "febbraio", "febrero")
_add(3, "märz", "maerz", "marz", "mär", "mar", "mrz", "march", "mars", "maart", "mrt", "marzo", "mäerz")
_add(4, "april", "apr", "avril", "avr", "aprile", "abril", "abrëll", "abrell")
_add(5, "mai", "may", "mei", "maggio", "mayo", "mee")
_add(6, "juni", "jun", "june", "juin", "giugno", "junio")
_add(7, "juli", "jul", "july", "juillet", "juil", "luglio", "julio")
_add(8, "august", "aug", "août", "aout", "augustus", "agosto")
_add(9, "september", "sep", "sept", "septembre", "settembre", "septiembre")
_add(10, "oktober", "okt", "october", "oct", "octobre", "ottobre", "octubre")
_add(11, "november", "nov", "novembre", "noviembre")
_add(12, "dezember", "dez", "december", "dec", "décembre", "decembre", "déc", "dicembre", "diciembre")

_MONTH_ALT = "|".join(sorted((re.escape(n) for n in _MONTH_NAMES), key=len, reverse=True))
_MONTH = rf"(?P<mon>{_MONTH_ALT})\.?"
_YEAR = r"(?P<y>(?:19|20)\d\d)"
_DAY_SUFFIX = r"(?:\.|st|nd|rd|th|er|e|ème)?"

_FLAGS = re.IGNORECASE | re.UNICODE

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("iso", re.compile(r"(?<!\d)(?P<y>20\d\d)-(?P<m>[01]?\d)-(?P<d>[0-3]?\d)(?!\d)")),
    (
        "num_range",
        re.compile(
            r"(?<![\d.])(?P<d1>[0-3]?\d)\.(?:(?P<m1>[01]?\d)\.)?\s*(?:-|–|—|bis|to|au)\s*(?P<d2>[0-3]?\d)\.(?P<m2>[01]?\d)\.(?P<y>(?:20)?\d\d)(?![\d])",
            _FLAGS,
        ),
    ),
    ("num_dmy", re.compile(r"(?<![\d./])(?P<d>[0-3]?\d)(?P<sep>[./-])(?P<m>[0-3]?\d)(?P=sep)(?P<y>(?:20)?\d\d)(?![\d])")),
    (
        "text_range",
        re.compile(
            rf"(?<!\d)(?P<d1>[0-3]?\d){_DAY_SUFFIX}\s*(?:-|–|—|/|&|bis|to|au|t/m)\s*(?P<d2>[0-3]?\d){_DAY_SUFFIX}\s*(?:de\s+)?{_MONTH}(?![a-zà-ÿ])\s*,?\s*(?:de\s+)?{_YEAR}?",
            _FLAGS,
        ),
    ),
    (
        "text_dmy",
        re.compile(
            rf"(?<!\d)(?P<d>[0-3]?\d){_DAY_SUFFIX}\s*(?:de\s+)?{_MONTH}(?![a-zà-ÿ])\s*,?\s*(?:de\s+)?{_YEAR}?",
            _FLAGS,
        ),
    ),
    (
        "text_mdy",
        re.compile(
            rf"(?<![a-zà-ÿ]){_MONTH}(?![a-zà-ÿ])\s*(?P<d>[0-3]?\d)(?:st|nd|rd|th)?(?:\s*(?:-|–)\s*(?P<d2>[0-3]?\d)(?:st|nd|rd|th)?)?(?!\d)\s*,?\s*{_YEAR}?",
            _FLAGS,
        ),
    ),
    ("num_dm", re.compile(r"(?<![\d./])(?P<d>[0-3]?\d)\.(?P<m>[01]?\d)\.(?![\d])")),
]


@dataclass(frozen=True)
class DateMatch:
    start: date
    end: date | None
    span: tuple[int, int]
    text: str
    has_year: bool
    kind: str


def _strip(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def month_number(name: str) -> int | None:
    key = name.casefold().rstrip(".")
    if key in _MONTH_NAMES:
        return _MONTH_NAMES[key]
    stripped = _strip(key)
    for n, m in _MONTH_NAMES.items():
        if _strip(n) == stripped:
            return m
    return None


def _year(raw: str | None, month: int, day: int, today: date) -> tuple[int, bool]:
    if raw:
        y = int(raw)
        if y < 100:
            y += 2000
        return y, True
    year = today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return year, False
    if candidate < today - timedelta(days=60):
        year += 1
    return year, False


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str, *, today: date | None = None, locale: str | None = None) -> list[DateMatch]:
    """Find all dates in ``text`` (non-overlapping, in order of appearance)."""
    if not text:
        return []
    today = today or date.today()
    us_locale = bool(locale and locale.lower().startswith("en-us"))
    taken: list[tuple[int, int]] = []
    out: list[DateMatch] = []

    def free(span: tuple[int, int]) -> bool:
        return all(span[1] <= a or span[0] >= b for a, b in taken)

    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            span = m.span()
            if not free(span):
                continue
            g = m.groupdict()
            start: date | None = None
            end: date | None = None
            has_year = bool(g.get("y"))
            if kind == "iso":
                start = _safe_date(int(g["y"]), int(g["m"]), int(g["d"]))
            elif kind == "num_range":
                m2 = int(g["m2"])
                m1 = int(g["m1"]) if g.get("m1") else m2
                y, has_year = _year(g["y"], m2, int(g["d2"]), today)
                start = _safe_date(y, m1, int(g["d1"]))
                end = _safe_date(y, m2, int(g["d2"]))
                if start and end and end < start:
                    start = _safe_date(y - 1, m1, int(g["d1"]))
            elif kind == "num_dmy":
                a, b = int(g["d"]), int(g["m"])
                day, month = a, b
                if g["sep"] in "/-":
                    if b > 12 and a <= 12:
                        day, month = b, a
                    elif us_locale and a <= 12 and b <= 12:
                        day, month = b, a
                y, has_year = _year(g["y"], month, day, today)
                start = _safe_date(y, month, day)
            elif kind == "num_dm":
                day, month = int(g["d"]), int(g["m"])
                if not (1 <= month <= 12 and 1 <= day <= 31):
                    continue
                y, has_year = _year(None, month, day, today)
                start = _safe_date(y, month, day)
            elif kind in ("text_range", "text_dmy", "text_mdy"):
                month = month_number(g["mon"])
                if month is None:
                    continue
                if kind == "text_range":
                    d1, d2 = int(g["d1"]), int(g["d2"])
                elif kind == "text_mdy" and g.get("d2"):
                    d1, d2 = int(g["d"]), int(g["d2"])
                else:
                    d1, d2 = int(g["d"]), None
                y, has_year = _year(g.get("y"), month, d1, today)
                start = _safe_date(y, month, d1)
                if d2 is not None:
                    end = _safe_date(y, month, d2)
                    if end and start and end < start:
                        end = None
            if start is None:
                continue
            if not (date(2000, 1, 1) <= start <= today + timedelta(days=365 * 4)):
                continue
            taken.append(span)
            out.append(DateMatch(start=start, end=end, span=span, text=m.group(0).strip(), has_year=has_year, kind=kind))
    out.sort(key=lambda dm: dm.span[0])
    return out


_TIME_24 = re.compile(r"(?<![\d.:])(?P<h>[01]?\d|2[0-3])\s*[:.h]\s*(?P<m>[0-5]\d)(?![\d])\s*(?:uhr|h)?", _FLAGS)
_TIME_UHR = re.compile(r"(?<![\d.:])(?P<h>[01]?\d|2[0-3])\s*(?:uhr|h)(?![a-z0-9])", _FLAGS)
_TIME_12 = re.compile(r"(?<![\d.:])(?P<h>1[0-2]|0?[1-9])(?::(?P<m>[0-5]\d))?\s*(?P<ap>[ap])\.?\s?m\.?(?![a-z])", _FLAGS)
_DOORS_WORDS = ("einlass", "doors", "door", "portes", "ouverture", "deuren", "deur", "open")
_START_WORDS = ("beginn", "start", "show", "konzert", "concert", "début", "debut", "aanvang", "showtime", "anfang")


def find_times(text: str) -> tuple[time | None, time | None]:
    """Return ``(start_time, doors_time)`` found in ``text``."""
    if not text:
        return None, None
    found: list[tuple[int, time]] = []
    taken: list[tuple[int, int]] = []
    for pattern in (_TIME_12, _TIME_24, _TIME_UHR):
        for m in pattern.finditer(text):
            span = m.span()
            if any(not (span[1] <= a or span[0] >= b) for a, b in taken):
                continue
            g = m.groupdict()
            hour = int(g["h"])
            minute = int(g.get("m") or 0)
            if g.get("ap"):
                if g["ap"].lower() == "p" and hour != 12:
                    hour += 12
                if g["ap"].lower() == "a" and hour == 12:
                    hour = 0
            if not (0 <= hour <= 23):
                continue
            # concerts rarely start before 10:00 – avoid catching e.g. "1.5" prices
            if hour < 9 and not g.get("ap"):
                if not (hour == 0 and minute == 0):
                    continue
            taken.append(span)
            found.append((span[0], time(hour, minute)))
    if not found:
        return None, None
    found.sort()
    lowered = text.lower()
    start_t: time | None = None
    doors_t: time | None = None
    for pos, t in found:
        context = lowered[max(0, pos - 18) : pos]
        if any(w in context for w in _DOORS_WORDS):
            doors_t = doors_t or t
        elif any(w in context for w in _START_WORDS):
            start_t = start_t or t
    remaining = [t for _, t in found if t not in (start_t, doors_t)]
    if start_t is None and remaining:
        if doors_t is None and len(remaining) >= 2:
            doors_t, start_t = min(remaining[:2]), max(remaining[:2])
        else:
            later = [t for t in remaining if doors_t is None or t > doors_t]
            start_t = later[0] if later else remaining[0]
    if start_t is not None and doors_t is not None and doors_t > start_t:
        doors_t, start_t = start_t, doors_t
    return start_t, doors_t


def parse_iso_datetime(value: str | None) -> tuple[date | None, time | None, tzinfo | None]:
    """Parse ISO-8601 like ``2027-03-12T20:00:00+01:00`` (as used by schema.org)."""
    if not value or not isinstance(value, str):
        return None, None, None
    value = value.strip()
    if not value:
        return None, None, None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", value)
    if m:
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d, None, None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = dateutil_parser.isoparse(value)
        except (ValueError, OverflowError):
            try:
                dt = dateutil_parser.parse(value, dayfirst=True, fuzzy=True)
            except (ValueError, OverflowError):
                return None, None, None
    has_time = "T" in value or re.search(r"\d{1,2}:\d{2}", value) is not None
    t = dt.timetz().replace(tzinfo=None) if has_time else None
    if t is not None and t == time(0, 0) and value.endswith(("T00:00:00", "T00:00")):
        t = None  # midnight usually means "no time given"
    return dt.date(), t, dt.tzinfo


def to_local(d: date, t: time | None, tz: tzinfo | None, target_tz: str | None) -> tuple[date, time | None]:
    """Convert a date/time with offset into the venue's local time zone."""
    if t is None or tz is None or not target_tz:
        return d, t
    from zoneinfo import ZoneInfo

    try:
        local = datetime.combine(d, t, tz).astimezone(ZoneInfo(target_tz))
    except Exception:
        return d, t
    return local.date(), local.time().replace(tzinfo=None)
