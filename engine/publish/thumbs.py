"""Thumbnail families, drawn from the project's own song covers. Seven styles learned from eight reference thumbnails
(their views are kept in REFERENCE), each in six colour variants. Nothing is downloaded: backgrounds are drawn here.

render(family, variant, covers, ctx, size=(1280, 720)) -> PIL image
ctx: {"title": YouTube title, "moods": [...], "minutes": float}
Text rule: header-style families always say "PlayList" (never the playlist's own name); concept-style families use a
phrase picked from the detected mood (never the name either)."""
import hashlib
import math
import os
import re

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FONTS = os.path.join(os.path.dirname(__file__), "fonts")
HEADER = "PlayList"

REFERENCE = {   # what the reference thumbnails did (views as seen); the dark-moody styles below are learned from your chosen dark YouTube references
    "aura": {"views": 0, "note": "Asymmetric dark-blend colour sweep with glowing light contrast, clean sans 'Playlist', and a 2x3 cover grid (inspired by encore.)."},
    "prism": {"views": 0, "note": "Vertical fluted frosted glass refracting moody dark colour blends behind 'Playlist' and a 2x3 cover grid."},
    "silk": {"views": 0, "note": "Chiaroscuro spotlight beams and metallic liquid satin folds on deep shadow, luxury serif 'Playlist', and a 2x3 cover grid (inspired by No..Hardyy)."},
    "eclipse": {"views": 0, "note": "Glowing dual-tone solar eclipse halo framing a dark center orb behind 'Playlist' and a 2x3 cover grid."},
    "wave": {"views": 0, "note": "Sculpted grainy 3D silk wave on textured obsidian, large serif 'Playlist', and a clean 1x4 bottom cover strip (inspired by No..Hardyy)."},
    "horizon": {"views": 0, "note": "Warm luminous horizon glow rising into a deep starless dark sky, clean sans 'Playlist', and a 1x4 bottom cover strip."},
    "night": {"views": 3840035, "note": "Night photo, big concept title, the covers of your songs around it (up to six). Darkest of the eight and the most viewed."},
    "swirl": {"views": 2846410, "note": "Black-and-white swirl, serif 'Playlist', six covers. Second most viewed, also very dark."},
    "sunset": {"views": 485216, "note": "Sunset bokeh, small sans 'Playlist', six covers."},
    "bold": {"views": 71796, "note": "Huge bold title, six covers, video-time badge and progress bar."},
    "poster": {"views": 0, "note": "Our own: three large covers fanned out on a dark gradient. No reference yet: test it."},
    "room": {"views": 0, "note": "Warm dark room with window light, a record player and a plant; your covers as little prints, 'PlayList' in cream italic and the channel name at the bottom."},
    "strip": {"views": 0, "note": "Your covers side by side across the whole picture, a big warm 3D title with sparkles over them."},
    "chrome": {"views": 0, "note": "Dark swirl, a big silver 'PlayList', your covers in one row underneath."},
    "tracklist": {"views": 0, "note": "Dark grainy blue with a glowing picture, 'PlayList' on top and a list of the song names with their small covers."},
}
FAMILIES = [
    {"id": "aura", "label": "Dark blend mesh", "variants": [
        "teal", "dusk", "cobalt", "emerald", "crimson", "amber",
        "magenta", "forest_gold", "copper_teal", "plum_peach", "ice", "blood_violet",
        "mocha_rose", "aurora_violet", "bronze_navy", "sage", "sapphire", "sunset_lilac",
    ]},
    {"id": "prism", "label": "Fluted glass", "variants": ["twilight", "ocean", "ember", "emerald", "crimson", "violet", "gold", "mono"]},
    {"id": "silk", "label": "Liquid silk & beams", "variants": ["silver_beam", "ice_silk", "rose_silk", "gold_silk", "violet_silk", "teal_silk", "crimson_silk", "emerald_silk"]},
    {"id": "eclipse", "label": "Eclipse halo", "variants": ["violet_peach", "cyan_blue", "crimson_gold", "emerald_teal", "magenta_indigo", "amber_noir", "silver", "sapphire"]},
    {"id": "wave", "label": "Grainy 3D wave (4-cover)", "variants": ["silver", "cyan_violet", "crimson", "gold", "emerald", "cobalt", "rose", "amber"]},
    {"id": "horizon", "label": "Midnight horizon (4-cover)", "variants": ["crimson", "amber", "violet", "teal", "rose", "emerald", "cobalt", "gold"]},
    {"id": "night", "label": "Late night", "variants": ["blue", "purple", "teal", "crimson", "amber", "green"]},
    {"id": "swirl", "label": "Dark swirl", "variants": ["mono", "blue", "violet", "wine", "teal", "sepia"]},
    {"id": "sunset", "label": "Sunset glow", "variants": ["orange", "pink", "violet", "gold", "rose", "dusk"]},
    {"id": "bold", "label": "Big bold title", "variants": ["mono", "blue", "violet", "crimson", "teal", "amber"]},
    {"id": "poster", "label": "Fanned poster", "variants": ["ink", "blue", "plum", "forest", "ember", "slate"]},
    {"id": "room", "label": "Warm room", "variants": ["sepia", "wine", "teal", "blue", "violet", "mono"]},
    {"id": "strip", "label": "Cover strip", "variants": ["amber", "crimson", "teal", "blue", "purple", "green"]},
    {"id": "chrome", "label": "Silver on dark", "variants": ["mono", "blue", "violet", "wine", "teal", "sepia"]},
    {"id": "tracklist", "label": "Track list", "variants": ["blue", "violet", "teal", "wine", "mono", "sepia"]},
]
LEGACY = {"record": "room", "cascade": "strip", "hero": "room", "filmstrip": "strip",
          "pastel": "aura", "sky": "aura", "season": "horizon"}      # removed/light styles: saved picks map cleanly to dark styles
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


def place_cover(base, path, x, y, s, angle=0, shadow=True, radius=None, k=1.0, frame=0, frame_color=(238, 230, 216)):
    """Cover thumbnail with a soft drop shadow, optionally rotated and with a paper-like frame. (x, y) = centre."""
    im = Image.open(path).convert("RGB")
    if frame:
        canvas = Image.new("RGB", (s, s), frame_color)
        canvas.paste(im.resize((s - 2 * frame, s - 2 * frame), Image.LANCZOS), (frame, frame))
        im = canvas
    else:
        im = im.resize((s, s), Image.LANCZOS)
    cv = rounded(im, radius if radius is not None else max(2, round(4 * k)))
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


