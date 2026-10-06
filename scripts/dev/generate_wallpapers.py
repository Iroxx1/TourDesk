#!/usr/bin/env python3
"""Generate the TourDesk desktop wallpapers (procedural, no external assets).

    pip install numpy pillow
    python scripts/dev/generate_wallpapers.py

Writes ``frontend/public/wallpapers/<key>.webp`` (2560x1440) and ``<key>-thumb.webp``.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend" / "public" / "wallpapers"
W, H = 2560, 1440


# ----------------------------------------------------------------------------------- helpers
def hexcol(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)], dtype=np.float32)


def grid(w: int = W, h: int = H) -> tuple[np.ndarray, np.ndarray]:
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return x / (w - 1), y / (h - 1)


def ramp(t: np.ndarray, stops: list[tuple[float, str]]) -> np.ndarray:
    """Map scalar field t (0..1) to colours by stops."""
    t = np.clip(t, 0, 1)
    out = np.zeros(t.shape + (3,), dtype=np.float32)
    pos = [p for p, _ in stops]
    cols = [hexcol(c) for _, c in stops]
    for c in range(3):
        out[..., c] = np.interp(t, pos, [col[c] for col in cols])
    return out


def smooth_noise(w: int, h: int, scale: int, octaves: int = 4, seed: int = 0, persistence: float = 0.5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    total = np.zeros((h, w), dtype=np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        cells = max(2, int(scale * 2**o))
        small = rng.random((max(2, int(cells * h / w)), cells)).astype(np.float32)
        img = Image.fromarray((small * 255).astype(np.uint8), "L").resize((w, h), Image.Resampling.BICUBIC)
        total += amp * (np.asarray(img, dtype=np.float32) / 255)
        norm += amp
        amp *= persistence
    return total / norm


def to_img(arr: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def from_img(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGB"), dtype=np.float32) / 255


def blur(arr: np.ndarray, radius: float) -> np.ndarray:
    """Fast large blur: downscale, gaussian, upscale."""
    if radius <= 0:
        return arr
    h, w = arr.shape[:2]
    k = max(1, int(radius / 6))
    small = to_img(arr).resize((max(1, w // k), max(1, h // k)), Image.Resampling.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(radius / k))
    return from_img(small.resize((w, h), Image.Resampling.BICUBIC))


def blur_mask(mask: np.ndarray, radius: float) -> np.ndarray:
    h, w = mask.shape
    k = max(1, int(radius / 6))
    img = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8), "L")
    small = img.resize((max(1, w // k), max(1, h // k)), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(max(0.5, radius / k)))
    return np.asarray(small.resize((w, h), Image.Resampling.BICUBIC), dtype=np.float32) / 255


def mask_from(draw_fn, w: int = W, h: int = H, ss: int = 2) -> np.ndarray:
    """Anti-aliased mask: draw at ss-times resolution with ImageDraw, downscale."""
    img = Image.new("L", (w * ss, h * ss), 0)
    draw_fn(ImageDraw.Draw(img), ss)
    img = img.resize((w, h), Image.Resampling.LANCZOS)
    return np.asarray(img, dtype=np.float32) / 255


def over(base: np.ndarray, color: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    a = alpha[..., None]
    return base * (1 - a) + color * a


def screen(base: np.ndarray, layer: np.ndarray) -> np.ndarray:
    return 1 - (1 - base) * (1 - layer)


def finish(arr: np.ndarray, seed: int = 0, grain: float = 0.012) -> Image.Image:
    rng = np.random.default_rng(seed + 999)
    noise = (rng.random(arr.shape[:2], dtype=np.float32) - 0.5)[..., None] * grain
    return to_img(arr + noise)


def bezier(points: list[tuple[float, float]], n: int = 200) -> list[tuple[float, float]]:
    pts = np.array(points, dtype=np.float64)
    out = []
    for t in np.linspace(0, 1, n):
        p = pts.copy()
        while len(p) > 1:
            p = (1 - t) * p[:-1] + t * p[1:]
        out.append((p[0][0], p[0][1]))
    return out


# ----------------------------------------------------------------------------------- wallpapers
def bloom(seed: int = 1, light: bool = False) -> Image.Image:
    x, y = grid()
    if light:
        bg = ramp(y * 0.7 + x * 0.3, [(0, "#eaf2fc"), (0.6, "#dbe7f7"), (1, "#c9daf2")])
        petal_cols = [("#ffffff", "#9cc7f5"), ("#e8f1ff", "#5d9be8"), ("#f6f9ff", "#7fb0ee"), ("#ffffff", "#b5d3f7")]
    else:
        bg = ramp(np.hypot(x - 0.55, (y - 0.5) * 0.6) * 1.6, [(0, "#123a8c"), (0.5, "#081d52"), (1, "#030a1f")])
        petal_cols = [("#7fd0ff", "#0b3ea8"), ("#4ea7ff", "#06236b"), ("#a7e3ff", "#1450c4"), ("#2f86f0", "#041a54")]
    img = bg.copy()
    cx, cy = W * 0.56, H * 0.52
    rng = np.random.default_rng(seed)
    angles = [-150, -105, -60, -20, 20, 60, 105, 150, 190, 235]
    for i, ang in enumerate(angles):
        a = math.radians(ang + rng.uniform(-6, 6))
        length = H * rng.uniform(0.55, 0.72)
        width = length * rng.uniform(0.28, 0.36)
        tip = (cx + math.cos(a) * length, cy + math.sin(a) * length)
        nx, ny = -math.sin(a), math.cos(a)
        c1 = (cx + math.cos(a) * length * 0.35 + nx * width, cy + math.sin(a) * length * 0.35 + ny * width)
        c2 = (cx + math.cos(a) * length * 0.35 - nx * width, cy + math.sin(a) * length * 0.35 - ny * width)
        left = bezier([(cx, cy), c1, (tip[0] + nx * width * 0.25, tip[1] + ny * width * 0.25), tip], 120)
        right = bezier([tip, (tip[0] - nx * width * 0.25, tip[1] - ny * width * 0.25), c2, (cx, cy)], 120)
        poly = left + right

        def draw(d, ss, poly=poly):
            d.polygon([(px * ss, py * ss) for px, py in poly], fill=255)

        m = mask_from(draw)
        m = blur_mask(m, 6) * (0.78 if not light else 0.7)
        # gradient along the petal axis
        t = ((x * W - cx) * math.cos(a) + (y * H - cy) * math.sin(a)) / length
        inner, outer = petal_cols[i % len(petal_cols)]
        col = ramp(t, [(0, outer), (0.5, inner), (1, outer)])
        # soft edge highlight
        img = over(img, col, m)
    glow_mask = np.exp(-(((x * W - cx) / (W * 0.18)) ** 2 + ((y * H - cy) / (H * 0.25)) ** 2))
    glow = hexcol("#ffffff" if light else "#9fdcff")
    img = screen(img, glow * glow_mask[..., None] * (0.35 if not light else 0.5))
    img = img * (1 - 0.25 * smooth_noise(W, H, 3, 2, seed)[..., None] * (0 if light else 1))
    return finish(img, seed)


def nightfall(seed: int = 2) -> Image.Image:
    x, y = grid()
    horizon = 0.58
    sky = ramp(y / horizon, [(0, "#05030f"), (0.55, "#1a0b3d"), (0.85, "#5a1a6e"), (1, "#ff4fa3")])
    floor = ramp((y - horizon) / (1 - horizon), [(0, "#2a0a3c"), (0.3, "#0d0420"), (1, "#020108")])
    img = np.where((y < horizon)[..., None], sky, floor)
    # sun with stripes
    cxs, cys, r = W * 0.5, H * horizon - H * 0.02, H * 0.2
    d = np.hypot(x * W - cxs, y * H - cys)
    sun_mask = np.clip(r - d, 0, 1.5) / 1.5
    stripes = ((y * H - (cys - r)) / (2 * r))
    gaps = np.sin(stripes * math.pi * 14) > (1.2 - stripes * 1.8)
    sun_mask = sun_mask * (~gaps | (stripes < 0.45)) * (y < horizon)
    sun = ramp(stripes, [(0, "#ffe66d"), (0.5, "#ff8a5c"), (1, "#ff3d8b")])
    img = over(img, sun, sun_mask.astype(np.float32))
    img = screen(img, hexcol("#ff3d8b") * (np.exp(-((d / (r * 2.2)) ** 2)) * 0.45)[..., None])
    # grid
    lines = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(lines)
    hy = H * horizon
    for i in range(-30, 31):
        x0 = W / 2 + i * 26
        x1 = W / 2 + i * 260
        dr.line([(x0, hy), (x1, H)], fill=255, width=2)
    k = 1.0
    yy = hy + 4
    while yy < H:
        dr.line([(0, yy), (W, yy)], fill=255, width=2)
        k *= 1.18
        yy += 6 * k
    lm = np.asarray(lines, dtype=np.float32) / 255
    lm = lm * np.clip((y - horizon) * 6, 0, 1)
    col = ramp((y - horizon) / (1 - horizon), [(0, "#ff5fd2"), (0.5, "#7a5cff"), (1, "#34e1ff")])
    glow = blur_mask(lm, 10)
    img = screen(img, col * (glow * 0.9)[..., None])
    img = over(img, col, lm * 0.9)
    # stars
    rng = np.random.default_rng(seed)
    stars = np.zeros((H, W), dtype=np.float32)
    n = 900
    sx, sy = rng.integers(0, W, n), rng.integers(0, int(H * horizon * 0.85), n)
    stars[sy, sx] = rng.random(n) ** 3
    img = screen(img, np.repeat(blur_mask(stars, 1.2)[..., None] * 1.2, 3, axis=2))
    # haze at horizon
    haze = np.exp(-(((y - horizon) / 0.035) ** 2))
    img = screen(img, hexcol("#ff6fb5") * (haze * 0.5)[..., None])
    return finish(img, seed)


def glass(seed: int = 3) -> Image.Image:
    x, y = grid()
    n = smooth_noise(W, H, 1.2, 2, seed)
    bg = ramp(x * 0.6 + y * 0.25 + n * 0.3, [(0, "#f6d5f7"), (0.35, "#d7e3fc"), (0.7, "#bfe6f3"), (1, "#fde7d4")])
    # blurred colour blobs behind the glass
    img = bg.copy()
    rng = np.random.default_rng(seed)
    for col, (bx, by, br) in zip(["#ff9ad5", "#7cb6ff", "#8ef0d1", "#ffc58a"], [(0.25, 0.3, 0.22), (0.7, 0.35, 0.25), (0.55, 0.78, 0.2), (0.12, 0.8, 0.16)], strict=True):
        m = np.exp(-(((x - bx) * W / (br * W)) ** 2 + ((y - by) * H / (br * W)) ** 2))
        img = over(img, hexcol(col), m * 0.55)
    blurred = blur(img, 60)
    panels = [(0.18, 0.2, 0.46, 0.62, 60), (0.5, 0.12, 0.84, 0.48, 70), (0.42, 0.55, 0.78, 0.9, 64), (0.08, 0.66, 0.3, 0.92, 48)]
    for px0, py0, px1, py1, rad in panels:
        def draw(d, ss, b=(px0, py0, px1, py1, rad)):
            d.rounded_rectangle([b[0] * W * ss, b[1] * H * ss, b[2] * W * ss, b[3] * H * ss], radius=b[4] * ss, fill=255)

        m = mask_from(draw)
        shadow = blur_mask(np.roll(m, 24, axis=0), 40) * 0.18
        img = img * (1 - shadow[..., None])
        frosted = blurred * 0.75 + 0.25
        img = over(img, frosted, m * 0.85)
        edge = np.clip(m - blur_mask(m, 3) * 0.9, 0, 1)
        img = screen(img, np.repeat((edge * 0.8)[..., None], 3, axis=2))
        sheen = np.clip(1 - (y - py0) / max(0.01, py1 - py0), 0, 1) ** 3 * m * 0.18
        img = screen(img, np.repeat(sheen[..., None], 3, axis=2))
    _ = rng
    return finish(img, seed, grain=0.008)


def stage(seed: int = 4) -> Image.Image:
    x, y = grid()
    img = ramp(y, [(0, "#05040b"), (0.6, "#0b0820"), (1, "#14082b")])
    rng = np.random.default_rng(seed)
    beams = [(0.2, "#7a5cff"), (0.35, "#ff3db5"), (0.5, "#4fd2ff"), (0.65, "#ffb347"), (0.8, "#7a5cff")]
    haze = smooth_noise(W, H, 2, 4, seed)
    for i, (bx, col) in enumerate(beams):
        ox, oy = bx * W, -40
        target_x = W * (0.5 + (bx - 0.5) * 0.35) + rng.uniform(-120, 120)
        target_y = H * 0.78
        spread = 160 + i * 10

        def draw(d, ss, ox=ox, oy=oy, tx=target_x, ty=target_y, sp=spread):
            d.polygon([(ox * ss, oy * ss), ((tx - sp) * ss, ty * ss), ((tx + sp) * ss, ty * ss)], fill=255)

        m = blur_mask(mask_from(draw), 30)
        fade = np.clip(1 - y / 0.9, 0, 1) ** 0.6
        intensity = m * (0.35 + 0.65 * haze) * fade * 0.85
        img = screen(img, hexcol(col) * intensity[..., None])
        # lamp
        lamp = np.exp(-(((x * W - ox) / 40) ** 2 + ((y * H - 10) / 30) ** 2))
        img = screen(img, np.repeat(lamp[..., None], 3, axis=2))
    # stage glow
    stage_glow = np.exp(-(((y - 0.78) / 0.06) ** 2)) * np.exp(-(((x - 0.5) / 0.45) ** 2))
    img = screen(img, hexcol("#ff9be0") * (stage_glow * 0.7)[..., None])
    # crowd silhouettes
    crowd = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(crowd)
    base = H * 0.86
    xpos = -40
    while xpos < W + 40:
        hw = rng.uniform(26, 40)
        top = base - rng.uniform(40, 110)
        d.ellipse([xpos - hw * 0.55, top - hw * 0.9, xpos + hw * 0.55, top + hw * 0.2], fill=255)
        d.rounded_rectangle([xpos - hw * 1.2, top + hw * 0.05, xpos + hw * 1.2, H + 10], radius=int(hw), fill=255)
        if rng.random() < 0.18:
            side = rng.choice([-1, 1])
            ax = xpos + side * hw * 0.9
            d.line([(ax, top + hw * 0.3), (ax + side * rng.uniform(10, 50), top - rng.uniform(90, 170))], fill=255, width=int(hw * 0.45))
        xpos += hw * rng.uniform(1.3, 1.9)
    cm = np.asarray(crowd.filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32) / 255
    img = over(img, hexcol("#030207"), cm)
    rim = np.clip(cm - blur_mask(cm, 4), 0, 1) * (y < 0.9)
    img = screen(img, hexcol("#ff7ad9") * (rim * 0.5)[..., None])
    return finish(img, seed, grain=0.02)


def neon(seed: int = 5) -> Image.Image:
    x, y = grid()
    img = ramp(np.hypot(x - 0.5, y - 0.55), [(0, "#120a24"), (0.6, "#07050f"), (1, "#020205")])
    colors = ["#ff2bd6", "#20e3ff", "#8b5cff", "#ff8a3d", "#22ffa8"]
    rng = np.random.default_rng(seed)
    for i in range(7):
        col = hexcol(colors[i % len(colors)])
        lines = Image.new("L", (W * 2, H * 2), 0)
        d = ImageDraw.Draw(lines)
        amp = rng.uniform(0.08, 0.22) * H
        freq = rng.uniform(0.6, 1.4)
        phase = rng.uniform(0, math.tau)
        yc = H * rng.uniform(0.25, 0.8)
        pts = []
        for xx in np.linspace(-0.1, 1.1, 400):
            yy = yc + amp * math.sin(xx * math.tau * freq + phase) + amp * 0.35 * math.sin(xx * math.tau * freq * 2.3 + phase * 1.7)
            pts.append((xx * W * 2, yy * 2))
        d.line(pts, fill=255, width=int(rng.uniform(5, 9) * 2), joint="curve")
        m = np.asarray(lines.resize((W, H), Image.Resampling.LANCZOS), dtype=np.float32) / 255
        core = np.repeat(m[..., None], 3, axis=2) * (0.6 + 0.4 * col)
        glow1 = blur_mask(m, 12)
        glow2 = blur_mask(m, 48)
        img = screen(img, col * (glow2 * 0.55)[..., None])
        img = screen(img, col * (glow1 * 0.9)[..., None])
        img = screen(img, core)
    reflection = np.exp(-(((y - 0.9) / 0.12) ** 2)) * 0.1
    img = screen(img, hexcol("#8b5cff") * reflection[..., None])
    return finish(img, seed, grain=0.016)


def ridge(width: int, base: float, amp: float, seed: int, scale: float = 6, octaves: int = 6) -> np.ndarray:
    rng = np.random.default_rng(seed)
    xs = np.linspace(0, 1, width)
    total = np.zeros(width)
    a, f, norm = 1.0, scale, 0.0
    for _ in range(octaves):
        knots = rng.random(int(f) + 3)
        total += a * np.interp(xs * (len(knots) - 3) + 1, np.arange(len(knots)), knots)
        norm += a
        a *= 0.5
        f *= 2
    total /= norm
    return base - amp * (total - 0.3)


def alps(seed: int = 6) -> Image.Image:
    x, y = grid()
    img = ramp(y, [(0, "#0b1a3d"), (0.35, "#284a8c"), (0.55, "#e0866f"), (0.62, "#ffcf8f")])
    sun = np.exp(-(((x - 0.68) * W / 70) ** 2 + ((y - 0.5) * H / 70) ** 2))
    img = screen(img, hexcol("#fff2c9") * np.clip(sun * 1.5, 0, 1)[..., None])
    img = screen(img, hexcol("#ffb36b") * (np.exp(-(((x - 0.68) / 0.3) ** 2 + ((y - 0.52) / 0.15) ** 2)) * 0.5)[..., None])
    water = 0.68
    layers = [(0.5, 0.18, "#6d7fb8", 4), (0.56, 0.16, "#4d5d93", 5), (0.62, 0.12, "#2c3866", 7), (0.67, 0.08, "#151c3b", 9)]
    rows = np.arange(H)[:, None] / (H - 1)
    for i, (b, a, col, sc) in enumerate(layers):
        top = ridge(W, b, a, seed + i, scale=sc)
        m = (rows >= top[None, :]) & (rows <= water)
        m = blur_mask(m.astype(np.float32), 1.2)
        img = over(img, hexcol(col), m)
    # lake reflection
    above = img[int(H * water) - (H - int(H * water)) : int(H * water)][::-1]
    if above.shape[0] == H - int(H * water):
        refl = blur(above, 6) * 0.65 + hexcol("#0b1430") * 0.35
        ripple = (np.sin(np.arange(refl.shape[0])[:, None] * 0.35) * 0.04 + 1)
        img[int(H * water) :] = refl * ripple[..., None]
    shore = np.exp(-(((y - water) / 0.004) ** 2))
    img = screen(img, hexcol("#ffcf8f") * (shore * 0.4)[..., None])
    return finish(img, seed)


def skyline(seed: int = 7) -> Image.Image:
    x, y = grid()
    img = ramp(y, [(0, "#040714"), (0.5, "#0f1a40"), (0.66, "#3b2a6b"), (0.72, "#7d3f7a")])
    rng = np.random.default_rng(seed)
    stars = np.zeros((H, W), dtype=np.float32)
    n = 700
    stars[rng.integers(0, int(H * 0.5), n), rng.integers(0, W, n)] = rng.random(n) ** 2
    img = screen(img, np.repeat(blur_mask(stars, 1.0)[..., None] * 1.3, 3, axis=2))
    moon = np.exp(-(((x - 0.82) * W / 46) ** 2 + ((y - 0.16) * H / 46) ** 2) * 3)
    img = screen(img, hexcol("#f3f0ff") * np.clip(moon * 1.4, 0, 1)[..., None])
    img = screen(img, hexcol("#8d86ff") * (np.exp(-(((x - 0.82) / 0.12) ** 2 + ((y - 0.16) / 0.2) ** 2)) * 0.25)[..., None])
    water = int(H * 0.8)
    city = np.zeros((H, W, 3), dtype=np.float32)
    cmask = np.zeros((H, W), dtype=np.float32)
    for layer, (shade, hmin, hmax) in enumerate([("#101433", 0.15, 0.35), ("#070915", 0.1, 0.45)]):
        xpos = 0
        while xpos < W:
            bw = int(rng.uniform(40, 130))
            bh = int(H * rng.uniform(hmin, hmax) * (0.6 if layer == 0 else 1))
            top = water - bh
            cmask[top:water, xpos : xpos + bw] = 1
            city[top:water, xpos : xpos + bw] = hexcol(shade)
            if rng.random() < 0.15:
                sx = xpos + bw // 2
                city[top - 60 : top, sx - 2 : sx + 2] = hexcol(shade)
                cmask[top - 60 : top, sx - 2 : sx + 2] = 1
            if layer == 1:
                for wy in range(top + 12, water - 10, 18):
                    for wx in range(xpos + 8, xpos + bw - 8, 14):
                        if rng.random() < 0.32:
                            c = rng.choice(["#ffd27a", "#ffe9b0", "#9fd8ff"], p=[0.6, 0.3, 0.1])
                            city[wy : wy + 8, wx : wx + 6] = hexcol(c) * rng.uniform(0.6, 1.0)
            xpos += bw + int(rng.uniform(2, 14))
    img = over(img, city, cmask)
    lit = np.clip(city.max(axis=2) - 0.3, 0, 1) * cmask
    img = screen(img, hexcol("#ffcf7a") * (blur_mask(lit, 6) * 0.5)[..., None])
    glow = np.exp(-(((y - 0.78) / 0.08) ** 2))
    img = screen(img, hexcol("#ff7aa8") * (glow * 0.25)[..., None])
    refl_src = img[water - (H - water) : water][::-1]
    refl = blur(refl_src, 4)
    rows = np.arange(H - water)[:, None]
    shift = (np.sin(rows * 0.6) * 6).astype(int)
    refl = np.stack([np.roll(refl[r], shift[r, 0], axis=0) for r in range(refl.shape[0])])
    img[water:] = refl * 0.55 + hexcol("#04060f") * 0.45
    return finish(img, seed, grain=0.016)


def nebula(seed: int = 8) -> Image.Image:
    x, y = grid()
    img = np.zeros((H, W, 3), dtype=np.float32) + hexcol("#02030a")
    n1 = smooth_noise(W, H, 2.2, 6, seed)
    n2 = smooth_noise(W, H, 3.5, 6, seed + 1)
    shape = np.exp(-(((x - 0.45) / 0.45) ** 2 + ((y - 0.5) / 0.32) ** 2)) * 1.3
    dens1 = np.clip((n1 - 0.42) * 2.6, 0, 1) ** 1.6 * shape
    dens2 = np.clip((n2 - 0.45) * 2.8, 0, 1) ** 1.8 * shape
    img = screen(img, ramp(n2, [(0, "#3a0d6b"), (0.5, "#c2268f"), (1, "#ff8a6b")]) * dens1[..., None])
    img = screen(img, ramp(n1, [(0, "#0d2b6b"), (0.6, "#1f8fd6"), (1, "#7ff0ff")]) * (dens2 * 0.9)[..., None])
    rng = np.random.default_rng(seed)
    stars = np.zeros((H, W), dtype=np.float32)
    n = 4000
    stars[rng.integers(0, H, n), rng.integers(0, W, n)] = rng.random(n) ** 4
    img = screen(img, np.repeat((blur_mask(stars, 0.8) * 1.6)[..., None], 3, axis=2))
    big = np.zeros((H, W), dtype=np.float32)
    for _ in range(26):
        big[rng.integers(0, H), rng.integers(0, W)] = 1
    img = screen(img, hexcol("#cfe6ff") * (blur_mask(big, 8) * 3)[..., None])
    # planet
    px, py, pr = 0.8, 0.72, 0.16
    d = np.hypot((x - px) * W, (y - py) * H) / (pr * H)
    planet = np.clip((1 - d) * 60, 0, 1)
    light = np.clip(1 - np.hypot((x - px + 0.05) * W, (y - py + 0.05) * H) / (pr * H * 1.6), 0, 1)
    pcol = ramp(light, [(0, "#05060f"), (0.5, "#2a3f8f"), (1, "#9ed2ff")])
    img = over(img, pcol, planet)
    atmo = np.exp(-((d - 1) / 0.05) ** 2) * (d > 0.9)
    img = screen(img, hexcol("#6fb7ff") * (atmo * 0.6)[..., None])
    return finish(img, seed, grain=0.014)


def geometry(seed: int = 9) -> Image.Image:
    rng = np.random.default_rng(seed)
    cols, rows = 22, 13
    pts = np.zeros((rows + 1, cols + 1, 2))
    for r in range(rows + 1):
        for c in range(cols + 1):
            jx = rng.uniform(-0.35, 0.35) if 0 < c < cols else 0
            jy = rng.uniform(-0.35, 0.35) if 0 < r < rows else 0
            pts[r, c] = ((c + jx) / cols * W, (r + jy) / rows * H)
    img = Image.new("RGB", (W * 2, H * 2))
    d = ImageDraw.Draw(img)
    field = smooth_noise(cols + 1, rows + 1, 1.5, 3, seed)
    for r in range(rows):
        for c in range(cols):
            a, b, cc, dd = pts[r, c], pts[r, c + 1], pts[r + 1, c + 1], pts[r + 1, c]
            for tri in ((a, b, cc), (a, cc, dd)) if (r + c) % 2 == 0 else ((a, b, dd), (b, cc, dd)):
                cx = sum(p[0] for p in tri) / 3 / W
                cy = sum(p[1] for p in tri) / 3 / H
                t = 0.55 * (1 - cy) * 0.5 + field[min(rows, int(cy * rows)), min(cols, int(cx * cols))] * 0.5 + rng.uniform(-0.06, 0.06)
                accent = math.exp(-(((cx - 0.7) / 0.18) ** 2 + ((cy - 0.35) / 0.25) ** 2))
                col = ramp(np.array([t]), [(0, "#0a0e18"), (0.45, "#1b2440"), (0.8, "#2f3e66"), (1, "#40548a")])[0]
                accent2 = math.exp(-(((cx - 0.22) / 0.16) ** 2 + ((cy - 0.78) / 0.2) ** 2))
                col = col * (1 - accent * 0.7) + hexcol("#4a5cff") * accent * 0.7
                col = col * (1 - accent2 * 0.55) + hexcol("#c03fd6") * accent2 * 0.55
                d.polygon([(p[0] * 2, p[1] * 2) for p in tri], fill=tuple(int(v * 255) for v in col))
                edge = tuple(min(255, int(v * 255 * 1.35 + 18)) for v in col)
                d.line([(p[0] * 2, p[1] * 2) for p in (*tri, tri[0])], fill=edge, width=3)
    arr = from_img(img.resize((W, H), Image.Resampling.LANCZOS))
    x, y = grid()
    glow = np.exp(-(((x - 0.7) / 0.25) ** 2 + ((y - 0.35) / 0.3) ** 2))
    arr = screen(arr, hexcol("#4f6bff") * (glow * 0.18)[..., None])
    vign = 1 - 0.3 * np.clip(np.hypot(x - 0.5, y - 0.5) * 1.3, 0, 1) ** 2
    return finish(arr * vign[..., None], seed)


def daylight(seed: int = 10) -> Image.Image:
    return bloom(seed, light=True)


def aurora(seed: int = 11) -> Image.Image:
    x, y = grid()
    img = ramp(y, [(0, "#020814"), (0.5, "#06223a"), (0.75, "#0c3a4d")])
    n = smooth_noise(W, H, 4, 4, seed)
    for i, (col, yc, amp) in enumerate([("#2dffb3", 0.32, 0.08), ("#5ad1ff", 0.25, 0.06), ("#b066ff", 0.2, 0.05)]):
        curve = yc + amp * np.sin(x * math.tau * (1.2 + i * 0.4) + i) + 0.04 * (n - 0.5)
        band = np.exp(-(((y - curve) / 0.035) ** 2))
        rays = np.clip(1 - (curve - y) / 0.25, 0, 1) * (y < curve) * (0.5 + 0.5 * smooth_noise(W, H, 40, 2, seed + i))
        intensity = np.clip(band * 0.9 + rays * 0.55, 0, 1) * (0.7 - i * 0.12)
        img = screen(img, hexcol(col) * intensity[..., None])
    rng = np.random.default_rng(seed)
    stars = np.zeros((H, W), dtype=np.float32)
    k = 1600
    stars[rng.integers(0, int(H * 0.7), k), rng.integers(0, W, k)] = rng.random(k) ** 3
    img = screen(img, np.repeat((blur_mask(stars, 0.9) * 1.2)[..., None], 3, axis=2))
    water = 0.74
    rows = np.arange(H)[:, None] / (H - 1)
    for i, (b, a, col) in enumerate([(0.68, 0.12, "#071a26"), (0.72, 0.08, "#030b12")]):
        top = ridge(W, b, a, seed + 10 + i, scale=5)
        m = ((rows >= top[None, :]) & (rows <= water)).astype(np.float32)
        img = over(img, hexcol(col), blur_mask(m, 1.2))
    wy = int(H * water)
    refl = blur(img[wy - (H - wy) : wy][::-1], 5)
    img[wy:] = refl * 0.5 + hexcol("#01060b") * 0.5
    return finish(img, seed)


def sunset(seed: int = 12) -> Image.Image:
    x, y = grid()
    img = ramp(y * 0.8 + x * 0.2, [(0, "#ffe3c4"), (0.4, "#ffb4a2"), (0.75, "#e57a9a"), (1, "#7b4a9e")])
    bands = [("#fff1e0", 0.42, 0.05, 1.1), ("#ffc6a8", 0.5, 0.06, 0.9), ("#ff9a9e", 0.6, 0.07, 1.3), ("#d9739f", 0.7, 0.06, 0.8),
             ("#a65ba6", 0.8, 0.05, 1.2), ("#6b4296", 0.9, 0.04, 1.0)]
    rng = np.random.default_rng(seed)
    for col, base, amp, freq in bands:
        phase = rng.uniform(0, math.tau)
        curve = base + amp * np.sin(x * math.tau * freq + phase) + amp * 0.4 * np.sin(x * math.tau * freq * 2.7 + phase * 2)
        m = blur_mask((y >= curve).astype(np.float32), 2)
        shadow = blur_mask(np.clip((y >= curve - 0.012).astype(np.float32) - m, 0, 1), 18) * 0.25
        img = img * (1 - shadow[..., None])
        shade = ramp(np.clip((y - curve) * 3, 0, 1), [(0, col), (1, col)]) * (1 - 0.12 * np.clip((y - curve) * 4, 0, 1)[..., None])
        img = over(img, shade, m)
    sun = np.exp(-(((x - 0.3) * W / 120) ** 2 + ((y - 0.28) * H / 120) ** 2))
    img = screen(img, hexcol("#fff6e8") * np.clip(sun * 1.3, 0, 1)[..., None] * 0.9)
    return finish(img, seed, grain=0.008)


WALLPAPERS = {
    "bloom": bloom, "nightfall": nightfall, "glass": glass, "stage": stage, "neon": neon, "alps": alps,
    "skyline": skyline, "nebula": nebula, "geometry": geometry, "daylight": daylight, "aurora": aurora, "sunset": sunset,
}


def main(argv: list[str]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    keys = argv or list(WALLPAPERS)
    for key in keys:
        img = WALLPAPERS[key]()
        img.save(OUT / f"{key}.webp", "WEBP", quality=82, method=6)
        img.resize((384, 216), Image.Resampling.LANCZOS).save(OUT / f"{key}-thumb.webp", "WEBP", quality=80)
        print(f"{key}: {(OUT / f'{key}.webp').stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
