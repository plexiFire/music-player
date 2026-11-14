"""Thumbnail families, drawn from the project's own song covers. Seven styles learned from eight reference thumbnails
(their views are kept in REFERENCE), each in six colour variants. Nothing is downloaded: backgrounds are drawn here.

render(family, variant, covers, ctx, size=(1280, 720)) -> PIL image
ctx: {"title": YouTube title, "moods": [...], "minutes": float}
Text rule: header-style families always say "PlayList" (never the playlist's own name); concept-style families use a
phrase picked from the detected mood (never the name either)."""
import hashlib
import os
import re

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FONTS = os.path.join(os.path.dirname(__file__), "fonts")
HEADER = "PlayList"

REFERENCE = {   # what the eight reference thumbnails did (views as seen); brightness 0..1. n=8: a hint, not a proof.
    "night": {"views": 3840035, "note": "Night photo, big concept title, the covers of your songs around it (up to six). Darkest of the eight and the most viewed."},
    "swirl": {"views": 2846410, "note": "Black-and-white swirl, serif 'Playlist', six covers. Second most viewed, also very dark."},
    "sunset": {"views": 485216, "note": "Sunset bokeh, small sans 'Playlist', six covers."},
    "sky": {"views": 284536, "note": "Cloudy sky, big condensed concept title, the covers of your songs (up to six) and two chat bubbles."},
    "bold": {"views": 71796, "note": "Huge bold title, six covers, video-time badge and progress bar."},
    "season": {"views": 52263, "note": "Seasonal illustration, italic serif 'Playlist', six covers with shadows."},
    "poster": {"views": 0, "note": "Our own: three large covers fanned out on a dark gradient. No reference yet: test it."},
    "record": {"views": 0, "note": "Our own: a big vinyl record with a cover as its label, two covers leaning on it, big bold title. No reference yet: test it."},
    "cascade": {"views": 0, "note": "Our own: six covers stepping down a diagonal beside a big bold title. No reference yet: test it."},
    "hero": {"views": 0, "note": "Our own: one big glowing cover, five small ones under it, bold title across the bottom. No reference yet: test it."},
    "filmstrip": {"views": 0, "note": "Our own: covers on a tilted film strip with a bold title. No reference yet: test it."},
}
FAMILIES = [
    {"id": "night", "label": "Late night", "variants": ["blue", "purple", "teal", "crimson", "amber", "green"]},
    {"id": "swirl", "label": "Dark swirl", "variants": ["mono", "blue", "violet", "wine", "teal", "sepia"]},
    {"id": "sunset", "label": "Sunset glow", "variants": ["orange", "pink", "violet", "gold", "rose", "dusk"]},
    {"id": "sky", "label": "Cloud sky + chat", "variants": ["blue", "dusk", "pink", "night", "mint", "grey"]},
    {"id": "bold", "label": "Big bold title", "variants": ["mono", "blue", "violet", "crimson", "teal", "amber"]},
    {"id": "season", "label": "Seasons", "variants": ["autumn", "winter", "spring", "summer", "dusk", "night"]},
    {"id": "poster", "label": "Fanned poster", "variants": ["ink", "blue", "plum", "forest", "ember", "slate"]},
    {"id": "record", "label": "Big record", "variants": ["mono", "blue", "violet", "wine", "teal", "sepia"]},
    {"id": "cascade", "label": "Cover cascade", "variants": ["mono", "blue", "violet", "wine", "teal", "sepia"]},
    {"id": "hero", "label": "Hero cover", "variants": ["mono", "blue", "violet", "wine", "teal", "sepia"]},
    {"id": "filmstrip", "label": "Film strip", "variants": ["mono", "blue", "violet", "wine", "teal", "sepia"]},
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
REFERENCE_TEXTS = (     # words that stand on OTHER channels' thumbnails (the eight references). Never reused as our own text.
    "Late Night Melodies", "Bittersweet Memories", "When Music Is All We Need", "When Music Is All You Need", "Music Is My Drug",
    "things we left in yesterday", "playing back those moments", "Playlist")
CONCEPT = [   # mood word -> a short phrase of our own (concept-style thumbnails) and two chat-bubble lines of our own
    (("sad", "melancholy", "heartbreak", "lonely", "emotional"), "Soft Goodbyes", ("words I never sent", "this one still hurts")),
    (("late night", "dark", "night"), "Still Awake", ("it is way past midnight", "the quiet hours are mine")),
    (("nostalgic", "memories", "throwback"), "Rewind", ("take me back to then", "I remember this one")),
    (("dreamy", "dream", "aesthetic", "warm"), "Daydream Hours", ("drifting through the afternoon", "stay in your own little world")),
    (("romantic", "love"), "Held Close", ("you crossed my mind again", "this one sounds like you")),
    (("upbeat", "energetic", "feel good", "happy"), "Good Mood Only", ("today is a good day", "turn it up")),
    (("chill", "calm", "slow", "mellow", "peaceful", "relax"), "Slow Down Songs", ("take a minute for yourself", "just breathe and press play")),
]


def concept_for(moods):
    ms = " ".join(moods).lower()
    for keys, title, chat in CONCEPT:
        if any(k in ms for k in keys):
            return title, chat
    return "Songs For Tonight", ("this one is for tonight", "press play and stay a while")


def concept_text(ctx):
    """The text of the concept-style thumbnails: what you typed, else a phrase picked from the mood."""
    typed = re.sub(r"\s+", " ", ctx.get("thumb_text") or "").strip()
    return typed or concept_for(ctx.get("moods", []))[0]


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


def fit_box(s, max_w, max_h, size, min_size, name, weight, max_lines=3, spacing=1.1):
    """Wrap s into lines and shrink the font until the whole block fits max_w x max_h. -> (lines, font)."""
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    words = s.split()
    f, lines = font(name, min_size, weight), [s]
    for sz in range(int(size), int(min_size) - 1, -2):
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
        if len(lines) <= max_lines and all(probe.textlength(x, font=f) <= max_w for x in lines) and len(lines) * sz * spacing <= max_h:
            break
    return lines, f


def draw_block(img, lines, f, cx, cy, k, fill=(255, 255, 255), spacing=1.1):
    """Centre a block of lines on (cx, cy)."""
    lh = f.size * spacing
    y0 = cy - lh * (len(lines) - 1) / 2
    for j, ln in enumerate(lines):
        text(img, (cx, y0 + j * lh), ln, f, fill=fill, k=k)


def pick_covers(covers, n):
    """n covers for n slots. Fewer songs than slots: they repeat. More songs than slots: spread evenly over the whole playlist
    (first and last included), so a 10-song playlist is not shown as its first six songs only."""
    covers = [c for c in covers if c and os.path.exists(c)]
    if not covers:
        raise ValueError("no cover images yet: extract the songs first")
    if len(covers) < n:
        return [covers[i % len(covers)] for i in range(n)]
    if len(covers) == n:
        return covers
    return [covers[round(i * (len(covers) - 1) / (n - 1))] for i in range(n)] if n > 1 else covers[:1]


def real_count(covers):
    return len([c for c in covers if c and os.path.exists(c)])


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
    """Up to 4 songs: one cover in each corner around the title. 5 or more songs: three covers above and three below the title."""
    k = w / 1280
    img = bg_night(w, h, v)
    n = real_count(covers)
    if n <= 4:
        cs = pick_covers(covers, 4)
        s_ = int(250 * k)
        spots = [(0.27, 0.22), (0.73, 0.22), (0.27, 0.78), (0.73, 0.78)]
    else:
        cs = pick_covers(covers, 6 if n >= 6 else 5)
        s_ = int(192 * k)
        spots = [(0.2, 0.21), (0.5, 0.21), (0.8, 0.21), (0.2, 0.79), (0.5, 0.79), (0.8, 0.79)] if len(cs) == 6 \
            else [(0.2, 0.21), (0.5, 0.21), (0.8, 0.21), (0.35, 0.79), (0.65, 0.79)]
    for (fx, fy), c in zip(spots, cs):
        place_cover(img, c, w * fx, h * fy, s_, k=k)
    accent = tuple(min(255, int(c * 1.05)) for c in COL[v][2])
    lines, f = fit_box(concept_text(ctx), w * 0.84, h * 0.20, 100 * k, 44 * k, "PlayfairDisplay.ttf", 700, max_lines=2)
    draw_block(img, lines, f, w / 2, h * 0.5, k, fill=accent)
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
    if real_count(covers) <= 4:                                          # 2 x 2 for up to four songs
        cs = pick_covers(covers, 4)
        s_ = int(238 * k)
        for i, c in enumerate(cs):
            place_cover(img, c, w * 0.13 + (i % 2) * (s_ + 34 * k) + s_ / 2 - 20 * k, h * 0.2 + (i // 2) * (s_ + 34 * k) + s_ / 2 - 28 * k, s_, k=k)
    else:                                                                # 3 x 2 for five or more songs: every one of the first six is shown
        n = 6 if real_count(covers) >= 6 else 5
        cs = pick_covers(covers, n)
        s_, gap = int(158 * k), int(20 * k)
        for i, c in enumerate(cs):
            place_cover(img, c, w * 0.045 + s_ / 2 + (i % 3) * (s_ + gap), h * 0.42 - (s_ + gap) / 2 + (i // 3) * (s_ + gap), s_, k=k)
    _, chat = concept_for(ctx.get("moods", []))
    lines, f = fit_box(concept_text(ctx), w * 0.40, h * 0.42, 124 * k, 50 * k, "Oswald.ttf", 600, max_lines=3, spacing=1.05)
    draw_block(img, lines, f, w * 0.755, h * 0.37, k, fill=(240, 232, 215), spacing=1.05)
    for j, line in enumerate(chat):                       # two chat bubbles, like a message thread
        bw, bh = int(540 * k), int(72 * k)
        bx, by = w - bw - int(36 * k) - j * int(20 * k), h * 0.72 + j * (bh + int(14 * k))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([bx, by, bx + bw, by + bh], int(14 * k), fill=(24, 86, 60, 235))
        d.text((bx + 20 * k, by + bh / 2), line, font=font("Montserrat.ttf", int(30 * k), 500), fill=(235, 255, 240), anchor="lm")
    return img


def lay_bold(w, h, v, covers, ctx):
    """Header, a compact grid of covers on top, and a big title in a box of its own: it is shrunk until ALL of it fits inside that box,
    above the video-length badge and the progress bar, never cut at the edge."""
    k = w / 1280
    img = bg_swirl(w, h, v)
    cs = pick_covers(covers, 6)
    s_, gap = int(128 * k), int(20 * k)
    text(img, (w / 2, h * 0.065), HEADER, font("PlayfairDisplay.ttf", int(52 * k), 600), k=k, tracking=int(8 * k))
    x0 = w / 2 - (3 * s_ + 2 * gap) / 2 + s_ / 2
    top = h * 0.115
    for i, c in enumerate(cs):
        place_cover(img, c, x0 + (i % 3) * (s_ + gap), top + s_ / 2 + (i // 3) * (s_ + gap), s_, k=k)
    grid_bottom = top + 2 * s_ + gap
    box_top, box_bottom = grid_bottom + 18 * k, h - 120 * k                       # leaves room for the badge and the progress bar
    body = ctx.get("title", "").replace("[Playlist]", "").strip() or concept_text(ctx)
    lines, f = fit_box(body.upper(), w * 0.92, box_bottom - box_top, 100 * k, 40 * k, "Montserrat.ttf", 800, max_lines=3, spacing=1.04)
    draw_block(img, lines, f, w / 2, (box_top + box_bottom) / 2, k, spacing=1.04)
    d = ImageDraw.Draw(img)                               # decorative video-length badge and progress bar
    mins = int(ctx.get("minutes") or 20)
    badge = f"{mins}:{int((ctx.get('minutes') or 0) * 60) % 60:02d}"
    bx, by, bw, bh = w - int(210 * k), h - int(96 * k), int(180 * k), int(56 * k)
    d.rounded_rectangle([bx, by, bx + bw, by + bh], int(14 * k), fill=(15, 15, 15, 215))
    cx, cy, tr = bx + 34 * k, by + bh / 2, 11 * k                      # a small play triangle (the fonts have no note glyph)
    d.polygon([(cx - tr * 0.6, cy - tr), (cx - tr * 0.6, cy + tr), (cx + tr, cy)], fill=(255, 255, 255))
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


def _glow(img, xy, r, colour, alpha=170):
    """A soft coloured light behind something (xy = centre, r = radius)."""
    g = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([xy[0] - r, xy[1] - r, xy[0] + r, xy[1] + r], fill=(*colour, alpha))
    img.alpha_composite(g.filter(ImageFilter.GaussianBlur(r * 0.45)))


def _headline(ctx):
    return ctx.get("title", "").replace("[Playlist]", "").strip() or concept_text(ctx)


def lay_record(w, h, v, covers, ctx):
    """A big vinyl record on the right with the first cover as its label, two covers leaning on it, the title big on the left."""
    k = w / 1280
    dark, light, acc = COL[v]
    img = bg_swirl(w, h, v)
    cx, cy, R = w * 0.70, h * 0.52, h * 0.44
    _glow(img, (cx, cy), R * 1.15, light, 120)
    d = ImageDraw.Draw(img)
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=(10, 10, 12, 255))
    for i in range(1, 22):                                               # fine grooves
        r = R * (0.36 + 0.62 * i / 22)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(34 + (i % 3) * 8,) * 3 + (255,), width=max(1, int(1.5 * k)))
    sheen = Image.new("RGBA", img.size, (0, 0, 0, 0))                    # a light streak across the record
    ImageDraw.Draw(sheen).polygon([(cx, cy), (cx + R * 1.1, cy - R * 0.5), (cx + R * 1.1, cy - R * 0.2)], fill=(255, 255, 255, 40))
    img.alpha_composite(sheen.filter(ImageFilter.GaussianBlur(10 * k)))
    cs = pick_covers(covers, 3)
    label = int(R * 0.62)
    lab = rounded(Image.open(cs[0]).convert("RGB").resize((label, label), Image.LANCZOS), label // 2)
    img.alpha_composite(lab, (int(cx - label / 2), int(cy - label / 2)))
    d.ellipse([cx - 7 * k, cy - 7 * k, cx + 7 * k, cy + 7 * k], fill=(10, 10, 12, 255))
    place_cover(img, cs[1], w * 0.52, h * 0.74, int(190 * k), angle=8, k=k)
    place_cover(img, cs[2], w * 0.57, h * 0.30, int(150 * k), angle=-8, k=k)
    text(img, (w * 0.27, h * 0.12), HEADER, font("PlayfairDisplay.ttf", int(54 * k), 600), k=k, tracking=int(8 * k))
    lines, f = fit_box(_headline(ctx).upper(), w * 0.42, h * 0.5, 96 * k, 36 * k, "Montserrat.ttf", 800, max_lines=4, spacing=1.04)
    draw_block(img, lines, f, w * 0.25, h * 0.52, k, spacing=1.04)
    return img


def lay_cascade(w, h, v, covers, ctx):
    """Six covers stepping down a diagonal, each overlapping the last, the big title beside them."""
    k = w / 1280
    dark, light, acc = COL[v]
    img = bg_swirl(w, h, v)
    cs = pick_covers(covers, 6)
    s = int(230 * k)
    for i, c in enumerate(cs):
        x = w * (0.50 + 0.095 * i)
        y = h * (0.20 + 0.115 * i)
        place_cover(img, c, x, y, s, angle=-6 + i * 2, k=k)
    text(img, (w * 0.22, h * 0.12), HEADER, font("PlayfairDisplay.ttf", int(54 * k), 600), k=k, tracking=int(8 * k))
    lines, f = fit_box(_headline(ctx).upper(), w * 0.40, h * 0.55, 92 * k, 34 * k, "Montserrat.ttf", 800, max_lines=4, spacing=1.04)
    draw_block(img, lines, f, w * 0.23, h * 0.55, k, spacing=1.04)
    return img


def lay_hero(w, h, v, covers, ctx):
    """One big cover glowing in the middle, small covers lined up under it, the title across the bottom."""
    k = w / 1280
    dark, light, acc = COL[v]
    img = bg_swirl(w, h, v)
    cs = pick_covers(covers, 6)
    _glow(img, (w / 2, h * 0.36), h * 0.42, acc, 110)
    text(img, (w / 2, h * 0.06), HEADER, font("PlayfairDisplay.ttf", int(46 * k), 600), k=k, tracking=int(8 * k))
    place_cover(img, cs[0], w / 2, h * 0.34, int(300 * k), k=k, radius=int(14 * k))
    sm, gap = int(104 * k), int(16 * k)
    x0 = w / 2 - (5 * sm + 4 * gap) / 2 + sm / 2
    for i, c in enumerate(cs[1:]):
        place_cover(img, c, x0 + i * (sm + gap), h * 0.66, sm, k=k)
    lines, f = fit_box(_headline(ctx).upper(), w * 0.9, h * 0.2, 84 * k, 34 * k, "Montserrat.ttf", 800, max_lines=2, spacing=1.04)
    draw_block(img, lines, f, w / 2, h * 0.84, k, spacing=1.04)
    return img


def lay_filmstrip(w, h, v, covers, ctx):
    """Covers on a tilted film strip across the picture, the title in a box over the lower part."""
    k = w / 1280
    dark, light, acc = COL[v]
    img = bg_swirl(w, h, v)
    cs = pick_covers(covers, 6)
    strip = Image.new("RGBA", (int(w * 1.5), int(190 * k)), (0, 0, 0, 0))
    sd = ImageDraw.Draw(strip)
    sd.rectangle([0, 0, strip.size[0], strip.size[1]], fill=(8, 8, 10, 235))
    for x in range(int(14 * k), strip.size[0], int(34 * k)):                  # the holes along both edges
        for y in (int(8 * k), strip.size[1] - int(22 * k)):
            sd.rounded_rectangle([x, y, x + int(18 * k), y + int(14 * k)], int(3 * k), fill=(70, 70, 76, 255))
    sz = int(140 * k)
    for i, c in enumerate(cs):
        cv = rounded(Image.open(c).convert("RGB").resize((sz, sz), Image.LANCZOS), int(4 * k))
        strip.alpha_composite(cv, (int(strip.size[0] / 2 - 3 * (sz + 18 * k) + i * (sz + 18 * k) + 9 * k), int(25 * k)))
    strip = strip.rotate(-7, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(strip, (int(w / 2 - strip.size[0] / 2), int(h * 0.30 - strip.size[1] / 2)))
    text(img, (w / 2, h * 0.07), HEADER, font("PlayfairDisplay.ttf", int(50 * k), 600), k=k, tracking=int(8 * k))
    lines, f = fit_box(_headline(ctx).upper(), w * 0.92, h * 0.34, 98 * k, 38 * k, "Montserrat.ttf", 800, max_lines=3, spacing=1.04)
    draw_block(img, lines, f, w / 2, h * 0.78, k, spacing=1.04)
    return img


LAYOUTS = {"night": lay_night, "swirl": lay_swirl, "sunset": lay_sunset, "sky": lay_sky, "bold": lay_bold, "season": lay_season, "poster": lay_poster, "record": lay_record, "cascade": lay_cascade, "hero": lay_hero, "filmstrip": lay_filmstrip}


def render(family, variant, covers, ctx=None, size=(1280, 720)):
    ctx = ctx or {}
    fam = next((f for f in FAMILIES if f["id"] == family), None)
    if not fam or variant not in fam["variants"]:
        raise ValueError(f"unknown thumbnail style {family}/{variant}")
    return LAYOUTS[family](size[0], size[1], variant, covers, ctx).convert("RGB")


def cache_key(family, variant, covers, ctx, size):
    sig = repr((family, variant, [(c, os.path.getmtime(c)) for c in covers if c and os.path.exists(c)], ctx.get("moods"),
                ctx.get("title"), ctx.get("thumb_text"), round(ctx.get("minutes") or 0), size))
    return hashlib.sha1(sig.encode()).hexdigest()[:12]


def save_jpeg(img, path, max_bytes=1_900_000):
    """YouTube accepts thumbnails up to 2 MB: lower the quality until the file fits."""
    for q in (92, 88, 84, 78, 70):
        img.save(path, "JPEG", quality=q, optimize=True)
        if os.path.getsize(path) <= max_bytes:
            break
    return path


def write_selected(project, stem, minutes):
    """The thumbnails you picked, written as <stem>.thumbnail-A/B/C.jpg (A is also <stem>.thumbnail.jpg). Letters that are no longer picked
    are removed, so an old B or C can never be uploaded by mistake. Needs only the covers: no video. Returns the written paths."""
    picked = (project.get("thumbs_selected") or [])[:3]
    prof = project.get("profile") or {}
    ctx = {"moods": [m.strip() for m in (project.get("mood") or "").split(",") if m.strip()] or prof.get("moods", []),
           "title": project.get("youtube_title") or (project.get("desc_meta") or {}).get("title", ""),
           "thumb_text": project.get("thumb_text", ""), "minutes": minutes}
    covers = [t["cover"] for t in project["tracks"] if t.get("cover")]
    written = []
    for letter, sel in zip("ABC", picked):
        img = render(sel["family"], sel["variant"], covers, ctx)
        path = f"{stem}.thumbnail-{letter}.jpg"
        save_jpeg(img, path)
        written.append(path)
        if letter == "A":
            save_jpeg(img, stem + ".thumbnail.jpg")
    for letter in "ABC"[len(picked):]:
        old = f"{stem}.thumbnail-{letter}.jpg"
        if os.path.exists(old):
            os.remove(old)
    return written