# ---------- shared pieces ----------
PASTEL = {    # sky top, sky bottom, accent
    "peach": ((255, 185, 155), (255, 228, 205), (255, 110, 100)), "pink": ((255, 150, 195), (255, 218, 232), (255, 80, 165)),
    "lilac": ((165, 145, 230), (238, 218, 250), (150, 85, 230)), "sky": ((110, 175, 255), (218, 238, 255), (60, 125, 255)),
    "mint": ((125, 218, 198), (222, 250, 236), (30, 165, 135)), "gold": ((255, 198, 105), (255, 236, 188), (240, 145, 25)),
}
COLS = {1: 1, 2: 2, 3: 3, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 3, 10: 5, 11: 4, 12: 4}


def grid_rows(n):
    """How many covers go in each row for n covers: 3 -> [3], 4 -> [2, 2], 5 -> [3, 2], 6 -> [3, 3], 7 -> [4, 3], 9 -> [3, 3, 3] ..."""
    cols, rows, left = COLS.get(n, 4), [], n
    while left > 0:
        rows.append(min(cols, left))
        left -= cols
    return rows


def place_grid(img, covers, box, gap, k, frame=0, frame_color=(238, 230, 216)):
    """Lay all the covers out in neat rows inside box = (x, y, w, h); the last row is centred. Returns the cover size."""
    x0, y0, bw, bh = box
    rows = grid_rows(len(covers))
    nc = max(rows)
    s = int(min((bw - gap * (nc - 1)) / nc, (bh - gap * (len(rows) - 1)) / len(rows)))
    y = y0 + (bh - (len(rows) * s + (len(rows) - 1) * gap)) / 2
    i = 0
    for cnt in rows:
        x = x0 + (bw - (cnt * s + (cnt - 1) * gap)) / 2
        for j in range(cnt):
            place_cover(img, covers[i], x + s / 2 + j * (s + gap), y + s / 2, s, k=k, frame=frame, frame_color=frame_color)
            i += 1
        y += s + gap
    return s


def pick_indices(total, n):
    """n positions out of `total`, spread evenly over the whole list (first and last included)."""
    if total <= n:
        return list(range(total))
    return [round(i * (total - 1) / (n - 1)) for i in range(n)] if n > 1 else [0]


def fill_crop(path, w, h):
    im = Image.open(path).convert("RGB")
    sc = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS)
    l, t = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))


def glow_text(img, xy, s, f, fill, glow, k, radius=14, strength=230):
    g = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).text(xy, s, font=f, fill=(*glow, strength), anchor="mm")
    img.alpha_composite(g.filter(ImageFilter.GaussianBlur(radius * k)))
    ImageDraw.Draw(img).text(xy, s, font=f, fill=fill, anchor="mm")


def sparkle(d, x, y, r, fill):
    q = r * 0.22
    d.polygon([(x, y - r), (x + q, y - q), (x + r, y), (x + q, y + q), (x, y + r), (x - q, y + q), (x - r, y), (x - q, y - q)], fill=fill)


def silver_text(img, xy, s, f, k):
    """Text filled with a vertical silver gradient and a soft shadow underneath."""
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text(xy, s, font=f, fill=255, anchor="mm")
    box = mask.getbbox() or (0, 0, w, h)
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh.paste((0, 0, 0, 170), (0, int(8 * k)), mask)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10 * k)))
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    shade = 0.62 + 0.38 * np.abs(np.cos((t - box[1] / h) / max(1e-3, (box[3] - box[1]) / h) * np.pi * 1.1))
    col = np.stack([shade * 232, shade * 234, shade * 240], axis=-1)
    layer = Image.fromarray(np.clip(np.repeat(col, w, axis=1), 0, 255).astype(np.uint8)).convert("RGBA")
    layer.putalpha(mask)
    img.alpha_composite(layer)


def bg_swirl(w, h, v):
    from ..look import background
    dark, light, acc = COL[v]
    f = background._frame(w // 3, h // 3, 0.9, dark, light, scale=2.4, warp=1.0, iters=3, phase=1.7, contrast=1, gamma=1.6)
    img = to_img(f.astype(np.float32)).resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6))
    return vignette(grain(img, 5), 0.4).convert("RGBA")


def _phrase(ctx):
    """The short phrase of the style: the words you typed, else one that fits the mood (never the playlist's name)."""
    return concept_text(ctx)


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



# ---------- the earlier styles (every one of them uses as many covers as you have) ----------
def lay_night(w, h, v, covers, ctx):
    """1-4 songs: placed around the title (corners for four); 5 or more: covers above and below the title, split evenly."""
    k = w / 1280
    img = bg_night(w, h, v)
    cs = pick_covers(covers, min(real_count(covers), 8))
    n = len(cs)
    if n <= 4:
        s_ = int(250 * k)
        spots = {1: [(0.5, 0.2)], 2: [(0.27, 0.22), (0.73, 0.78)], 3: [(0.27, 0.22), (0.73, 0.22), (0.5, 0.8)],
                 4: [(0.27, 0.22), (0.73, 0.22), (0.27, 0.78), (0.73, 0.78)]}[n]
    else:
        top, bot = (n + 1) // 2, n // 2
        s_ = int(min(192 * k, (w * 0.9 - 20 * k * (top - 1)) / top))
        spots = [((i + 0.5) / top, 0.21) for i in range(top)] + [((i + 0.5) / bot, 0.79) for i in range(bot)]
    for (fx, fy), c in zip(spots, cs):
        place_cover(img, c, w * fx, h * fy, s_, k=k)
    accent = tuple(min(255, int(c * 1.05)) for c in COL[v][2])
    lines, f = fit_box(concept_text(ctx), w * 0.84, h * 0.20, 100 * k, 44 * k, "PlayfairDisplay.ttf", 700, max_lines=2)
    draw_block(img, lines, f, w / 2, h * 0.5, k, fill=accent)
    return img


