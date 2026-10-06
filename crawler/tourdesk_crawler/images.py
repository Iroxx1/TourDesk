"""Artist image discovery: 1. official website, 2. Wikimedia Commons (Wikidata), 3. Deezer, 4. fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

from tourdesk.core.text import normalize_variants
from tourdesk.services.media import ImageError, image_dimensions, save_artist_image
from tourdesk_crawler.extract.html import page_info, parse_html
from tourdesk_crawler.http.client import PoliteHttpClient
from tourdesk_crawler.http.errors import CrawlError
from tourdesk_crawler.pipeline.models import ArtistSpec

log = logging.getLogger("tourdesk.crawler")
MIN_SIZE = 200
MAX_IMAGE_BYTES = 8 * 1024 * 1024


@dataclass
class FoundImage:
    data: bytes
    source: str  # official | wikimedia | deezer
    source_url: str


def _download(http: PoliteHttpClient, url: str, *, api: bool = False) -> bytes | None:
    try:
        res = http.fetch(url, api=api, use_cache=False, accept="image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8", max_bytes=MAX_IMAGE_BYTES)
    except CrawlError as exc:
        log.info("image download failed %s: %s", url, exc)
        return None
    if not (res.content_type or "").lower().startswith("image/"):
        return None
    dims = image_dimensions(res.content)
    if dims is None or min(dims) < MIN_SIZE:
        return None
    return res.content


def from_official_site(http: PoliteHttpClient, artist: ArtistSpec) -> FoundImage | None:
    if not artist.official_website:
        return None
    try:
        page = http.fetch(artist.official_website)
    except CrawlError:
        return None
    info = page_info(parse_html(page.text), page.final_url)
    if not info.og_image:
        return None
    data = _download(http, info.og_image)
    return FoundImage(data, "official", info.og_image) if data else None


def from_wikidata(http: PoliteHttpClient, artist: ArtistSpec) -> FoundImage | None:
    qid = (artist.external_ids or {}).get("wikidata")
    if not qid:
        return None
    try:
        data = http.fetch_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json", api=True, min_interval=1.0)
    except CrawlError:
        return None
    entity = (data.get("entities") or {}).get(qid) or {}
    claims = (entity.get("claims") or {}).get("P18") or []
    if not claims:
        return None
    filename = ((claims[0].get("mainsnak") or {}).get("datavalue") or {}).get("value")
    if not filename:
        return None
    url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(filename.replace(' ', '_'))}?width=960"
    img = _download(http, url, api=True)
    if img is None:
        return None
    return FoundImage(img, "wikimedia", f"https://commons.wikimedia.org/wiki/File:{quote(filename.replace(' ', '_'))}")


def from_deezer(http: PoliteHttpClient, artist: ArtistSpec) -> FoundImage | None:
    try:
        data = http.fetch_json("https://api.deezer.com/search/artist", params={"q": artist.name, "limit": 5}, api=True, min_interval=1.0)
    except CrawlError:
        return None
    wanted: set[str] = set()
    for n in artist.all_names:
        wanted |= normalize_variants(n)
    for hit in data.get("data") or []:
        if normalize_variants(hit.get("name") or "") & wanted:
            url = hit.get("picture_xl") or hit.get("picture_big")
            if not url or "/artist//" in url:  # deezer placeholder
                continue
            img = _download(http, url, api=True)
            if img:
                return FoundImage(img, "deezer", hit.get("link") or url)
    return None


STRATEGIES = {"official": from_official_site, "wikidata": from_wikidata, "deezer": from_deezer}


def find_and_store_image(http: PoliteHttpClient, artist: ArtistSpec, order: list[str]) -> FoundImage | None:
    for key in order:
        strategy = STRATEGIES.get(key)
        if strategy is None:
            continue
        found = strategy(http, artist)
        if found is None:
            continue
        try:
            save_artist_image(artist.id, found.data)
        except ImageError:
            continue
        return found
    return None
