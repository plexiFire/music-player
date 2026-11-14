"""Thumbnail families, drawn from the project's own song covers. Seven styles learned from eight reference thumbnails
(their views are kept in REFERENCE), each in six colour variants. Nothing is downloaded: backgrounds are drawn here.

render(family, variant, covers, ctx, size=(1280, 720)) -> PIL image
ctx: {"title": YouTube title, "moods": [...], "minutes": float}
Text rule: header-style families always say "PlayList" (never the playlist's own name); concept-style families use a
phrase picked from the detected mood (never the name either)."""
import hashlib
import os

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FONTS = os.path.join(os.path.dirname(__file__), "fonts")
HEADER = "PlayList"

REFERENCE = {   # what the eight reference thumbnails did (views as seen); brightness 0..1. n=8: a hint, not a proof.
    "night": {"views": 3840035, "note": "Night photo, big concept title, four covers around it. Darkest of the eight and the most viewed."},
    "swirl": {"views": 2846410, "note": "Black-and-white swirl, serif 'Playlist', six covers. Second most viewed, also very dark."},
    "sunset": {"views": 485216, "note": "Sunset bokeh, small sans 'Playlist', six covers."},
    "sky": {"views": 284536, "note": "Cloudy sky, big condensed concept title, four covers and two chat bubbles."},
    "bold": {"views": 71796, "note": "Huge bold title, six covers, video-time badge and progress bar."},
    "season": {"views": 52263, "note": "Seasonal illustration, italic serif 'Playlist', six covers with shadows."},
    "poster": {"views": 0, "note": "Our own: three large covers fanned out on a dark gradient. No reference yet: test it."},
}
FAMILIES = [
    {"id": "night", "label": "Late night", "variants": ["blue", "purple", "teal", "crimson", "amber", "green"]},
    {"id": "swirl", "label": "Dark swirl", "variants": ["mono", "blue", "violet", "wine", "teal", "sepia"]},
    {"id": "sunset", "label": "Sunset glow", "variants": ["orange", "pink", "violet", "gold", "rose", "dusk"]},
    {"id": "sky", "label": "Cloud sky + chat", "variants": ["blue", "dusk", "pink", "night", "mint", "grey"]},
    {"id": "bold", "label": "Big bold title", "variants": ["mono", "blue", "violet", "crimson", "teal", "amber"]},
    {"id": "season", "label": "Seasons", "variants": ["autumn", "winter", "spring", "summer", "dusk", "night"]},
    {"id": "poster", "label": "Fanned poster", "variants": ["ink", "blue", "plum", "forest", "ember", "slate"]},
]
# (dark, light, accent) colours per variant name, shared by the families that use a plain colour variant
COL = {
    "blue": ((6, 10, 30), (40, 80, 210), (150, 190, 255)), "purple": ((12, 6, 28), (110, 50, 190), (200, 150, 255)),
    "teal": ((3, 14, 18), (20, 150, 150), (130, 235, 225)), "crimson": ((22, 4, 8), (190, 36, 52), (255, 150, 150)),
    "amber": ((20, 10, 3), (215, 125, 30), (255, 205, 120)), "green": ((4, 16, 8), (36, 150, 80), (160, 235, 170)),
    "mono": ((4, 4, 5), (150, 150, 155), (235, 235, 235)), "violet": ((10, 5, 24), (120, 80, 200), (205, 180, 255)),
    "wine": ((18, 4, 10), (150, 36, 70), (240, 150, 175)), "sepia": ((16, 10, 6), (150, 110, 70), (235, 205, 165)),
    "orange": ((28, 8, 12), (240, 110, 40), (255, 215, 150)), "pink": ((28, 8, 24), (235, 90, 150), (255, 200, 225)),
    "gold": ((26, 14, 6), (240, 175, 50), (255, 235, 170)), "rose": ((26, 8, 16), (220, 100, 120), (255, 210, 215)),
    "dusk": ((14, 8, 30), (130, 80, 170), (255, 170, 130)), "mint": ((6, 20, 20), (110, 200, 180), (215, 255, 240)),
    "grey": ((12, 13, 16), (130, 140, 155), (225, 230, 240)), "night": ((4, 6, 20), (30, 50, 130), (170, 190, 240)),
    "ink": ((5, 5, 7), (60, 60, 70), (230, 230, 235)), "plum": ((14, 5, 20), (100, 40, 120), (225, 180, 240)),
    "forest": ((4, 14, 8), (40, 110, 70), (180, 225, 190)), "ember": ((20, 6, 4), (180, 60, 30), (255, 190, 150)),
    "slate": ((10, 12, 16), (70, 90, 115), (200, 215, 235)),
}
SEASON = {   # sky top, sky bottom, leaf colours
    "autumn": ((90, 40, 15), (230, 140, 50), [(200, 70, 20), (235, 150, 30), (150, 40, 20), (240, 190, 70)]),
    "winter": ((70, 110, 170), (225, 238, 250), [(255, 255, 255), (220, 235, 250)]),
    "spring": ((120, 170, 215), (250, 215, 225), [(250, 180, 200), (255, 220, 230), (200, 235, 190)]),
    "summer": ((40, 120, 200), (255, 220, 130), [(255, 240, 160), (120, 200, 120), (255, 200, 90)]),
    "dusk": ((30, 20, 70), (230, 110, 90), [(255, 170, 120), (200, 110, 170)]),
    "night": ((5, 8, 25), (40, 50, 110), [(150, 170, 255), (220, 230, 255)]),
}
CONCEPT = [   # mood word -> concept title (header-less families) and two chat-bubble lines
    (("sad", "melancholy", "heartbreak", "lonely", "emotional"), "Bittersweet Memories", ("things we never said", "playing back those moments")),
    (("late night", "dark", "night"), "Late Night Melodies", ("still awake at 3 AM", "this one keeps me company")),
    (("nostalgic", "memories", "throwback"), "Back In Time", ("things we left in yesterday", "take me back there")),
    (("dreamy", "dream", "aesthetic", "warm"), "Dreamy Hours", ("floating through the evening", "stay in your own little world")),
    (("romantic", "love"), "Falling Slowly", ("you crossed my mind again", "this one sounds like you")),
    (("upbeat", "energetic", "feel good", "happy"), "Good Mood Only", ("today is a good day", "turn it up")),
    (("chill", "calm", "slow", "mellow", "peaceful", "relax"), "Slow Down Songs", ("take a minute for yourself", "just breathe and press play")),
]


