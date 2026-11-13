"""Disc styles for the spinning record behind the cover. All are DARK (like real records in the reference videos)
and drawn procedurally (RGBA PNG), nothing is downloaded.

styles:  vinyl  classic black record, cream label (+ optional star stickers)   [default]
         plain  matte black disc, small grey centre
         blue   black record with a deep blue sheen
         wine   black record with a deep red sheen
         cd     black CD: dark mirror with a faint rainbow shimmer
         art    black record that wears the song's cover art as its centre label (one disc per song)
"""
import colorsys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

STYLES = {
    "vinyl": "Classic vinyl (black, cream label)",
    "plain": "Plain black disc",
    "blue": "Black vinyl, blue sheen",
    "wine": "Black vinyl, red sheen",
    "cd": "Black CD (faint rainbow)",
    "art": "Cover art on the disc label",
}
ALIASES = {"picture": "art", "brown": "wine", "gold": "vinyl", "neon": "blue"}     # old names from earlier versions
TINTS = {   # body, sheen colour, label colour
    "vinyl": ([16, 16, 18], [150, 150, 158], None),
    "blue": ([8, 13, 28], [110, 150, 235], [70, 84, 120]),
    "wine": ([22, 8, 11], [225, 110, 120], [96, 50, 56]),
    "art": ([16, 16, 18], [150, 150, 158], None),
}


