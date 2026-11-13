"""Mutagen tag reading/writing for mp3, m4a, flac, ogg/opus and wav."""
import mimetypes

from mutagen import File as MFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, COMM, ID3, TALB, TIT2, TPE1, TXXX
from mutagen.mp4 import MP4, MP4Cover
from mutagen.wave import WAVE


def read(path):
    """Return {title, artist, album, duration} (missing values are '' / 0)."""
    f = MFile(path, easy=True)
    if f is None:
        raise ValueError(f"unreadable audio file: {path}")
    if isinstance(f, WAVE):  # WAV carries ID3 frames; no EasyID3 wrapper
        g = lambda k: str(f.tags.get({"title": "TIT2", "artist": "TPE1", "album": "TALB"}[k], "")) if f.tags else ""
    else:
        g = lambda k: (f.get(k) or [""])[0]
    return {"title": g("title"), "artist": g("artist"), "album": g("album"),
            "duration": float(f.info.length)}


def _image(cover_path):
    data = open(cover_path, "rb").read()
    mime = mimetypes.guess_type(cover_path)[0] or "image/jpeg"
    return data, mime


def write(path, title="", artist="", album="", cover=None, comment=""):
    """Write tags (and cover art when given) in the file's native tag format."""
    ext = path.lower().rsplit(".", 1)[-1]
    img = _image(cover) if cover else None
    if ext in ("mp3", "wav"):
        f = WAVE(path) if ext == "wav" else None
        if f is not None:
            if f.tags is None:
                f.add_tags()
            tags = f.tags
        else:
            try:
                tags = ID3(path)
            except Exception:
                tags = ID3()
        for fr, val in (("TIT2", title), ("TPE1", artist), ("TALB", album)):
            if val:
                tags.setall(fr, [{"TIT2": TIT2, "TPE1": TPE1, "TALB": TALB}[fr](encoding=3, text=val)])
        if comment:
            tags.setall("COMM", [COMM(encoding=3, lang="eng", desc="senora", text=comment)])
        if img:
            tags.setall("APIC", [APIC(encoding=3, mime=img[1], type=3, desc="Cover", data=img[0])])
        (f.save() if f is not None else tags.save(path, v2_version=3))
    elif ext == "m4a":
        f = MP4(path)
        if title: f["\xa9nam"] = [title]
        if artist: f["\xa9ART"] = [artist]
        if album: f["\xa9alb"] = [album]
        if comment: f["\xa9cmt"] = [comment]
        if img:
            fmt = MP4Cover.FORMAT_PNG if img[1] == "image/png" else MP4Cover.FORMAT_JPEG
            f["covr"] = [MP4Cover(img[0], imageformat=fmt)]
        f.save()
    elif ext in ("flac", "ogg", "opus"):
        f = MFile(path)
        if title: f["title"] = [title]
        if artist: f["artist"] = [artist]
        if album: f["album"] = [album]
        if comment: f["comment"] = [comment]
        if img and isinstance(f, FLAC):
            p = Picture()
            p.type, p.mime, p.data = 3, img[1], img[0]
            f.clear_pictures()
            f.add_picture(p)
        f.save()
    else:
        raise ValueError(f"don't know how to tag .{ext}")