def concept_for(moods):
    ms = " ".join(moods).lower()
    for keys, title, chat in CONCEPT:
        if any(k in ms for k in keys):
            return title, chat
    return "Songs For Tonight", ("this one is for tonight", "press play and stay a while")


# ---------- drawing helpers ----------
_font_cache = {}


def font(name, size, weight=None):
    key = (name, size, weight)
    if key not in _font_cache:
        try:
            f = ImageFont.truetype(os.path.join(FONTS, name), size)
            if weight:
                try:
                    f.set_variation_by_axes([weight])
                except Exception:
                    pass
        except OSError:
            f = ImageFont.load_default()
        _font_cache[key] = f
    return _font_cache[key]


def grad(w, h, top, bottom):
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    a = np.array(top, np.float32)[None, None, :] * (1 - t) + np.array(bottom, np.float32)[None, None, :] * t
    return np.repeat(a, w, axis=1)


def to_img(a):
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def grain(img, amount=6, seed=1):
    a = np.asarray(img, np.float32)
    return to_img(a + np.random.default_rng(seed).normal(0, amount, a.shape[:2])[..., None])


def vignette(img, strength=0.55):
    w, h = img.size
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.hypot((x - w / 2) / (w / 2), (y - h / 2) / (h / 2))
    return to_img(np.asarray(img, np.float32) * (1 - strength * np.clip(d - 0.35, 0, 1) ** 1.4)[..., None])