def lay_grid(w, h, img, covers, header, hfont, k, size=210, top=0.1, fill=(255, 255, 255), tracking=0):
    cs = pick_covers(covers, min(real_count(covers), 12))
    text(img, (w / 2, h * top), header, hfont, fill=fill, k=k, tracking=tracking)
    y0 = h * (top + 0.1) + 14 * k
    place_grid(img, cs, (w * 0.17, y0, w * 0.66, h * 0.95 - y0), int(34 * k), k)
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
    cs = pick_covers(covers, min(real_count(covers), 9))
    place_grid(img, cs, (w * 0.04, h * 0.1, w * 0.52, h * 0.8), int(22 * k), k)
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
    cs = pick_covers(covers, min(real_count(covers), 8))
    s_, gap = int(128 * k), int(20 * k)
    text(img, (w / 2, h * 0.065), HEADER, font("PlayfairDisplay.ttf", int(52 * k), 600), k=k, tracking=int(8 * k))
    top = h * 0.115
    place_grid(img, cs, (w * 0.2, top, w * 0.6, 2 * s_ + gap), gap, k)
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
    """All your covers fanned out (up to seven), the middle one in front and largest."""
    k = w / 1280
    img = bg_poster(w, h, v)
    cs = pick_covers(covers, min(real_count(covers), 7))
    n = len(cs)
    mid = (n - 1) / 2
    step = 0.19 if n <= 3 else 0.62 / (n - 1)
    base = min(330 * k, step * w * 1.55) if n > 3 else 330 * k
    for i in sorted(range(n), key=lambda i: -abs(i - mid)):                            # the outer ones first, the middle one last (on top)
        d = i - mid
        size = int(base * max(0.6, 1 - 0.1 * abs(d)))
        place_cover(img, cs[i], w * (0.5 + d * step), h * (0.5 + 0.06 * abs(d)), size, angle=-7 * d if n <= 3 else -14 * d / max(1, mid), k=k)
    text(img, (w / 2, h * 0.11), HEADER, font("Montserrat.ttf", int(56 * k), 600), k=k, tracking=int(22 * k), fill=COL[v][2])
    return img


# ---------- styles ----------
def lay_strip(w, h, v, covers, ctx):
    """Your covers side by side across the whole picture, a big warm 3D title with sparkles over them."""
    k = w / 1280
    dark, light, acc = COL[v]
    cs = pick_covers(covers, min(real_count(covers), 8))
    n = len(cs)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    edges = [round(i * w / n) for i in range(n + 1)]
    for i, c in enumerate(cs):
        img.paste(fill_crop(c, edges[i + 1] - edges[i] + 1, h), (edges[i], 0))
    ramp = np.clip((np.linspace(0, 1, h) - 0.22) / 0.55, 0, 1) ** 1.2 * 200 + 40            # darker where the words are
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shade.putalpha(Image.fromarray(np.repeat(ramp[:, None], w, axis=1).astype(np.uint8)))
    img.alpha_composite(shade)
    d = ImageDraw.Draw(img)
    colour = tuple(min(255, int(c * 1.05)) for c in light)
    pad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(pad).ellipse([w * 0.30, h * 0.36, w * 0.70, h * 0.57], fill=(0, 0, 0, 150))
    img.alpha_composite(pad.filter(ImageFilter.GaussianBlur(26 * k)))
    text(img, (w / 2, h * 0.47), HEADER, font("PlayfairDisplay-Italic.ttf", int(78 * k), 600), fill=(252, 244, 230), k=k)
    lines, f = fit_box(_phrase(ctx), w * 0.86, h * 0.34, 150 * k, 56 * k, "Montserrat.ttf", 800, max_lines=2, spacing=1.0)
    lh = f.size * 1.0
    y0 = h * 0.70 - lh * (len(lines) - 1) / 2
    for j, ln in enumerate(lines):
        y = y0 + j * lh
        for off in range(int(9 * k), 0, -1):                                              # the 3D edge
            d.text((w / 2 + off * 0.9, y + off), ln, font=f, fill=tuple(int(c * 0.28) for c in light), anchor="mm")
        d.text((w / 2, y), ln, font=f, fill=colour, anchor="mm")
    tw = max(d.textlength(x, font=f) for x in lines)
    sparkle(d, w / 2 - tw / 2 - 30 * k, h * 0.58, 26 * k, colour)
    sparkle(d, w / 2 + tw / 2 + 30 * k, h * 0.82, 20 * k, colour)
    sparkle(d, w / 2 - tw / 2 - 8 * k, h * 0.84, 12 * k, colour)
    return img


def lay_pastel(w, h, v, covers, ctx):
    """Soft sunset sky, a glowing italic 'PlayList', all your covers in a neat framed grid."""
    k = w / 1280
    top, bot, acc = PASTEL[v]
    img = to_img(grad(w, h, top, bot)).convert("RGBA")
    rng = np.random.default_rng(7)
    for _ in range(9):                                                                    # soft clouds
        cl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cx, cy, rx, ry = rng.uniform(0, w), rng.uniform(h * 0.05, h * 0.95), rng.uniform(120, 300) * k, rng.uniform(25, 60) * k
        ImageDraw.Draw(cl).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(255, 255, 255, int(rng.uniform(50, 110))))
        img.alpha_composite(cl.filter(ImageFilter.GaussianBlur(22 * k)))
    glow_text(img, (w / 2, h * 0.115), HEADER, font("PlayfairDisplay-Italic.ttf", int(104 * k), 600), (255, 255, 255), acc, k, radius=16, strength=255)
    cs = pick_covers(covers, min(real_count(covers), 12))
    place_grid(img, cs, (w * 0.17, h * 0.235, w * 0.66, h * 0.72), int(16 * k), k, frame=int(5 * k), frame_color=(255, 255, 255))
    return to_img(grain(img.convert("RGB"), 3)).convert("RGBA")


def lay_chrome(w, h, v, covers, ctx):
    """Dark swirl, a big silver 'PlayList', your covers in one row underneath."""
    k = w / 1280
    img = bg_swirl(w, h, v)
    silver_text(img, (w / 2, h * 0.36), HEADER, font("Montserrat.ttf", int(168 * k), 700), k)
    cs = pick_covers(covers, min(real_count(covers), 8))
    n, gap = len(cs), int(20 * k)
    s = int(min(190 * k, (w * 0.86 - gap * (n - 1)) / n))
    x0 = w / 2 - (n * s + (n - 1) * gap) / 2 + s / 2
    for i, c in enumerate(cs):
        place_cover(img, c, x0 + i * (s + gap), h * 0.72, s, k=k, radius=int(3 * k))
    return img


