"""HTML helpers: parsing, metadata, link discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from tourdesk.core.text import clean_text, safe_url

TOUR_KEYWORDS = (
    "tour", "tourdates", "tour-dates", "dates", "live", "shows", "concerts", "konzerte", "termine", "gigs", "events",
    "tickets", "touring", "tournee", "tournée", "dates-de-tournee", "agenda", "on-tour", "upcoming",
)
AGENDA_KEYWORDS = (
    "agenda", "programm", "program", "programme", "events", "veranstaltungen", "konzerte", "kalender", "calendar",
    "spielplan", "concerts", "shows", "termine", "line-up", "lineup", "evenements", "événements", "concerten", "upcoming",
)
LINEUP_KEYWORDS = ("line-up", "lineup", "bands", "artists", "künstler", "kuenstler", "acts", "programm", "program", "artistes", "running-order")
_SKIP_HREF = re.compile(r"^(mailto:|tel:|javascript:|#)", re.I)
_ASSET_EXT = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp3|mp4|css|js|ico)(\?|$)", re.I)


@dataclass
class PageInfo:
    url: str
    lang: str | None
    title: str | None
    og_image: str | None
    canonical: str | None


def parse_html(text: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(text, "lxml")
    except Exception:  # pragma: no cover - lxml missing
        return BeautifulSoup(text, "html.parser")


def page_info(soup: BeautifulSoup, url: str) -> PageInfo:
    html_tag = soup.find("html")
    lang = html_tag.get("lang") if isinstance(html_tag, Tag) else None
    title = clean_text(soup.title.get_text()) if soup.title else None
    og = None
    for prop in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if isinstance(tag, Tag) and tag.get("content"):
            og = safe_url(urljoin(url, str(tag["content"]).strip()))
            if og:
                break
    if og is None:
        link = soup.find("link", attrs={"rel": "image_src"})
        if isinstance(link, Tag) and link.get("href"):
            og = safe_url(urljoin(url, str(link["href"])))
    canonical = None
    link = soup.find("link", attrs={"rel": "canonical"})
    if isinstance(link, Tag) and link.get("href"):
        canonical = safe_url(urljoin(url, str(link["href"])))
    return PageInfo(url=url, lang=str(lang) if lang else None, title=title, og_image=og, canonical=canonical)


def same_site(a: str, b: str) -> bool:
    ha = (urlsplit(a).hostname or "").lower().removeprefix("www.")
    hb = (urlsplit(b).hostname or "").lower().removeprefix("www.")
    return bool(ha) and (ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha))


def normalize_link(base: str, href: str) -> str | None:
    if not href or _SKIP_HREF.match(href.strip()):
        return None
    url = safe_url(urljoin(base, href.strip()))
    if not url or _ASSET_EXT.search(url):
        return None
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def discover_links(soup: BeautifulSoup, base_url: str, keywords: tuple[str, ...], *, limit: int = 5) -> list[str]:
    """Same-site links whose text or path suggests a tour/agenda/line-up page, best first."""
    scored: dict[str, int] = {}
    for a in soup.find_all("a", href=True):
        url = normalize_link(base_url, str(a["href"]))
        if not url or not same_site(url, base_url) or url.rstrip("/") == base_url.rstrip("/"):
            continue
        text = (a.get_text(" ", strip=True) or "").casefold()
        path = urlsplit(url).path.casefold()
        score = 0
        for i, kw in enumerate(keywords):
            weight = max(1, 10 - i)
            if re.search(rf"(^|[/\-_]){re.escape(kw)}([/\-_.]|$)", path):
                score += weight * 2
            if text == kw or text.startswith(kw + " ") or text.endswith(" " + kw):
                score += weight * 3
            elif kw in text and len(text) < 40:
                score += weight
        if score:
            # shallower paths first
            score -= path.count("/")
            scored[url] = max(scored.get(url, 0), score)
    return [u for u, _ in sorted(scored.items(), key=lambda kv: -kv[1])][:limit]


def find_next_page(soup: BeautifulSoup, base_url: str) -> str | None:
    link = soup.find("link", attrs={"rel": "next"}) or soup.find("a", attrs={"rel": "next"})
    if isinstance(link, Tag) and link.get("href"):
        return normalize_link(base_url, str(link["href"]))
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True).casefold()
        if text in ("next", "weiter", "nächste seite", "suivant", "volgende", "mehr laden", "load more", "›", "»", "next page"):
            url = normalize_link(base_url, str(a["href"]))
            if url and same_site(url, base_url):
                return url
    return None


def strip_noise(soup: BeautifulSoup) -> BeautifulSoup:
    for tag in soup(["script", "style", "noscript", "svg", "template", "iframe", "form", "nav"]):
        tag.decompose()
    for tag in soup.find_all(["header", "footer"]):
        # keep headers/footers that look like part of an event list
        if not tag.find(string=re.compile(r"\d{1,2}[./]\d{1,2}")):
            tag.decompose()
    return soup


def detect_widgets(soup: BeautifulSoup) -> dict[str, str]:
    """Detect embedded tour widgets of common providers."""
    found: dict[str, str] = {}
    bit = soup.find(attrs={"class": re.compile(r"bit-widget-initializer")})
    if isinstance(bit, Tag) and bit.get("data-artist-name"):
        found["bandsintown_artist"] = str(bit["data-artist-name"])
    for script in soup.find_all("script", src=True):
        src = str(script["src"])
        if "widget.seated.com" in src or "seated.com" in src:
            sid = script.get("data-artist-id")
            if sid:
                found["seated_artist_id"] = str(sid)
        if "songkick" in src:
            found["songkick_widget"] = src
    sk = soup.find("a", attrs={"class": re.compile(r"songkick-widget")})
    if isinstance(sk, Tag) and sk.get("href"):
        found["songkick_url"] = str(sk["href"])
    return found