def bokeh(size, colours, n, seed, rmin, rmax, alpha=(40, 120), blur=3, region=(0, 0, 1, 1)):
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = np.random.default_rng(seed)
    for _ in range(n):
        r = rng.uniform(rmin, rmax)
        x, y = rng.uniform(region[0], region[2]) * w, rng.uniform(region[1], region[3]) * h
        c = colours[rng.integers(len(colours))]
        d.ellipse([x - r, y - r, x + r, y + r], fill=(*c, int(rng.uniform(*alpha))))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def rounded(im, radius):
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, im.size[0] - 1, im.size[1] - 1], radius, fill=255)
    out = im.convert("RGBA")
    out.putalpha(m)
    return out


def place_cover(base, path, x, y, s, angle=0, shadow=True, radius=None, k=1.0):
    """Cover thumbnail with a soft drop shadow, optionally rotated. (x, y) = centre."""
    cv = rounded(Image.open(path).convert("RGB").resize((s, s), Image.LANCZOS), radius if radius is not None else max(2, round(4 * k)))
    if angle:
        cv = cv.rotate(angle, resample=Image.BICUBIC, expand=True)
    if shadow:
        sh = Image.new("RGBA", (cv.size[0] + int(60 * k), cv.size[1] + int(60 * k)), (0, 0, 0, 0))
        sh.paste((0, 0, 0, 150), (int(30 * k), int(30 * k), int(30 * k) + cv.size[0], int(30 * k) + cv.size[1]), cv.split()[3])
        sh = sh.filter(ImageFilter.GaussianBlur(14 * k))
        base.alpha_composite(sh, (int(x - sh.size[0] / 2 + 6 * k), int(y - sh.size[1] / 2 + 12 * k)))
    base.alpha_composite(cv, (int(x - cv.size[0] / 2), int(y - cv.size[1] / 2)))


def text(base, xy, s, f, fill=(255, 255, 255), shadow=(0, 0, 0, 170), anchor="mm", tracking=0, k=1.0, blur=0):
    d = ImageDraw.Draw(base)
    if tracking:
        widths = [d.textlength(c, font=f) for c in s]
        total = sum(widths) + tracking * (len(s) - 1)
        x = xy[0] - total / 2 if anchor[0] == "m" else xy[0]
        for c, w in zip(s, widths):
            if shadow:
                d.text((x + 3 * k, xy[1] + 3 * k), c, font=f, fill=shadow, anchor="l" + anchor[1])
            d.text((x, xy[1]), c, font=f, fill=fill, anchor="l" + anchor[1])
            x += w + tracking
        return
    if shadow:
        sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((xy[0] + 4 * k, xy[1] + 5 * k), s, font=f, fill=shadow, anchor=anchor, align="center")
        base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(3 * k)) if blur is not None else sh)
    d.text(xy, s, font=f, fill=fill, anchor=anchor, align="center")


def fit_lines(s, max_w, size, min_size, name, weight, max_lines=3):
    """Wrap s into at most max_lines lines that fit max_w pixels, shrinking the font until they do."""
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    words = s.split()
    for sz in range(size, min_size - 1, -4):
        f = font(name, sz, weight)
        lines, cur = [], ""
        for wd in words:
            t = (cur + " " + wd).strip()
            if probe.textlength(t, font=f) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = wd
        lines.append(cur)
        if len(lines) <= max_lines and all(probe.textlength(x, font=f) <= max_w for x in lines):
            return lines, f
    return lines[:max_lines], f


def pick_covers(covers, n):
    covers = [c for c in covers if c and os.path.exists(c)]
    if not covers:
        raise ValueError("no cover images yet: extract the songs first")
    return [covers[i % len(covers)] for i in range(n)] if len(covers) < n else covers[:n]


