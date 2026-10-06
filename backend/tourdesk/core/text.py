"""Text normalisation helpers shared by API, matcher and crawler."""

from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import urlsplit

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")
_TAG_RE = re.compile(r"<[^>]+>")
_GERMAN_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})
_SAINT_TOKENS = {"st": "st", "sankt": "st", "saint": "st", "san": "san", "sainte": "ste", "ste": "ste"}
_ARTICLES = ("the ", "die ", "der ", "das ", "le ", "la ", "les ", "de ", "het ", "il ", "el ")


def strip_accents(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def normalize_name(value: str | None) -> str:
    """Lowercase, accent-free, punctuation-free representation used for matching.

    ``"Sankt Ingbert"`` and ``"St. Ingbert"`` both become ``"st ingbert"``;
    ``"Saarbrücken"`` becomes ``"saarbrucken"``.
    """
    if not value:
        return ""
    value = value.casefold().replace("ß", "ss").replace("&", " and ").replace("+", " and ")
    value = strip_accents(value)
    value = _NON_ALNUM_RE.sub(" ", value)
    tokens = [_SAINT_TOKENS.get(t, t) for t in value.split()]
    return " ".join(tokens)


def normalize_variants(value: str | None) -> set[str]:
    """All normalised spellings of a name (accent stripping, German transliteration,
    with/without leading article, '&'/'and'/'und'/'et')."""
    if not value:
        return set()
    out = {normalize_name(value), normalize_name(value.translate(_GERMAN_TRANSLIT))}
    for v in list(out):
        for art in _ARTICLES:
            if v.startswith(art) and len(v) > len(art) + 2:
                out.add(v[len(art) :])
        for conj in (" und ", " et ", " en "):
            if conj in f" {v} ":
                out.add(f" {v} ".replace(conj, " and ").strip())
    out.discard("")
    return out


def slugify(value: str, max_length: int = 80) -> str:
    value = normalize_name(value)
    slug = value.replace(" ", "-")
    return slug[:max_length].strip("-") or "item"


def clean_text(value: str | None, max_length: int | None = None) -> str | None:
    """Collapse whitespace, unescape entities, drop tags. Returns ``None`` for empty."""
    if value is None:
        return None
    value = html.unescape(str(value))
    value = _TAG_RE.sub(" ", value)
    value = value.replace(" ", " ").replace("​", "")
    value = _WS_RE.sub(" ", value).strip()
    if not value:
        return None
    if max_length and len(value) > max_length:
        value = value[: max_length - 1].rstrip() + "…"
    return value


def is_http_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc) and " " not in value.strip()


def safe_url(value: str | None, max_length: int = 1000) -> str | None:
    """Return the URL if it is a plain http(s) URL, else ``None`` (prevents ``javascript:``)."""
    if not value:
        return None
    value = value.strip()
    if len(value) > max_length or not is_http_url(value):
        return None
    return value


def url_domain(value: str | None) -> str | None:
    if not value:
        return None
    try:
        host = urlsplit(value).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def escape_like(value: str) -> str:
    """Escape LIKE wildcards for use with ``ESCAPE '\\'``."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
