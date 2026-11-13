"""Folder mode: audio files in a folder -> project.json (tags, embedded/looked-up cover, order)."""
import os
import re

from mutagen import File as MFile
from PIL import Image, ImageDraw

from ..sources import library, metadata


def _tags(path):
    f = MFile(path, easy=True)
    t = (f.get("title") or [None])[0] if f else None
    a = (f.get("artist") or [None])[0] if f else None
    return t, a


def _embedded_cover(path, out):
    f = MFile(path)
    if f is None:
        return None
    data = None
    tags = f.tags
    if tags is not None:
        for k in list(tags.keys()):
            if str(k).startswith("APIC"):
                data = tags[k].data
                break
        if data is None and "covr" in tags and tags["covr"]:
            data = bytes(tags["covr"][0])
    if data is None and getattr(f, "pictures", None):
        data = f.pictures[0].data
    if data:
        with open(out, "wb") as fh:
            fh.write(data)
        return out
    return None


def _plain_cover(title, out):
    im = Image.new("RGB", (1200, 1200), (28, 28, 34))
    d = ImageDraw.Draw(im)
    d.ellipse([350, 350, 850, 850], outline=(200, 200, 205), width=10)
    d.ellipse([560, 560, 640, 640], fill=(200, 200, 205))
    im.save(out)
    return out


def build_project(folder, title, workdir, order_file=None, lookup=True):
    os.makedirs(workdir, exist_ok=True)
    names = [n for n in sorted(os.listdir(folder))
             if os.path.splitext(n)[1].lower() in library.AUDIO_EXT]
    if order_file and os.path.exists(order_file):  # optional: one filename per line
        wanted = [l.strip() for l in open(order_file) if l.strip()]
        names = [n for n in wanted if n in names] + [n for n in names if n not in wanted]
    tracks = []
    for i, n in enumerate(names, 1):
        path = os.path.join(folder, n)
        stem = os.path.splitext(n)[0]
        t, a = _tags(path)
        if not t:
            t = re.sub(r"^\d+[\s._-]+", "", stem)
            if " - " in t:
                a2, t = t.split(" - ", 1)
                a = a or a2
        cover = _embedded_cover(path, os.path.join(workdir, f"cover{i:02d}.jpg"))
        album = ""
        if not cover and lookup:
            try:
                m = metadata.resolve(f"{a} - {t}" if a else t)
                if not m["needs_review"] and m["cover_url"]:
                    cover = metadata.download_cover(m["cover_url"], os.path.join(workdir, f"cover{i:02d}.jpg"))
                    album = m["album"]
            except Exception:
                pass
        cover = cover or _plain_cover(t, os.path.join(workdir, f"cover{i:02d}.png"))
        tracks.append({"title": t.strip(), "artist": (a or "").strip(), "album": album,
                       "duration": 0, "cover": cover, "audio": path, "source_link": ""})
    return {"title": title, "theme": title, "tracks": tracks}
