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
