"""Disc styles for the spinning record behind the cover. All are drawn procedurally (RGBA PNG), nothing is downloaded.

make_disc(path, diameter, style, art=None, stars=3)

styles:  vinyl   classic black record, cream label (+ optional star stickers)   [default]
         brown   brown / amber coloured vinyl, cream label
         plain   plain matte black disc, no label art
         cd      silver CD with a rainbow reflection and a clear centre ring
         gold    gold metallic disc, black label
         neon    translucent neon (magenta/cyan) swirl vinyl
         picture picture disc: the song's cover art covers the whole spinning disc
"""
import colorsys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

STYLES = {
    "vinyl": "Classic vinyl (black, cream label)",
    "brown": "Brown coloured vinyl",
    "plain": "Plain black disc",
    "cd": "Silver CD (rainbow shine)",
    "gold": "Gold disc",
    "neon": "Neon colour vinyl",
    "picture": "Picture disc (cover art spins)",
}


def _hsv_to_rgb(h, s, v):
    """Vectorised HSV -> RGB (0..1) for numpy arrays."""
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r = np.choose(i, [v, q, p, p, t, v]); g = np.choose(i, [t, v, v, q, p, p]); b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def make_disc(path, diameter=560, style="vinyl", art=None, stars=0, label=(228, 220, 200), ss=2):
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

    if style in ("vinyl", "brown"):
        tone = np.array([16, 16, 18] if style == "vinyl" else [92, 52, 24], np.float32)
        grain = (1 + (0.30 if style == "vinyl" else 0.07) * rings[idx] + 0.18 * np.sin(r * 700))[..., None]
        base = tone[None, None, :] * grain if style == "brown" else tone[None, None, :] + 5 * rings[idx][..., None] + 3 * np.sin(r * 700)[..., None]
        for gap in (0.52, 0.66, 0.79):
            base = base - 9 * np.exp(-((r - gap) / 0.006) ** 2)[..., None]
        sheen_col = np.array([150, 150, 158] if style == "vinyl" else [255, 190, 120], np.float32)
        rgb = base + (0.55 * lobe * np.clip((r - 0.34) / 0.2, 0, 1) * (r < 0.985))[..., None] * sheen_col
        rgb = rgb + rim * 40
        rgb = paper_label(0.34, label)
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
    elif style == "cd":
        h = (ang / (2 * np.pi) * 2.0 + r * 2.2) % 1.0
        rainbow = _hsv_to_rgb(h, np.full_like(h, 0.55), np.full_like(h, 0.95)) * 255
        silver = np.array([188, 192, 200], np.float32)[None, None, :] * (0.92 + 0.08 * np.sin(r * 420))[..., None]
        rgb = 0.58 * silver + 0.42 * rainbow
        rgb = rgb + (0.35 * lobe)[..., None] * 90
        rgb = np.where(((r > 0.13) & (r < 0.30))[..., None], 0.55 * rgb + 0.45 * np.array([225, 228, 235], np.float32), rgb)   # clear ring
        rgb = rgb - (np.abs(r - 0.30) < 0.004)[..., None] * 45 - (np.abs(r - 0.13) < 0.004)[..., None] * 45
        rgb = rgb - rim * 60
        alpha = alpha * np.where(r < 0.065, 0, 1)                                                 # centre hole is see-through
        alpha = np.where((r > 0.065) & (r < 0.30), np.minimum(alpha, 205), alpha)               # clear plastic ring
        marks = [(0.0, 0.44), (3.14159, 0.44)]
    elif style == "gold":
        base = np.array([158, 120, 44], np.float32)[None, None, :] * (0.85 + 0.10 * rings[idx] + 0.08 * np.sin(r * 500))[..., None]
        rgb = base + (0.95 * lobe * (r < 0.985))[..., None] * np.array([255, 232, 160], np.float32) * 0.8
        rgb = rgb + (0.25 * np.maximum(0, np.cos(2 * (ang - 0.6 - 1.57))) ** 6)[..., None] * 120
        rgb = rgb + rim * 50
        rgb = np.where((r < 0.32)[..., None], np.array([22, 18, 14], np.float32) + rng.normal(0, 2, (d, d, 1)), rgb)
        rgb = rgb + (np.abs(r - 0.31) < 0.004)[..., None] * np.array([210, 170, 80], np.float32)
        rgb = np.where((r < 0.028)[..., None], np.array([8, 8, 8], np.float32), rgb)
        marks = [(0.0, 0.20), (3.14159, 0.20)]
    elif style == "neon":
        sw = 0.5 + 0.5 * np.sin(ang * 3 + r * 13)
        A, B = np.array([236, 64, 208], np.float32), np.array([48, 196, 255], np.float32)
        mix = A[None, None, :] * sw[..., None] + B[None, None, :] * (1 - sw)[..., None]
        body = np.array([20, 10, 40], np.float32)[None, None, :] * 0.5 + mix * (0.42 + 0.06 * rings[idx])[..., None]
        rgb = body + (0.8 * lobe * np.clip((r - 0.3) / 0.2, 0, 1) * (r < 0.985))[..., None] * np.array([230, 230, 255], np.float32) * 0.55
        rgb = rgb + (np.exp(-((r - 0.985) / 0.012) ** 2))[..., None] * np.array([255, 160, 255], np.float32) * 0.6
        rgb = np.where((r < 0.30)[..., None], np.array([14, 10, 24], np.float32), rgb)
        rgb = rgb + (np.abs(r - 0.295) < 0.005)[..., None] * np.array([120, 240, 255], np.float32)
        rgb = np.where((r < 0.028)[..., None], np.array([6, 6, 10], np.float32), rgb)
        marks = [(0.0, 0.17), (3.14159, 0.17)]
    else:  # picture disc: the cover art IS the disc
        if not art:
            raise ValueError("the 'picture' disc needs the song's cover art")
        pic = np.asarray(Image.open(art).convert("RGB").resize((d, d), Image.LANCZOS), np.float32)
        grooves = (4 * rings[idx] * 0.35 + 3 * np.sin(r * 700))[..., None]
        rgb = pic * 0.93 + grooves
        rgb = rgb + (0.30 * lobe * (r < 0.985))[..., None] * 120
        rgb = rgb - rim * 40
        rgb = np.where(((r > 0.06) & (r < 0.115))[..., None], np.array([200, 200, 206], np.float32), rgb)   # small hub plate
        rgb = rgb - (np.abs(r - 0.115) < 0.004)[..., None] * 60
        rgb = np.where((r < 0.03)[..., None], np.array([12, 12, 12], np.float32), rgb)
        marks = []

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