# ---------- backgrounds ----------
def bg_night(w, h, v):
    dark, light, acc = COL[v]
    a = grad(w, h, dark, tuple(int(c * 0.35) for c in light))
    img = to_img(a)
    streaks = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(streaks)
    rng = np.random.default_rng(4)
    for i in range(14):                                   # long-exposure light trails along the road
        y0 = h * rng.uniform(0.66, 0.86)
        d.line([(-20, y0), (w * 0.5, y0 - rng.uniform(5, 40)), (w + 20, y0 - rng.uniform(40, 120))],
               fill=(*[min(255, int(c * 1.1)) for c in (acc if i % 2 else light)], int(rng.uniform(60, 150))), width=int(rng.uniform(2, 7)))
    img = Image.alpha_composite(img.convert("RGBA"), streaks.filter(ImageFilter.GaussianBlur(5)))
    img = Image.alpha_composite(img, bokeh((w, h), [light, acc, (255, 255, 255)], 40, 3, h * 0.008, h * 0.03, (60, 150), 2.5, (0, 0.55, 1, 0.95)))
    return vignette(grain(img.convert("RGB"), 4), 0.5).convert("RGBA")


def bg_swirl(w, h, v):
    from ..look import background
    dark, light, acc = COL[v]
    f = background._frame(w // 3, h // 3, 0.9, dark, light, scale=2.4, warp=1.0, iters=3, phase=1.7, contrast=1, gamma=1.6)
    img = to_img(f.astype(np.float32)).resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6))
    return vignette(grain(img, 5), 0.4).convert("RGBA")