def _hsv_to_rgb(h, s, v):
    """Vectorised HSV -> RGB (0..1) for numpy arrays."""
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r = np.choose(i, [v, q, p, p, t, v]); g = np.choose(i, [t, v, v, q, p, p]); b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def make_disc(path, diameter=560, style="vinyl", art=None, stars=0, label=(228, 220, 200), ss=2):
    style = ALIASES.get(style, style)
    if style not in STYLES:
        raise ValueError(f"unknown disc style {style!r}; choose from {sorted(STYLES)}")
    d = diameter * ss
    c = d / 2
    rng = np.random.default_rng(11)
    y, x = np.mgrid[0:d, 0:d].astype(np.float32)
    dx, dy = x - c + 0.5, y - c + 0.5
    r = np.hypot(dx, dy) / c                      # 0 centre .. 1 rim
    ang = np.arctan2(dy, dx)
    rings = rng.normal(0, 1, 900).astype(np.float32)
    idx = np.clip(((r - 0.30) / 0.68 * 899), 0, 899).astype(int)
    lobe = np.maximum(0, np.cos(2 * (ang - 0.6))) ** 10        # light on the grooves, fixed while the disc spins
    rim = np.exp(-((r - 0.985) / 0.01) ** 2)[..., None]
    alpha = (r <= 1.0).astype(np.float32) * 255
    marks = []                                                  # small spots so the rotation is visible

    def paper_label(radius, colour, ring=True):
        shade = 1 - 0.18 * (np.hypot(dx - 0.2 * c, dy - 0.25 * c) / c)
        paper = np.array(colour, np.float32)[None, None, :] * shade[..., None] + rng.normal(0, 2.5, (d, d, 1))
        out = np.where((r < radius)[..., None], paper, rgb)
        out = out - (np.abs(r - (radius - 0.005)) < 0.004)[..., None] * 40
        if ring:
            out = out - (np.abs(r - 0.25) < 0.003)[..., None] * 30
        return out

    if style in TINTS:
        tone, sheen, lab = TINTS[style]
        base = np.array(tone, np.float32)[None, None, :] + 5 * rings[idx][..., None] + 3 * np.sin(r * 700)[..., None]
        for gap in (0.52, 0.66, 0.79):
            base = base - 7 * np.exp(-((r - gap) / 0.006) ** 2)[..., None]
        rgb = base + (0.55 * lobe * np.clip((r - 0.34) / 0.2, 0, 1) * (r < 0.985))[..., None] * np.array(sheen, np.float32)
        rgb = rgb + rim * 40
        if style == "art":
            if not art:
                raise ValueError("the 'art' disc needs the song's cover art")
            pic = np.asarray(Image.open(art).convert("RGB").resize((d, d), Image.LANCZOS), np.float32)
            rgb = np.where((r < 0.34)[..., None], pic * 0.95, rgb)
            rgb = rgb - (np.abs(r - 0.335) < 0.005)[..., None] * 50
        else:
            rgb = paper_label(0.34, label if lab is None else lab)
        rgb = np.where((r < 0.028)[..., None], np.array([10, 10, 10], np.float32), rgb)
        marks = [(0.0, 0.20), (3.14159, 0.20)]
    elif style == "plain":
        body = np.array([30, 30, 33], np.float32)
        rgb = body[None, None, :] + 1.5 * rings[idx][..., None] + 1.0 * np.sin(r * 300)[..., None]
        rgb = rgb + (0.30 * lobe * np.clip((r - 0.2) / 0.2, 0, 1) * (r < 0.985))[..., None] * np.array([150, 150, 158], np.float32)
        rgb = rgb + rim * 30
        rgb = np.where((r < 0.2)[..., None], np.array([54, 54, 58], np.float32) + rng.normal(0, 1.5, (d, d, 1)), rgb)
        rgb = rgb - (np.abs(r - 0.2) < 0.004)[..., None] * 25
        rgb = np.where((r < 0.03)[..., None], np.array([12, 12, 12], np.float32), rgb)
        marks = [(0.0, 0.12)]
    else:  # cd: black mirror disc with a faint rainbow shimmer and a dark clear ring
        h = (ang / (2 * np.pi) * 2.0 + r * 2.2) % 1.0
        rainbow = _hsv_to_rgb(h, np.full_like(h, 0.7), np.full_like(h, 0.8)) * 255
        rgb = np.array([13, 13, 17], np.float32)[None, None, :] + 3 * rings[idx][..., None] + 2 * np.sin(r * 420)[..., None]
        shimmer = (0.34 * lobe + 0.06) * np.clip((r - 0.3) / 0.15, 0, 1)
        rgb = rgb + (shimmer * (r < 0.985))[..., None] * (0.45 * rainbow + 0.35 * np.array([160, 160, 170], np.float32))
        rgb = np.where(((r > 0.13) & (r < 0.30))[..., None], 0.7 * rgb + 0.3 * np.array([56, 56, 64], np.float32), rgb)
        rgb = rgb - (np.abs(r - 0.30) < 0.004)[..., None] * 15 + (np.abs(r - 0.13) < 0.004)[..., None] * 25
        rgb = rgb + rim * 35
        alpha = alpha * np.where(r < 0.065, 0, 1)
        marks = [(0.0, 0.44), (3.14159, 0.44)]

    img = Image.fromarray(np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), alpha.astype(np.uint8)]), "RGBA")
    g = ImageDraw.Draw(img)
    for a, rad in marks:
        px, py = c + np.cos(a) * rad * c, c + np.sin(a) * rad * c
        g.ellipse([px - ss * 5, py - ss * 5, px + ss * 5, py + ss * 5], fill=(90, 90, 96, 255))
    for k in range(stars if style == "vinyl" else 0):          # glitter star stickers: classic style only
        a = 0.55 + k * 2.4
        rr = (0.58 + 0.14 * (k % 2)) * c
        _star(g, c + np.cos(a) * rr, c + np.sin(a) * rr, (0.09 + 0.05 * (k % 2)) * c)
    img = img.filter(ImageFilter.GaussianBlur(0.4 * ss / 2)).resize((diameter, diameter), Image.LANCZOS)
    img.save(path)
    return path


def make_vinyl(path, diameter=560, label=(150, 150, 156), ss=2, stars=0):
    """Backwards-compatible name for the classic style."""
    return make_disc(path, diameter, "vinyl", stars=stars, label=label, ss=ss)


def _star(g, cx, cy, r):
    pts = []
    for i in range(10):
        a = -np.pi / 2 + i * np.pi / 5
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + np.cos(a) * rad, cy + np.sin(a) * rad))
    g.polygon(pts, fill=(205, 208, 214, 255), outline=(250, 250, 252, 255))
