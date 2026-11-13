"""A small bold channel-name mark for the bottom-right corner (so nobody can re-upload the video unmarked)."""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = ["/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/System/Library/Fonts/HelveticaNeue.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]


def make(text, out_path, frame_h=1080, opacity=0.82):
    """Draws '<text>.' in white with a soft shadow. Size scales with the video height."""
    size = max(14, round(frame_h * 0.032))
    font = next((ImageFont.truetype(f, size) for f in FONTS if os.path.exists(f)), ImageFont.load_default())
    label = text.strip().rstrip(".") + "."
    box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), label, font=font)
    w, h = box[2] - box[0] + size, box[3] - box[1] + size
    shadow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shadow).text((size // 2 - box[0] + 2, size // 2 - box[1] + 2), label, font=font, fill=170)
    shadow = shadow.filter(ImageFilter.GaussianBlur(size / 8))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (w, h), (0, 0, 0, 255)), (0, 0), shadow)
    ImageDraw.Draw(img).text((size // 2 - box[0], size // 2 - box[1]), label, font=font, fill=(255, 255, 255, round(255 * opacity)))
    img.save(out_path)
    return out_path