def bg_sunset(w, h, v):
    dark, light, acc = COL[v]
    top = tuple(int(c * 1.6) for c in dark)
    a = np.concatenate([grad(w, h // 2, top, light), grad(w, h - h // 2, light, tuple(int(c * 0.6) for c in dark))], axis=0)
    img = Image.alpha_composite(to_img(a).convert("RGBA"), bokeh((w, h), [acc, light, (255, 230, 190)], 70, 8, h * 0.012, h * 0.05, (50, 140), 6, (0, 0.5, 1, 1)))
    return vignette(grain(img.convert("RGB"), 5), 0.45).convert("RGBA")


def bg_sky(w, h, v):
    dark, light, acc = COL[v]
    img = to_img(grad(w, h, tuple(int(c * 0.7 + 10) for c in light), tuple(int(c * 0.5) for c in light))).convert("RGBA")
    clouds = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(clouds)
    rng = np.random.default_rng(6)
    for _ in range(26):
        cx, cy, rw = rng.uniform(0, w), rng.uniform(0, h * 0.85), rng.uniform(w * 0.08, w * 0.22)
        d.ellipse([cx - rw, cy - rw * 0.45, cx + rw, cy + rw * 0.45], fill=(*acc, int(rng.uniform(60, 130))))
    return vignette(grain(Image.alpha_composite(img, clouds.filter(ImageFilter.GaussianBlur(28))).convert("RGB"), 4), 0.35).convert("RGBA")


def bg_season(w, h, v):
    top, bottom, leaves = SEASON[v]
    img = to_img(grad(w, h, top, bottom)).convert("RGBA")
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = np.random.default_rng(9)
    for _ in range(150):
        x, y, rw = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(h * 0.008, h * 0.03)
        e = Image.new("RGBA", (int(rw * 6), int(rw * 6)), (0, 0, 0, 0))
        ImageDraw.Draw(e).ellipse([rw, rw * 2, rw * 5, rw * 4], fill=(*leaves[rng.integers(len(leaves))], int(rng.uniform(120, 230))))
        e = e.rotate(rng.uniform(0, 180), resample=Image.BICUBIC)
        layer.alpha_composite(e, (int(x), int(y)))
    img = Image.alpha_composite(img, layer.filter(ImageFilter.GaussianBlur(1.6)))
    return vignette(grain(img.convert("RGB"), 4), 0.4).convert("RGBA")


def bg_poster(w, h, v):
    dark, light, acc = COL[v]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    glow = np.exp(-(((x - w * 0.5) / (w * 0.45)) ** 2 + ((y - h * 0.45) / (h * 0.55)) ** 2))[..., None]
    a = np.array(dark, np.float32)[None, None, :] * (1 - glow) + np.array(light, np.float32)[None, None, :] * glow * 0.8
    return vignette(grain(to_img(a), 4), 0.5).convert("RGBA")


# ---------- layouts ----------
def lay_night(w, h, v, covers, ctx):
    k = w / 1280
    img = bg_night(w, h, v)
    cs = pick_covers(covers, 4)
    s = int(250 * k)
    for (fx, fy), c in zip([(0.27, 0.22), (0.73, 0.22), (0.27, 0.78), (0.73, 0.78)], cs):
        place_cover(img, c, w * fx, h * fy, s, k=k)
    title, _ = concept_for(ctx.get("moods", []))
    accent = COL[v][2]
    text(img, (w / 2, h * 0.5), title, font("PlayfairDisplay.ttf", int(100 * k), 700), fill=tuple(min(255, int(c * 1.05)) for c in accent), k=k)
    return img


def lay_grid(w, h, img, covers, header, hfont, k, size=210, top=0.1, fill=(255, 255, 255), tracking=0):
    cs = pick_covers(covers, 6)
    text(img, (w / 2, h * top), header, hfont, fill=fill, k=k, tracking=tracking)
    s, gap = int(size * k), int(34 * k)
    x0 = w / 2 - (3 * s + 2 * gap) / 2 + s / 2
    y0 = h * (top + 0.1) + s / 2 + 14 * k
    for i, c in enumerate(cs):
        place_cover(img, c, x0 + (i % 3) * (s + gap), y0 + (i // 3) * (s + gap), s, k=k)
    return img


def lay_swirl(w, h, v, covers, ctx):
    k = w / 1280
    return lay_grid(w, h, bg_swirl(w, h, v), covers, HEADER, font("PlayfairDisplay.ttf", int(82 * k), 600), k, tracking=int(10 * k))


def lay_sunset(w, h, v, covers, ctx):
    k = w / 1280
    return lay_grid(w, h, bg_sunset(w, h, v), covers, HEADER, font("Montserrat.ttf", int(62 * k), 500), k, tracking=int(16 * k), fill=(255, 245, 235))


def lay_sky(w, h, v, covers, ctx):
    k = w / 1280
    img = bg_sky(w, h, v)
    cs = pick_covers(covers, 4)
    s = int(238 * k)
    for i, c in enumerate(cs):
        place_cover(img, c, w * 0.13 + (i % 2) * (s + 34 * k) + s / 2 - 20 * k, h * 0.2 + (i // 2) * (s + 34 * k) + s / 2 - 28 * k, s, k=k)
    title, chat = concept_for(ctx.get("moods", []))
    words = title.split(" ", 1)
    f = font("Oswald.ttf", int(124 * k), 600)
    cream = (240, 232, 215)
    for j, wd in enumerate(words):
        text(img, (w * 0.755, h * (0.3 + 0.2 * j)), wd, f, fill=cream, k=k)
    for j, line in enumerate(chat):                       # two chat bubbles, like a message thread
        bw, bh = int(540 * k), int(72 * k)
        bx, by = w - bw - int(36 * k) - j * int(20 * k), h * 0.7 + j * (bh + int(14 * k))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], int(14 * k), fill=(24, 86, 60, 235))
        d.text((bx + 20 * k, by + bh / 2), line, font=font("Montserrat.ttf", int(31 * k), 500), fill=(235, 255, 240), anchor="lm")
    return img


def lay_bold(w, h, v, covers, ctx):
    k = w / 1280
    img = bg_swirl(w, h, v)
    cs = pick_covers(covers, 6)
    s, gap = int(150 * k), int(26 * k)
    text(img, (w / 2, h * 0.075), HEADER, font("PlayfairDisplay.ttf", int(54 * k), 600), k=k, tracking=int(8 * k))
    x0 = w / 2 - (3 * s + 2 * gap) / 2 + s / 2
    for i, c in enumerate(cs):
        place_cover(img, c, x0 + (i % 3) * (s + gap), h * 0.19 + s / 2 + (i // 3) * (s + gap), s, k=k)
    body = ctx.get("title", "").replace("[Playlist]", "").strip() or "When music is all you need"
    lines, f = fit_lines(body.upper(), w * 0.92, int(100 * k), int(52 * k), "Montserrat.ttf", 800, max_lines=3)
    y = h * 0.70 + (0 if len(lines) < 3 else -20 * k)
    for j, ln in enumerate(lines):
        text(img, (w / 2, y + j * f.size * 1.02), ln, f, k=k)
    d = ImageDraw.Draw(img)                               # decorative video-length badge and progress bar
    mins = int(ctx.get("minutes") or 20)
    badge = f"{mins}:{int((ctx.get('minutes') or 0) * 60) % 60:02d}"
    bx, by, bw, bh = w - int(210 * k), h - int(96 * k), int(180 * k), int(56 * k)
    d.rounded_rectangle([bx, by, bx + bw, by + bh], int(14 * k), fill=(15, 15, 15, 215))
    d.text((bx + 34 * k, by + bh / 2), "♪", font=font("Montserrat.ttf", int(30 * k), 700), fill=(255, 255, 255), anchor="lm")
    d.text((bx + 66 * k, by + bh / 2), badge, font=font("Montserrat.ttf", int(30 * k), 700), fill=(255, 255, 255), anchor="lm")
    d.rectangle([0, h - int(12 * k), w, h], fill=(90, 90, 90, 200))
    d.rectangle([0, h - int(12 * k), int(w * 0.1), h], fill=(240, 30, 30, 255))
    return img


def lay_season(w, h, v, covers, ctx):
    k = w / 1280
    return lay_grid(w, h, bg_season(w, h, v), covers, HEADER, font("PlayfairDisplay-Italic.ttf", int(88 * k), 600), k, size=200, top=0.1)


def lay_poster(w, h, v, covers, ctx):
    k = w / 1280
    img = bg_poster(w, h, v)
    cs = pick_covers(covers, 3)
    s = int(330 * k)
    for (fx, fy, ang), c in zip([(0.31, 0.56, 7), (0.69, 0.56, -7), (0.5, 0.5, 0)], cs):
        place_cover(img, c, w * fx, h * fy, s if fx == 0.5 else int(s * 0.9), angle=ang, k=k)
    text(img, (w / 2, h * 0.11), HEADER, font("Montserrat.ttf", int(56 * k), 600), k=k, tracking=int(22 * k), fill=COL[v][2])
    return img


LAYOUTS = {"night": lay_night, "swirl": lay_swirl, "sunset": lay_sunset, "sky": lay_sky, "bold": lay_bold, "season": lay_season, "poster": lay_poster}


def render(family, variant, covers, ctx=None, size=(1280, 720)):
    ctx = ctx or {}
    fam = next((f for f in FAMILIES if f["id"] == family), None)
    if not fam or variant not in fam["variants"]:
        raise ValueError(f"unknown thumbnail style {family}/{variant}")
    return LAYOUTS[family](size[0], size[1], variant, covers, ctx).convert("RGB")


def cache_key(family, variant, covers, ctx, size):
    sig = repr((family, variant, [(c, os.path.getmtime(c)) for c in covers if c and os.path.exists(c)], ctx.get("moods"),
                ctx.get("title"), round(ctx.get("minutes") or 0), size))
    return hashlib.sha1(sig.encode()).hexdigest()[:12]


def save_jpeg(img, path, max_bytes=1_900_000):
    """YouTube accepts thumbnails up to 2 MB: lower the quality until the file fits."""
    for q in (92, 88, 84, 78, 70):
        img.save(path, "JPEG", quality=q, optimize=True)
        if os.path.getsize(path) <= max_bytes:
            break
    return path
