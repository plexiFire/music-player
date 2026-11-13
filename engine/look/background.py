"""Generate a seamless looping marbled-flow background video (free, local, numpy only)."""
import hashlib
import random
import subprocess
import numpy as np

# curated dark-based (shadow, highlight) palettes: every background stays dark, each video gets a different mood
PALETTES = {
    "ink":      ((7, 7, 9),     (118, 114, 106)),
    "mono":     ((4, 4, 4),     (108, 108, 108)),
    "midnight": ((3, 5, 20),    (58, 82, 160)),
    "navy":     ((2, 8, 24),    (40, 100, 170)),
    "ember":    ((14, 4, 5),    (156, 70, 38)),
    "wine":     ((16, 3, 8),    (140, 38, 62)),
    "rose":     ((20, 5, 14),   (152, 72, 102)),
    "plum":     ((14, 4, 20),   (122, 62, 140)),
    "violet":   ((9, 4, 24),    (104, 82, 166)),
    "forest":   ((3, 13, 9),    (78, 122, 84)),
    "moss":     ((9, 12, 4),    (120, 138, 66)),
    "teal":     ((2, 14, 16),   (38, 130, 126)),
    "ocean":    ((2, 14, 22),   (52, 122, 134)),
    "steel":    ((8, 11, 15),   (110, 128, 148)),
    "sand":     ((16, 12, 8),   (132, 114, 90)),
    "sunset":   ((18, 5, 22),   (176, 98, 58)),
}


def style_from_seed(seed):
    """Deterministic style from any text (e.g. playlist title). Same seed -> same look."""
    h = int(hashlib.sha256(str(seed).encode()).hexdigest(), 16)
    rng = random.Random(h)
    name = rng.choice(list(PALETTES))
    return {"palette": name, "scale": round(rng.uniform(2.2, 2.8), 2),
            "warp": round(rng.uniform(0.9, 1.05), 2), "iters": 3,
            "phase": round(rng.uniform(0, 6.28), 2), "direction": rng.choice([1, -1]),
            "seconds": rng.choice([16, 20, 24]),
            "contrast": 1, "blur": 0.8, "grain": 12,
            "offset": [round(rng.uniform(0, 6.28), 2), round(rng.uniform(0, 6.28), 2)],
            "rot": round(rng.uniform(0, 3.14), 2), "gamma": round(rng.uniform(3.0, 4.2), 2)}


def _frame(w, h, theta, dark, light, scale=3.0, warp=0.9, iters=4, phase=0.0, contrast=1,
           offset=(0.0, 0.0), rot=0.0, gamma=1.0):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    x = x / w * scale * 2 * np.pi
    y = y / h * scale * 2 * np.pi * (h / w)
    x, y = x * np.cos(rot) - y * np.sin(rot) + offset[0], x * np.sin(rot) + y * np.cos(rot) + offset[1]
    c, s = np.cos(theta), np.sin(theta)
    for i in range(iters):  # domain warping gives the liquid-marble look
        k = 1.0 + 0.35 * i
        x, y = (x + warp * np.sin(k * y + 1.7 * s + i + phase),
                y + warp * np.sin(k * x + 1.3 * c + 2 * i))
    v = 0.5 + 0.5 * np.sin(x + y)
    for _ in range(max(1, int(contrast))):  # repeated smoothstep = punchier black/white swirls
        v = v * v * (3 - 2 * v)
    v = v ** gamma  # gamma: keeps most of the frame in shadow, highlights stay sparse
    dark = np.array(dark, np.float32)
    light = np.array(light, np.float32)
    img = dark + (light - dark) * v[..., None]
    grain = np.random.default_rng(7).normal(0, 3, (h, w, 1)).astype(np.float32)
    return np.clip(img + grain, 0, 255).astype(np.uint8)