def lay_tracklist(w, h, v, covers, ctx):
    """A glowing picture, 'PlayList' on top and the song names with their small covers."""
    k = w / 1280
    dark, light, acc = COL[v]
    real = [c for c in covers if c and os.path.exists(c)]
    titles = [str(x) for x in (ctx.get("tracks") or [])]
    idx = pick_indices(len(real), min(len(real), 9))
    base = grad(w, h, tuple(int(c * 1.4) for c in dark), tuple(int(c * 0.5) for c in dark))
    img = to_img(base).convert("RGBA")
    art = Image.open(real[idx[len(idx) // 2]]).convert("RGB").resize((int(h * 0.9), int(h * 0.9)), Image.LANCZOS).filter(ImageFilter.GaussianBlur(26 * k))
    haze = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    haze.paste(art.convert("RGBA"), (int(w * 0.55), int(h * 0.08)))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse([w * 0.58, h * 0.12, w * 0.98, h * 0.92], fill=170)
    haze.putalpha(mask.filter(ImageFilter.GaussianBlur(50 * k)))
    img.alpha_composite(haze)
    _glow(img, (w * 0.77, h * 0.52), h * 0.30, light, 110)
    place_cover(img, real[idx[len(idx) // 2]], w * 0.77, h * 0.52, int(h * 0.42), k=k, radius=int(10 * k))
    text(img, (w / 2, h * 0.095), HEADER, font("Montserrat.ttf", int(70 * k), 600), k=k, tracking=int(10 * k))
    n = len(idx)
    area_top, area_h = h * 0.20, h * 0.74
    row = min(70 * k, area_h / n)
    thumb = int(row * 0.84)
    f = font("Montserrat.ttf", max(15, int(row * 0.44)), 500)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    max_w = w * 0.50 - thumb - 22 * k
    for r, i in enumerate(idx):
        y = area_top + row * r + row / 2
        place_cover(img, real[i], w * 0.075 + thumb / 2, y, thumb, k=k, shadow=False, radius=int(3 * k))
        name = titles[i] if i < len(titles) and titles[i] else f"Song {i + 1}"
        while probe.textlength(name, font=f) > max_w and len(name) > 4:
            name = name[:-2].rstrip() + "…" if not name.endswith("…") else name[:-2] + "…"
        ImageDraw.Draw(img).text((w * 0.075 + thumb + 22 * k, y), name, font=f, fill=(244, 246, 252), anchor="lm")
    return to_img(grain(img.convert("RGB"), 9)).convert("RGBA")


def _glow(img, xy, r, colour, alpha=170):
    """A soft coloured light behind something (xy = centre, r = radius)."""
    g = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([xy[0] - r, xy[1] - r, xy[0] + r, xy[1] + r], fill=(*colour, alpha))
    img.alpha_composite(g.filter(ImageFilter.GaussianBlur(r * 0.45)))


def lay_room(w, h, v, covers, ctx):
    """A dark warm room: window light across the wall, a record player and a plant; the covers as little prints, 'PlayList' and your channel name."""
    k = w / 1280
    dark, light, acc = COL[v]
    warm = tuple(int(0.45 * a + 0.55 * b) for a, b in zip((120, 90, 62), light))
    img = to_img(grad(w, h, tuple(int(c * 0.6 + 26) for c in dark), tuple(int(c * 0.3 + 8) for c in dark))).convert("RGBA")
    bars = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bars)
    for i in range(3):                                                                    # light through the window
        x = w * (0.18 + 0.1 * i)
        bd.polygon([(x, 0), (x + 90 * k, 0), (x + 360 * k, h * 0.8), (x + 250 * k, h * 0.8)], fill=(*warm, 135))
    img.alpha_composite(bars.filter(ImageFilter.GaussianBlur(16 * k)))
    leaves = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld, rng = ImageDraw.Draw(leaves), np.random.default_rng(3)
    for _ in range(16):
        cx, cy = w * rng.uniform(0.86, 1.02), h * rng.uniform(0.0, 0.55)
        ang = rng.uniform(-0.9, 0.9)
        pts = [(cx + np.cos(ang + t) * 120 * k * (1 - abs(t) / 2.4) * np.sign(1.0), cy + np.sin(ang + t) * 36 * k) for t in np.linspace(-1.2, 1.2, 9)]
        ld.polygon([(cx, cy)] + pts, fill=(12, 20, 10, 235))
    img.alpha_composite(leaves.filter(ImageFilter.GaussianBlur(1.5 * k)))
    disc = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc)
    cx, cy, rx, ry = -w * 0.02, h * 0.86, w * 0.30, h * 0.20
    dd.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(8, 8, 9, 255))
    for i in range(1, 9):
        a = 0.35 + 0.08 * i
        dd.ellipse([cx - rx * a, cy - ry * a, cx + rx * a, cy + ry * a], outline=(40, 38, 36, 255), width=max(1, int(1.5 * k)))
    img.alpha_composite(disc)
    img = to_img(grain(vignette(img.convert("RGB"), 0.6), 6)).convert("RGBA")
    cream = (246, 236, 216)
    text(img, (w / 2, h * 0.175), HEADER, font("PlayfairDisplay-Italic.ttf", int(160 * k), 600), fill=cream, k=k)
    cs = pick_covers(covers, min(real_count(covers), 9))
    place_grid(img, cs, (w * 0.27, h * 0.34, w * 0.46, h * 0.52), int(16 * k), k, frame=int(6 * k), frame_color=(228, 222, 210))
    d = ImageDraw.Draw(img)
    name = (ctx.get("channel") or "senora").strip().lower()
    y = h * 0.915
    d.line([(w * 0.18, y), (w * 0.41, y)], fill=(*cream, 150), width=max(1, int(2 * k)))
    d.line([(w * 0.59, y), (w * 0.82, y)], fill=(*cream, 150), width=max(1, int(2 * k)))
    d.text((w / 2, y), name, font=font("PlayfairDisplay-Italic.ttf", int(48 * k), 500), fill=cream, anchor="mm")
    return img


# ---------- dark-moody aesthetic families (mesh blends, fluted glass, liquid silk, eclipse halo, 3D wave, horizon) ----------
def _mesh_bg(w, h, base_rgb, blobs, warp_amp=0.04, phase=0.5):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    xn, yn = x / max(w, 1), y / max(h, 1)
    if warp_amp > 0:
        xw = xn + warp_amp * np.sin(yn * 4.0 + phase)
        yw = yn + warp_amp * np.cos(xn * 3.5 - phase)
    else:
        xw, yw = xn, yn
    acc = np.zeros((h, w, 3), dtype=np.float32)
    acc[:] = np.array(base_rgb, dtype=np.float32)
    for (bx, by, rx, ry, rot_deg, col, strength, power) in blobs:
        rad = math.radians(rot_deg)
        dx, dy = xw - bx, yw - by
        u = dx * math.cos(rad) + dy * math.sin(rad)
        v = -dx * math.sin(rad) + dy * math.cos(rad)
        d2 = (u / rx) ** 2 + (v / ry) ** 2
        wm = np.clip(np.exp(-(d2 ** power)) * strength, 0.0, 1.0)[..., None]
        acc = acc * (1.0 - wm) + np.array(col, dtype=np.float32) * wm
    return Image.fromarray(np.clip(acc, 0, 255).astype(np.uint8))


def _place_strip4(img, covers, w, h, k, cy_frac=0.72):
    cs = pick_covers(covers, min(real_count(covers), 4))
    n = len(cs)
    if not n:
        return
    s = int(min(210 * k, (w * 0.84 - 40 * k * max(0, n - 1)) / n))
    gap = int(44 * k)
    total_w = n * s + (n - 1) * gap
    x0 = (w - total_w) / 2
    cy = h * cy_frac
    for i, c in enumerate(cs):
        place_cover(img, c, x0 + s / 2 + i * (s + gap), cy, s, k=k)


def _place_grid6(img, covers, w, h, k, top_y_frac=0.265):
    cs = pick_covers(covers, min(real_count(covers), 6))
    y0 = h * top_y_frac
    place_grid(img, cs, (w * 0.17, y0, w * 0.66, h * 0.94 - y0), int(34 * k), k)


# 18 rich dark-blend colour presets for `aura` (base, blobs, use_serif, phase)
AURA_PRESETS = {
    "teal": ((9, 25, 42), [
        (0.03, 0.45, 0.14, 0.55, 0, (4, 8, 16), 0.92, 1.1),
        (0.24, 0.18, 0.16, 0.42, -22, (62, 128, 148), 0.78, 1.0),
        (0.45, 0.88, 0.34, 0.28, -10, (92, 162, 172), 0.88, 1.0),
        (0.18, 0.95, 0.28, 0.24, 10, (118, 182, 190), 0.90, 1.0),
        (0.88, 0.25, 0.30, 0.45, 0, (16, 44, 68), 0.70, 1.0),
        (0.92, 0.92, 0.28, 0.30, 0, (5, 11, 24), 0.85, 1.0),
    ], False, 0.5),
    "dusk": ((16, 22, 42), [
        (0.12, 0.30, 0.42, 0.52, -15, (215, 148, 138), 0.95, 1.0),
        (0.32, 0.18, 0.28, 0.35, 10, (182, 122, 128), 0.72, 1.0),
        (0.42, 0.86, 0.36, 0.32, 0, (108, 128, 165), 0.85, 1.0),
        (0.62, 0.48, 0.28, 0.42, 0, (48, 52, 92), 0.75, 1.0),
        (0.92, 0.20, 0.26, 0.42, 0, (7, 10, 18), 0.95, 1.1),
        (0.88, 0.88, 0.30, 0.35, 0, (6, 8, 14), 0.95, 1.1),
    ], False, 0.4),
    "cobalt": ((32, 33, 52), [
        (0.42, 0.15, 0.24, 0.36, 12, (108, 114, 212), 0.82, 1.0),
        (0.18, 0.68, 0.34, 0.44, -18, (145, 142, 232), 0.90, 1.0),
        (0.14, 0.92, 0.32, 0.28, 0, (212, 182, 228), 0.92, 1.0),
        (0.45, 0.92, 0.28, 0.24, 0, (128, 134, 224), 0.80, 1.0),
        (0.85, 0.55, 0.32, 0.55, 0, (24, 25, 38), 0.88, 1.0),
    ], False, 0.6),
    "emerald": ((6, 16, 22), [
        (0.20, 0.32, 0.42, 0.50, -20, (36, 175, 132), 0.88, 1.0),
        (0.75, 0.78, 0.40, 0.44, 15, (28, 125, 155), 0.84, 1.0),
        (0.88, 0.18, 0.30, 0.42, 0, (5, 12, 18), 0.94, 1.1),
        (0.12, 0.90, 0.30, 0.32, 0, (6, 22, 26), 0.82, 1.0),
    ], False, 0.7),
    "crimson": ((12, 5, 10), [
        (0.18, 0.78, 0.42, 0.46, -20, (195, 36, 62), 0.92, 1.0),
        (0.08, 0.28, 0.30, 0.42, 15, (145, 22, 48), 0.80, 1.0),
        (0.45, 0.92, 0.30, 0.26, 0, (230, 88, 95), 0.78, 1.0),
        (0.86, 0.30, 0.32, 0.50, 0, (10, 4, 12), 0.92, 1.1),
        (0.70, 0.15, 0.28, 0.32, 0, (72, 18, 42), 0.65, 1.0),
    ], True, 0.8),
    "amber": ((14, 10, 8), [
        (0.82, 0.18, 0.38, 0.48, 30, (222, 140, 56), 0.90, 1.0),
        (0.65, 0.36, 0.30, 0.42, 28, (242, 182, 102), 0.70, 1.0),
        (0.22, 0.85, 0.36, 0.34, -15, (145, 78, 34), 0.78, 1.0),
        (0.12, 0.20, 0.28, 0.40, 0, (10, 7, 6), 0.95, 1.1),
        (0.90, 0.88, 0.30, 0.34, 0, (9, 6, 5), 0.92, 1.1),
    ], False, 0.9),
    "magenta": ((10, 8, 28), [
        (0.16, 0.25, 0.40, 0.50, -18, (215, 48, 136), 0.92, 1.0),
        (0.45, 0.85, 0.42, 0.36, 12, (112, 46, 178), 0.86, 1.0),
        (0.88, 0.25, 0.30, 0.48, 0, (8, 6, 22), 0.94, 1.1),
        (0.86, 0.86, 0.32, 0.35, 0, (6, 5, 16), 0.92, 1.1),
    ], False, 0.3),
    "forest_gold": ((5, 14, 10), [
        (0.18, 0.78, 0.44, 0.48, -20, (24, 128, 92), 0.90, 1.0),
        (0.78, 0.22, 0.38, 0.42, 24, (214, 162, 74), 0.86, 1.0),
        (0.48, 0.48, 0.30, 0.36, 0, (16, 62, 48), 0.65, 1.0),
        (0.10, 0.16, 0.28, 0.36, 0, (4, 10, 8), 0.94, 1.1),
        (0.90, 0.90, 0.30, 0.34, 0, (5, 11, 8), 0.94, 1.1),
    ], True, 0.9),
    "copper_teal": ((8, 14, 22), [
        (0.16, 0.30, 0.42, 0.52, -16, (44, 152, 166), 0.92, 1.0),
        (0.82, 0.78, 0.42, 0.46, -20, (218, 102, 54), 0.90, 1.0),
        (0.48, 0.55, 0.30, 0.36, 0, (18, 42, 58), 0.65, 1.0),
        (0.88, 0.16, 0.28, 0.36, 0, (6, 10, 18), 0.95, 1.1),
        (0.12, 0.90, 0.28, 0.30, 0, (6, 12, 18), 0.85, 1.1),
    ], False, 1.4),
    "plum_peach": ((12, 6, 16), [
        (0.80, 0.24, 0.42, 0.48, 18, (226, 140, 112), 0.90, 1.0),
        (0.24, 0.76, 0.44, 0.48, -14, (124, 38, 128), 0.90, 1.0),
        (0.55, 0.46, 0.32, 0.38, 0, (78, 28, 72), 0.70, 1.0),
        (0.10, 0.18, 0.28, 0.38, 0, (10, 5, 14), 0.94, 1.1),
    ], True, 2.0),
    "ice": ((5, 10, 20), [
        (0.28, 0.18, 0.28, 0.44, -26, (145, 208, 245), 0.88, 1.0),
        (0.18, 0.86, 0.36, 0.34, 14, (195, 226, 248), 0.86, 1.0),
        (0.54, 0.76, 0.34, 0.34, -12, (62, 118, 168), 0.78, 1.0),
        (0.88, 0.45, 0.32, 0.56, 0, (4, 7, 15), 0.95, 1.1),
        (0.04, 0.48, 0.14, 0.42, 0, (4, 8, 16), 0.88, 1.1),
    ], False, 0.6),
    "blood_violet": ((9, 4, 14), [
        (0.16, 0.65, 0.40, 0.52, -12, (206, 32, 50), 0.92, 1.0),
        (0.82, 0.32, 0.42, 0.50, 18, (112, 48, 214), 0.90, 1.0),
        (0.50, 0.92, 0.32, 0.28, 0, (68, 16, 48), 0.78, 1.0),
        (0.45, 0.10, 0.34, 0.28, 0, (10, 5, 18), 0.86, 1.1),
    ], False, 1.1),
    "mocha_rose": ((14, 8, 7), [
        (0.20, 0.28, 0.42, 0.50, -14, (198, 118, 128), 0.88, 1.0),
        (0.76, 0.82, 0.44, 0.42, 16, (118, 68, 48), 0.86, 1.0),
        (0.46, 0.88, 0.36, 0.30, 0, (76, 44, 38), 0.76, 1.0),
        (0.88, 0.20, 0.30, 0.42, 0, (10, 6, 5), 0.95, 1.1),
    ], True, 1.7),
    "aurora_violet": ((7, 10, 24), [
        (0.18, 0.82, 0.42, 0.44, -18, (68, 214, 182), 0.90, 1.0),
        (0.78, 0.24, 0.44, 0.48, 20, (134, 62, 204), 0.90, 1.0),
        (0.48, 0.50, 0.32, 0.38, 0, (32, 74, 128), 0.72, 1.0),
        (0.10, 0.18, 0.26, 0.36, 0, (6, 9, 20), 0.94, 1.1),
        (0.90, 0.88, 0.28, 0.34, 0, (7, 8, 20), 0.94, 1.1),
    ], False, 2.3),
    "bronze_navy": ((8, 14, 34), [
        (0.84, 0.28, 0.38, 0.50, 22, (206, 166, 114), 0.88, 1.0),
        (0.22, 0.74, 0.46, 0.48, -16, (26, 56, 126), 0.92, 1.0),
        (0.56, 0.88, 0.34, 0.30, 0, (124, 96, 68), 0.72, 1.0),
        (0.12, 0.16, 0.30, 0.38, 0, (5, 9, 22), 0.94, 1.1),
    ], True, 0.8),
    "sage": ((12, 15, 13), [
        (0.18, 0.24, 0.44, 0.52, -20, (126, 156, 114), 0.88, 1.0),
        (0.52, 0.86, 0.42, 0.38, 12, (168, 176, 146), 0.76, 1.0),
        (0.86, 0.38, 0.32, 0.54, 0, (10, 13, 11), 0.95, 1.1),
        (0.88, 0.88, 0.28, 0.34, 0, (8, 10, 9), 0.94, 1.1),
    ], True, 1.5),
    "sapphire": ((4, 9, 26), [
        (0.20, 0.68, 0.44, 0.52, -16, (44, 108, 246), 0.94, 1.0),
        (0.46, 0.14, 0.34, 0.36, 10, (82, 178, 250), 0.82, 1.0),
        (0.14, 0.92, 0.32, 0.28, 0, (112, 205, 255), 0.82, 1.0),
        (0.86, 0.52, 0.34, 0.58, 0, (4, 8, 22), 0.95, 1.1),
    ], False, 0.4),
    "sunset_lilac": ((12, 10, 28), [
        (0.16, 0.78, 0.44, 0.46, -15, (234, 102, 122), 0.92, 1.0),
        (0.80, 0.28, 0.42, 0.48, 20, (148, 104, 232), 0.90, 1.0),
        (0.46, 0.32, 0.32, 0.38, 0, (74, 48, 128), 0.74, 1.0),
        (0.88, 0.88, 0.32, 0.38, 0, (9, 8, 22), 0.95, 1.1),
        (0.10, 0.14, 0.28, 0.34, 0, (11, 9, 24), 0.90, 1.1),
    ], False, 1.9),
}


def lay_aura(w, h, v, covers, ctx):
    k = w / 1280
    base_rgb, blobs, is_serif, phase = AURA_PRESETS[v]
    img = grain(_mesh_bg(w, h, base_rgb, blobs, warp_amp=0.04, phase=phase), 5, seed=11).convert("RGBA")
    if is_serif:
        text(img, (w / 2, h * 0.125), "Playlist", font("PlayfairDisplay.ttf", int(94 * k), 600), fill=(255, 252, 248), k=k, tracking=int(10 * k), blur=6)
    else:
        text(img, (w / 2, h * 0.125), "Playlist", font("Montserrat.ttf", int(82 * k), 600), fill=(255, 255, 255), k=k, tracking=int(16 * k), blur=6)
    _place_grid6(img, covers, w, h, k)
    return img


PRISM_PALETTES = {
    "twilight": ((12, 14, 28), (62, 145, 215), (168, 72, 175), (225, 105, 118)),
    "ocean": ((6, 14, 24), (36, 168, 185), (42, 92, 195), (112, 205, 220)),
    "ember": ((14, 8, 8), (224, 96, 52), (168, 42, 68), (242, 165, 88)),
    "emerald": ((6, 16, 14), (38, 178, 128), (24, 112, 145), (125, 212, 175)),
    "crimson": ((14, 6, 12), (205, 38, 66), (118, 32, 128), (235, 108, 124)),
    "violet": ((10, 8, 26), (112, 68, 228), (195, 72, 168), (156, 142, 242)),
    "gold": ((14, 11, 7), (218, 158, 68), (138, 88, 42), (240, 205, 138)),
    "mono": ((10, 10, 12), (165, 170, 180), (75, 80, 92), (215, 218, 224)),
}


def lay_prism(w, h, v, covers, ctx):
    k = w / 1280
    base_rgb, c1, c2, c3 = PRISM_PALETTES[v]
    base_img = _mesh_bg(w, h, base_rgb, [
        (0.20, 0.30, 0.36, 0.55, 0, c1, 0.90, 1.0),
        (0.50, 0.65, 0.38, 0.50, 0, c2, 0.85, 1.0),
        (0.82, 0.32, 0.32, 0.48, 0, c3, 0.78, 1.0),
        (0.92, 0.85, 0.28, 0.38, 0, base_rgb, 0.92, 1.1),
        (0.08, 0.88, 0.24, 0.35, 0, base_rgb, 0.88, 1.1),
    ], warp_amp=0.02)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    arr = np.array(base_img).astype(np.float32)
    flute_w = max(8.0, 28.0 * k)
    phase = (x % flute_w) / flute_w
    shift = (np.sin(phase * 2.0 * math.pi) * max(3.0, 14.0 * k)).astype(np.int32)
    x_src = np.clip(x.astype(np.int32) + shift, 0, w - 1)
    refracted = arr[y.astype(np.int32), x_src]
    rib = np.exp(-((phase - 0.18) / 0.10) ** 2) * 26.0 - np.exp(-((phase - 0.82) / 0.12) ** 2) * 22.0
    refracted = np.clip(refracted + rib[..., None], 0, 255).astype(np.uint8)
    img = grain(Image.fromarray(refracted).filter(ImageFilter.GaussianBlur(max(0.5, 0.8 * k))), 4, seed=21).convert("RGBA")
    text(img, (w / 2, h * 0.125), "Playlist", font("Montserrat.ttf", int(82 * k), 600), fill=(255, 255, 255), k=k, tracking=int(16 * k), blur=6)
    _place_grid6(img, covers, w, h, k)
    return img


SILK_PALETTES = {
    "ice_silk": ((10, 13, 22), (58, 76, 108), (198, 214, 232)),
    "rose_silk": ((16, 8, 14), (118, 52, 78), (235, 168, 176)),
    "gold_silk": ((14, 10, 6), (125, 86, 36), (240, 202, 132)),
    "violet_silk": ((10, 7, 22), (76, 48, 138), (198, 168, 245)),
    "teal_silk": ((6, 15, 18), (34, 98, 112), (165, 224, 230)),
    "crimson_silk": ((16, 5, 8), (128, 28, 44), (236, 142, 148)),
    "emerald_silk": ((6, 16, 10), (32, 104, 68), (168, 226, 188)),
}


def lay_silk(w, h, v, covers, ctx):
    k = w / 1280
    if v == "silver_beam":
        bg = _mesh_bg(w, h, (12, 12, 14), [
            (0.48, 0.22, 0.30, 0.52, -38, (215, 210, 198), 0.92, 1.05),
            (0.88, 0.55, 0.24, 0.45, -35, (195, 192, 184), 0.86, 1.05),
            (0.16, 0.88, 0.28, 0.28, -25, (175, 174, 168), 0.78, 1.0),
            (0.12, 0.38, 0.20, 0.50, -36, (4, 4, 5), 0.96, 1.15),
            (0.65, 0.78, 0.22, 0.48, -36, (6, 6, 8), 0.94, 1.15),
            (0.95, 0.12, 0.18, 0.32, 0, (4, 4, 5), 0.92, 1.1),
        ], warp_amp=0.03)
    else:
        c_dark, c_mid, c_hi = [np.array(c, np.float32) for c in SILK_PALETTES[v]]
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        xn, yn = x / max(w, 1), y / max(h, 1)
        wx = xn * 3.8 + 0.55 * np.sin(yn * 4.5 + xn * 2.2)
        wy = yn * 2.8 + 0.45 * np.cos(xn * 3.2 - yn * 2.5)
        folds = 0.5 + 0.5 * np.sin(wx * 2.6 + wy * 1.9 + np.sin(wx * 1.4 - wy * 1.8) * 1.6)
        s = (folds ** 2.2)[..., None]
        arr = np.where(s < 0.55, c_dark + (c_mid - c_dark) * (s / 0.55), c_mid + (c_hi - c_mid) * ((s - 0.55) / 0.45))
        bg = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    img = grain(bg, 6, seed=31).convert("RGBA")
    text(img, (w / 2, h * 0.13), "Playlist", font("PlayfairDisplay.ttf", int(96 * k), 600), fill=(252, 250, 246), k=k, tracking=int(8 * k), blur=8)
    _place_grid6(img, covers, w, h, k)
    return img


ECLIPSE_PALETTES = {
    "violet_peach": ((7, 7, 14), (148, 86, 235), (238, 138, 92)),
    "cyan_blue": ((5, 9, 18), (64, 212, 235), (62, 108, 240)),
    "crimson_gold": ((12, 5, 8), (218, 44, 68), (242, 178, 78)),
    "emerald_teal": ((5, 12, 12), (48, 206, 142), (46, 162, 210)),
    "magenta_indigo": ((10, 6, 18), (232, 62, 152), (108, 68, 228)),
    "amber_noir": ((10, 8, 6), (235, 148, 56), (195, 78, 42)),
    "silver": ((7, 7, 9), (218, 222, 230), (132, 142, 162)),
    "sapphire": ((5, 8, 20), (72, 136, 252), (156, 98, 242)),
}


def lay_eclipse(w, h, v, covers, ctx):
    k = w / 1280
    base_rgb, ca, cb = ECLIPSE_PALETTES[v]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    xn, yn = x / max(w, 1), y / max(h, 1)
    dx = (xn - 0.5) * (w / max(h, 1))
    dy = yn - 0.52
    r = np.sqrt(dx ** 2 + dy ** 2)
    ang = np.arctan2(dy, dx)
    ring_r = 0.48
    ring = np.exp(-((r - ring_r) / 0.085) ** 2)
    outer = np.exp(-((np.maximum(r - ring_r, 0.0)) / 0.28) ** 1.3) * (r >= ring_r)
    t_ang = 0.5 + 0.5 * np.sin(ang + 0.8)
    rcol = np.array(ca, np.float32) * (1.0 - t_ang[..., None]) + np.array(cb, np.float32) * t_ang[..., None]
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[:] = base_rgb
    arr += ring[..., None] * rcol * 0.95 + outer[..., None] * rcol * 0.42
    inner = np.clip((r - 0.34) / 0.14, 0.0, 1.0)[..., None]
    arr *= (0.18 + 0.82 * inner)
    bg = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(max(1.5, 5.0 * k)))
    img = grain(bg, 6, seed=41).convert("RGBA")
    text(img, (w / 2, h * 0.125), "Playlist", font("Montserrat.ttf", int(82 * k), 600), fill=(255, 255, 255), k=k, tracking=int(16 * k), blur=6)
    _place_grid6(img, covers, w, h, k)
    return img


WAVE_PALETTES = {
    "silver": ((8, 8, 10), (225, 225, 230), (225, 225, 230)),
    "cyan_violet": ((6, 8, 14), (70, 215, 235), (180, 95, 245)),
    "crimson": ((10, 5, 8), (225, 48, 72), (242, 128, 112)),
    "gold": ((10, 8, 5), (235, 178, 76), (245, 215, 148)),
    "emerald": ((5, 11, 9), (48, 212, 148), (62, 185, 215)),
    "cobalt": ((5, 8, 18), (68, 128, 250), (145, 178, 252)),
    "rose": ((12, 6, 12), (236, 102, 148), (182, 86, 218)),
    "amber": ((11, 7, 5), (238, 128, 56), (218, 68, 78)),
}


def lay_wave(w, h, v, covers, ctx):
    k = w / 1280
    base_rgb, cl, cr = WAVE_PALETTES[v]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    xn, yn = x / max(w, 1), y / max(h, 1)
    ridge_y = 0.45 + 0.17 * np.sin(xn * 6.0 - 0.5) - 0.13 * np.exp(-((xn - 0.62) / 0.15) ** 2)
    dy = yn - ridge_y
    up = np.exp(-((np.minimum(dy, 0.0) / 0.052) ** 2))
    lo = np.exp(-((np.maximum(dy, 0.0) / 0.24) ** 1.38))
    wl = np.where(dy < 0, up, lo)
    rim = np.exp(-((dy / 0.024) ** 2)) * 0.45
    lmod = 0.56 + 0.44 * np.sin(xn * 4.9 + 0.8) ** 2 + 0.32 * np.exp(-((xn - 0.62) / 0.18) ** 2)
    inten = np.clip((wl * 0.74 + rim) * lmod, 0.0, 1.0)
    wcol = np.array(cl, np.float32) * (1.0 - xn[..., None]) + np.array(cr, np.float32) * xn[..., None]
    arr = np.array(base_rgb, np.float32) + (inten[..., None] ** 1.08) * wcol + np.clip(inten - 0.74, 0, 1)[..., None] * 240.0
    rng = np.random.default_rng(55)
    arr = np.clip(arr + rng.normal(0, 18, (h, w, 1)), 0, 255).astype(np.uint8)
    img = Image.fromarray(arr).convert("RGBA")
    text(img, (w / 2, h * 0.275), "Playlist", font("PlayfairDisplay.ttf", int(108 * k), 600), fill=(242, 245, 250), k=k, tracking=int(10 * k), blur=9)
    _place_strip4(img, covers, w, h, k, cy_frac=0.72)
    return img


HORIZON_PALETTES = {
    "crimson": ((8, 14, 34), (218, 76, 68), (242, 134, 88), (156, 44, 78)),
    "amber": ((10, 12, 24), (228, 138, 52), (245, 192, 98), (158, 74, 34)),
    "violet": ((8, 10, 26), (146, 72, 224), (208, 112, 232), (82, 52, 178)),
    "teal": ((6, 12, 24), (42, 178, 176), (92, 216, 206), (26, 98, 148)),
    "rose": ((12, 10, 24), (224, 96, 136), (242, 152, 168), (138, 48, 96)),
    "emerald": ((6, 14, 16), (38, 182, 122), (96, 218, 162), (22, 108, 92)),
    "cobalt": ((5, 9, 24), (56, 118, 242), (112, 172, 252), (38, 62, 168)),
    "gold": ((12, 11, 14), (218, 168, 74), (242, 210, 132), (148, 104, 48)),
}


def lay_horizon(w, h, v, covers, ctx):
    k = w / 1280
    sky_rgb, h1, h2, h3 = HORIZON_PALETTES[v]
    bg = _mesh_bg(w, h, sky_rgb, [
        (0.50, 0.96, 0.65, 0.38, 0, h1, 0.94, 1.05),
        (0.26, 0.88, 0.40, 0.30, -8, h2, 0.76, 1.0),
        (0.78, 0.86, 0.36, 0.28, 8, h3, 0.80, 1.0),
        (0.50, 0.15, 0.70, 0.38, 0, tuple(max(4, int(c * 0.7)) for c in sky_rgb), 0.92, 1.1),
    ], warp_amp=0.025)
    img = grain(bg, 6, seed=61).convert("RGBA")
    text(img, (w / 2, h * 0.26), "Playlist", font("Montserrat.ttf", int(90 * k), 600), fill=(255, 248, 242), k=k, tracking=int(18 * k), blur=7)
    _place_strip4(img, covers, w, h, k, cy_frac=0.72)
    return img


LAYOUTS = {"aura": lay_aura, "prism": lay_prism, "silk": lay_silk, "eclipse": lay_eclipse, "wave": lay_wave, "horizon": lay_horizon,
           "night": lay_night, "swirl": lay_swirl, "sunset": lay_sunset, "bold": lay_bold, "poster": lay_poster,
           "room": lay_room, "strip": lay_strip, "chrome": lay_chrome, "tracklist": lay_tracklist}


def resolve(family, variant):
    """Saved picks of earlier versions keep working: an old style name becomes the closest new one (and its colour the first colour).
    For a current style an unknown colour is an error."""
    legacy = family in LEGACY
    family = LEGACY.get(family, family)
    fam = next((f for f in FAMILIES if f["id"] == family), None)
    if not fam:
        raise ValueError(f"unknown thumbnail style {family}/{variant}")
    if variant not in fam["variants"]:
        if not legacy:
            raise ValueError(f"unknown thumbnail style {family}/{variant}")
        variant = fam["variants"][0]
    return family, variant


def render(family, variant, covers, ctx=None, size=(1280, 720)):
    ctx = ctx or {}
    family, variant = resolve(family, variant)
    return LAYOUTS[family](size[0], size[1], variant, covers, ctx).convert("RGB")


def cache_key(family, variant, covers, ctx, size):
    family, variant = resolve(family, variant)
    sig = repr((family, variant, [(c, os.path.getmtime(c)) for c in covers if c and os.path.exists(c)], ctx.get("moods"),
                ctx.get("title"), ctx.get("thumb_text"), round(ctx.get("minutes") or 0), ctx.get("channel"), ctx.get("tracks"), size))
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
           "thumb_text": project.get("thumb_text", ""), "minutes": minutes, "channel": project.get("channel") or "",
           "tracks": [t.get("title", "") for t in project["tracks"] if t.get("cover")]}
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
