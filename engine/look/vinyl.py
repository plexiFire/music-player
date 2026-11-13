"""Draw a realistic vinyl record PNG (RGBA): fine grooves, track gaps, anisotropic sheen, paper label."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def make_vinyl(path, diameter=560, label=(150, 150, 156), ss=2, stars=0):
    d = diameter * ss
    c = d / 2
    rng = np.random.default_rng(11)
    y, x = np.mgrid[0:d, 0:d].astype(np.float32)
    dx, dy = x - c + 0.5, y - c + 0.5
    r = np.hypot(dx, dy) / c                      # 0 centre .. 1 rim
    ang = np.arctan2(dy, dx)

    # fine grooves: per-ring random brightness, hundreds of rings
    rings = rng.normal(0, 1, 900).astype(np.float32)
    idx = np.clip(((r - 0.36) / 0.62 * 899), 0, 899).astype(int)
    base = 16 + 5 * rings[idx] + 3 * np.sin(r * 700)
    for gap in (0.52, 0.66, 0.79):                # smoother bands between tracks
        base -= 9 * np.exp(-((r - gap) / 0.006) ** 2)
    base = np.repeat(base[..., None], 3, axis=2)

    # light reflecting off the grooves: two soft opposed lobes that stay fixed while the disc spins
    lobe = np.maximum(0, np.cos(2 * (ang - 0.6))) ** 10
    sheen = (0.55 * lobe * np.clip((r - 0.34) / 0.2, 0, 1) * (r < 0.985))[..., None]
    rgb = base + sheen * np.array([150, 150, 158], np.float32)
    rgb += np.exp(-((r - 0.985) / 0.01) ** 2)[..., None] * 40      # bevelled rim highlight

    # paper label
    lab = (r < 0.34)[..., None]
    shade = 1 - 0.18 * (np.hypot(dx - 0.2 * c, dy - 0.25 * c) / c)  # faint lighting gradient
    paper = np.array(label, np.float32)[None, None, :] * shade[..., None]
    paper += rng.normal(0, 2.5, (d, d, 1))
    rgb = np.where(lab, paper, rgb)
    rgb -= (np.abs(r - 0.335) < 0.004)[..., None] * 40                # label edge
    rgb -= (np.abs(r - 0.25) < 0.003)[..., None] * 30                 # printed ring
    rgb = np.where((r < 0.028)[..., None], np.array([10, 10, 10], np.float32), rgb)  # spindle hole

    alpha = (r <= 1.0).astype(np.uint8) * 255
    img = Image.fromarray(np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), alpha]), "RGBA")
    # draw a few tiny label marks so the spin is visible on the label too
    g = ImageDraw.Draw(img)
    for a in (0.0, 3.14159):
        px, py = c + np.cos(a) * 0.20 * c, c + np.sin(a) * 0.20 * c
        g.ellipse([px - ss * 5, py - ss * 5, px + ss * 5, py + ss * 5], fill=(90, 90, 96, 255))
    for k in range(stars):  # glitter star stickers on the grooves
        a = 0.55 + k * 2.4
        rr = (0.58 + 0.14 * (k % 2)) * c
        _star(g, c + np.cos(a) * rr, c + np.sin(a) * rr, (0.09 + 0.05 * (k % 2)) * c)
    img = img.filter(ImageFilter.GaussianBlur(0.4 * ss / 2)).resize((diameter, diameter), Image.LANCZOS)
    img.save(path)
    return path


def _star(g, cx, cy, r):
    pts = []
    for i in range(10):
        a = -np.pi / 2 + i * np.pi / 5
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + np.cos(a) * rad, cy + np.sin(a) * rad))
    g.polygon(pts, fill=(205, 208, 214, 255), outline=(250, 250, 252, 255))
