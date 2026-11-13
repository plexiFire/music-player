"""Thumbnail: blurred video frame, spaced title, grid of up to 6 covers (1280x720 JPEG < 2 MB)."""
import os
import subprocess
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

FONTS = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/System/Library/Fonts/Helvetica.ttc",
         "/Library/Fonts/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",     # Linux / GitHub runners
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]


def _font(size):
    for p in FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def _spaced(draw, text, font, cx, y, gap=26):
    w = sum(draw.textlength(c, font=font) for c in text) + gap * (len(text) - 1)
    x = cx - w / 2
    for c in text:
        draw.text((x + 3, y + 3), c, font=font, fill=(0, 0, 0))
        draw.text((x, y), c, font=font, fill=(255, 255, 255))
        x += draw.textlength(c, font=font) + gap


def thumbnail(video_path, out_path, text, covers, at=5.0, work=None):
    """1280x720 JPEG (<2 MB): blurred video frame, spaced title, grid of up to 6 covers."""
    from PIL import ImageFilter
    frame = (work or os.path.dirname(out_path) or ".") + "/_thumb_frame.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", video_path,
                    "-frames:v", "1", "-vf", "scale=1280:720", frame], check=True, stdin=subprocess.DEVNULL)
    im = Image.open(frame).convert("RGB").filter(ImageFilter.GaussianBlur(22))
    im = ImageEnhance.Brightness(im).enhance(0.85)
    d = ImageDraw.Draw(im)
    _spaced(d, text, _font(78), 640, 38)
    covers = covers[:6]
    n = len(covers)
    size, gap = (226, 36) if n > 2 else (300, 50)
    cols = 3 if n >= 5 else (2 if n == 4 else n)
    rows = [covers[i:i + cols] for i in range(0, n, cols)]
    total_h = len(rows) * size + (len(rows) - 1) * gap
    y = 150 + (520 - total_h) // 2
    for row in rows:
        x = (1280 - (len(row) * size + (len(row) - 1) * gap)) // 2
        for c in row:
            im.paste(Image.open(c).convert("RGB").resize((size, size), Image.LANCZOS), (x, y))
            x += size + gap
        y += size + gap
    q = 92
    while True:
        im.save(out_path, "JPEG", quality=q)
        if os.path.getsize(out_path) < 1_900_000 or q <= 60:
            break
        q -= 8
    os.remove(frame)
    return out_path