def make_loop(out_path, style=None, fps=30, size=(960, 540), final=(1920, 1080)):
    """Render a loop. Phase moves on a circle, so last frame flows into first frame."""
    style = {**style_from_seed("default"), **(style or {})}
    dark, light = PALETTES[style["palette"]]
    w, h = size
    n = int(style["seconds"] * fps)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-vf", f"scale={final[0]}:{final[1]}:flags=bicubic,gblur=sigma={style['blur']},noise=alls={style['grain']}:allf=u",
           "-c:v", "libx264", "-crf", "12", "-preset", "medium",
           "-pix_fmt", "yuv420p", out_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        theta = style["direction"] * 2 * np.pi * i / n
        p.stdin.write(_frame(w, h, theta, dark, light, style["scale"], style["warp"],
                             style["iters"], style["phase"], style["contrast"],
                             style["offset"], style["rot"], style["gamma"]).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("background render failed")
    return out_path


# constant backgrounds: a dark colour that fades toward near-black, like the blue one in the reference video
SOLID = {
    "blue": (30, 52, 205), "purple": (120, 44, 190), "teal": (18, 150, 160), "green": (30, 140, 80),
    "red": (190, 38, 52), "orange": (205, 100, 30), "pink": (200, 60, 140), "grey": (120, 124, 134),
}


def solid_colour(name):
    """Colour name from SOLID or '#rrggbb'. Unknown -> blue."""
    if isinstance(name, str) and name.startswith("#") and len(name) == 7:
        try:
            return tuple(int(name[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            pass
    return SOLID.get(name, SOLID["blue"])


def make_solid(out_path, size, colour="blue", darken=0.8, grain=5.0, stars=True):
    """One wide gradient image (a little larger than the frame so it can drift): black at the top-left, the colour
    glows toward the bottom-right, fine grain, a few tiny stars. Always dark."""
    from PIL import Image
    w, h = size
    W2, H2 = int(w * 1.15), int(h * 1.15)
    rng = np.random.default_rng(5)
    y, x = np.mgrid[0:H2, 0:W2].astype(np.float32)
    t = (x / W2 * 0.55 + y / H2 * 0.75)                              # diagonal ramp 0..1.3
    t = np.clip((t - 0.25) / 0.75, 0, 1) ** 1.25
    col = np.array(solid_colour(colour), np.float32) * float(darken)
    near_black = np.array([6, 6, 10], np.float32)
    img = near_black + (col - near_black) * t[..., None]
    img = img + rng.normal(0, grain, (H2, W2, 1)) * (0.4 + t[..., None])
    if stars:
        for _ in range(40):
            sx, sy = int(rng.integers(0, W2)), int(rng.integers(0, int(H2 * 0.6)))
            k = max(1, round(2 * w / 1920))
            img[sy:sy + k, sx:sx + k] += rng.integers(90, 190)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(out_path)
    return out_path


# ---- night-sky templates: dark gradient, soft light beams from the top, many tiny twinkling stars ----
SKY = {   # name: (label, glow colour)
    "night": ("Night sky (blue)", (40, 78, 190)),
    "nebula": ("Nebula (purple)", (150, 62, 190)),
    "aurora": ("Aurora (green)", (34, 170, 140)),
    "ember": ("Ember (red)", (200, 70, 40)),
    "rose": ("Rose dusk (pink)", (200, 70, 130)),
    "mono": ("Moonlight (grey)", (130, 136, 150)),
}


def _sky_stars(w, h, seed=3, n=150):
    rng = np.random.default_rng(seed)
    k = max(1.0, w / 1920)
    return {"x": rng.integers(2, w - 2, n), "y": (rng.random(n) ** 1.3 * h * 0.95).astype(int).clip(2, h - 3),
            "f": rng.integers(1, 4, n), "ph": rng.random(n) * 2 * np.pi, "amp": rng.uniform(0.45, 1.0, n),
            "big": rng.random(n) < 0.12, "k": k}


def sky_frame(w, h, t, colour="night", stars=None):
    """One frame, t in [0,1) is the loop position (everything is periodic in t, so the loop is seamless)."""
    glow = np.array(SKY.get(colour, SKY["night"])[1] if colour in SKY else solid_colour(colour), np.float32)
    sw, sh = 240, 135
    y, x = np.mgrid[0:sh, 0:sw].astype(np.float32)
    x, y = x / sw, y / sh
    beams = np.zeros((sh, sw), np.float32)
    for i, (cx, wid, amp) in enumerate([(0.34, 0.10, 1.0), (0.52, 0.16, 0.8), (0.70, 0.09, 0.6), (0.18, 0.12, 0.5)]):
        c = cx + 0.035 * np.sin(2 * np.pi * (t + i * 0.27))
        beams += amp * (0.8 + 0.2 * np.sin(2 * np.pi * (t * 2 + i))) * np.exp(-((x - c) / wid) ** 2)
    beams *= np.exp(-y / 0.42) * 0.9
    sky = 0.10 * np.exp(-((y - 0.0) / 0.9))                     # faint overall glow, strongest at the top
    base = np.array([3, 6, 16], np.float32)[None, None, :] + glow[None, None, :] * (0.55 * beams + sky)[..., None] * 1.0
    from PIL import Image
    img = np.asarray(Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32)
    st = stars or _sky_stars(w, h)
    v = (0.2 + 0.8 * (0.5 + 0.5 * np.sin(2 * np.pi * st["f"] * t + st["ph"])) ** 2) * st["amp"] * 255
    xs, ys = st["x"], st["y"]
    for dx, dy, wgt in ((0, 0, 1.0), (1, 0, 0.7), (0, 1, 0.7), (1, 1, 0.5)):
        img[ys + dy, xs + dx] += (v * wgt)[:, None]
    big = st["big"]
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):            # little cross sparkle on the bigger stars
        img[ys[big] + dy, xs[big] + dx] += (v[big] * 0.45)[:, None]
    return np.clip(img, 0, 255).astype(np.uint8)


def make_sky_loop(out_path, colour="night", fps=30, seconds=12, final=(1920, 1080)):
    w, h = final
    n = int(seconds * fps)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-vf", "noise=alls=7:allf=u", "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-pix_fmt", "yuv420p", out_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    st = _sky_stars(w, h)
    for i in range(n):
        p.stdin.write(sky_frame(w, h, i / n, colour, st).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("could not build the night-sky background")
    return out_path
