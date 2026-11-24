"""Per-track background: the track's own cover art, enlarged, heavily blurred and tinted."""
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def make(cover_path, out_path, size, margin=1.2, blur=0.07, darken=0.3, saturation=1.35, grain=0.0):
    """size=(W,H) of the video. Output is margin x larger so the render can drift across it."""
    W, H = size
    mw, mh = int(W * margin) // 2 * 2, int(H * margin) // 2 * 2
    sw, sh = mw // 4, mh // 4                     # blur at 1/4 scale: fast, and the result is soft anyway
    im = Image.open(cover_path).convert("RGB")
    s = max(sw / im.width, sh / im.height)         # fill the frame, crop the overflow
    im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
    l, t = (im.width - sw) // 2, (im.height - sh) // 2
    im = im.crop((l, t, l + sw, t + sh)).filter(ImageFilter.GaussianBlur(sh * blur))
    im = ImageEnhance.Color(im).enhance(saturation)
    a = np.asarray(im.resize((mw, mh), Image.BICUBIC), np.float32) * (1 - darken)
    if grain > 0:
        a += np.random.default_rng(5).normal(0, grain, (mh, mw, 1))  # hides banding in the gradients
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(out_path)
    return out_path
