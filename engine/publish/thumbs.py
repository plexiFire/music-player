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

REFERENCE = {   # the styles, taken from the reference thumbnails you chose (views 0: none of ours has been measured yet)
    "room": {"views": 0, "note": "Warm dark room with window light, a record player and a plant; your covers as little prints, 'PlayList' in cream italic and the channel name at the bottom."},
    "strip": {"views": 0, "note": "Your covers side by side across the whole picture, a big warm 3D title with sparkles over them."},
    "pastel": {"views": 0, "note": "Soft sunset sky, a glowing italic 'PlayList', your covers in a neat framed grid."},
    "chrome": {"views": 0, "note": "Dark swirl, a big silver 'PlayList', your covers in one row underneath."},
    "tracklist": {"views": 0, "note": "Dark grainy blue with a glowing picture, 'PlayList' on top and a list of the song names with their small covers."},
}
FAMILIES = [
    {"id": "room", "label": "Warm room", "variants": ["sepia", "wine", "teal", "blue", "violet", "mono"]},
    {"id": "strip", "label": "Cover strip", "variants": ["amber", "crimson", "teal", "blue", "purple", "green"]},
    {"id": "pastel", "label": "Soft sky grid", "variants": ["peach", "pink", "lilac", "sky", "mint", "gold"]},
    {"id": "chrome", "label": "Silver on dark", "variants": ["mono", "blue", "violet", "wine", "teal", "sepia"]},
    {"id": "tracklist", "label": "Track list", "variants": ["blue", "violet", "teal", "wine", "mono", "sepia"]},
]
LEGACY = {"night": "strip", "swirl": "chrome", "sunset": "pastel", "sky": "pastel", "bold": "tracklist", "season": "pastel", "poster": "room",
          "record": "room", "cascade": "strip", "hero": "room", "filmstrip": "strip"}      # styles of earlier versions: saved picks keep working
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


LAYOUTS = {"room": lay_room, "strip": lay_strip, "pastel": lay_pastel, "chrome": lay_chrome, "tracklist": lay_tracklist}


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
