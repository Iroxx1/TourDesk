"""Image processing and the local media cache (avatars, artist images)."""

from __future__ import annotations

import hashlib
import io
import shutil
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from tourdesk.core.config import get_settings

Image.MAX_IMAGE_PIXELS = 40_000_000
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ARTIST_SIZES = {"thumb": 96, "tile": 400, "hero": 960}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "MPO"}


class ImageError(ValueError):
    pass


def media_root() -> Path:
    root = get_settings().media_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _open(data: bytes) -> Image.Image:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError("Bild ist zu groß (max. 8 MB)")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ALLOWED_FORMATS:
            raise ImageError("Nicht unterstütztes Bildformat")
        if img.width * img.height > Image.MAX_IMAGE_PIXELS:
            raise ImageError("Bildauflösung ist zu groß")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageError("Datei ist kein gültiges Bild") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    return img


def _square(img: Image.Image, size: int) -> Image.Image:
    return ImageOps.fit(img, (size, size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))


def _encode_webp(img: Image.Image, quality: int = 84) -> bytes:
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=quality, method=5)
    return out.getvalue()


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    try:
        with Image.open(io.BytesIO(data)) as img:
            return img.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return None


def save_avatar(user_id: int, data: bytes) -> str:
    img = _open(data)
    path = media_root() / "avatars" / f"{user_id}.webp"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_encode_webp(_square(img, 256)))
    return f"avatars/{user_id}.webp"


def delete_avatar(user_id: int) -> None:
    (media_root() / "avatars" / f"{user_id}.webp").unlink(missing_ok=True)


def save_artist_image(artist_id: int, data: bytes) -> str:
    """Store an artist image in all sizes. Returns the relative directory."""
    img = _open(data)
    base = media_root() / "artists" / str(artist_id)
    base.mkdir(parents=True, exist_ok=True)
    for old in base.glob("*"):
        old.unlink(missing_ok=True)
    for name, size in ARTIST_SIZES.items():
        (base / f"{name}.webp").write_bytes(_encode_webp(_square(img, size), quality=86 if size > 200 else 80))
    return f"artists/{artist_id}"


def delete_artist_images(artist_id: int) -> None:
    shutil.rmtree(media_root() / "artists" / str(artist_id), ignore_errors=True)


_FALLBACK_GRADIENTS = [
    ("#0f6cbd", "#6b3fd4"),
    ("#c239b3", "#5b2fd6"),
    ("#e3008c", "#f7630c"),
    ("#0099bc", "#10893e"),
    ("#ca5010", "#e81123"),
    ("#4f46e5", "#06b6d4"),
    ("#7a7574", "#2d7d9a"),
    ("#8e562e", "#c239b3"),
]


def _initials(name: str) -> str:
    words = [w for w in name.replace("&", " ").split() if w[:1].isalnum()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def save_fallback_artist_image(artist_id: int, name: str) -> str:
    """Generated SVG placeholder (gradient + initials)."""
    digest = int(hashlib.sha1(name.encode(), usedforsecurity=False).hexdigest(), 16)
    c1, c2 = _FALLBACK_GRADIENTS[digest % len(_FALLBACK_GRADIENTS)]
    initials = _initials(name).replace("&", "&amp;").replace("<", "").replace(">", "")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient>
<radialGradient id="h" cx="0.25" cy="0.15" r="0.9"><stop offset="0" stop-color="#ffffff" stop-opacity="0.35"/><stop offset="0.6" stop-color="#ffffff" stop-opacity="0"/></radialGradient></defs>
<rect width="400" height="400" fill="url(#g)"/><rect width="400" height="400" fill="url(#h)"/>
<g fill="none" stroke="#ffffff" stroke-opacity="0.18" stroke-width="6"><path d="M40 300 q40 -60 80 0 t80 0 t80 0 t80 0"/><path d="M40 330 q40 -40 80 0 t80 0 t80 0 t80 0"/></g>
<text x="200" y="228" font-family="Segoe UI, Inter, Arial, sans-serif" font-size="132" font-weight="600" fill="#ffffff" text-anchor="middle">{initials}</text>
</svg>"""
    base = media_root() / "artists" / str(artist_id)
    base.mkdir(parents=True, exist_ok=True)
    for old in base.glob("*"):
        old.unlink(missing_ok=True)
    (base / "fallback.svg").write_text(svg, encoding="utf-8")
    return f"artists/{artist_id}"


def artist_image_url(image_path: str | None, image_source: str | None, version: int, size: str = "tile") -> str | None:
    if not image_path:
        return None
    if image_source == "fallback":
        return f"/media/{image_path}/fallback.svg?v={version}"
    return f"/media/{image_path}/{size}.webp?v={version}"


def avatar_url(avatar_path: str | None, version: int) -> str | None:
    if not avatar_path:
        return None
    return f"/media/{avatar_path}?v={version}"


def resolve_media_path(relative: str) -> Path | None:
    """Map a ``/media/...`` path to a file inside the media directory (no traversal)."""
    root = media_root().resolve()
    candidate = (root / relative).resolve()
    if root not in candidate.parents and candidate != root:
        return None
    if not candidate.is_file():
        return None
    return candidate
