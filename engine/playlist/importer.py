"""Unified track importer: local file | YouTube/web URL | Spotify link | 'Artist - Title'  ->  playlist tracks.

Every path ends the same way: a processed, tagged audio file in audio_dir, a cover image, and a track dict
in project.json's schema (title, artist, album, duration, cover, audio, source_link) plus `rights`.
Spotify supplies metadata only; its audio is never fetched. Web audio is fetched only if authorized.
"""
import json
import os
import re
import shutil

from ..media import audio, tags, trim as autotrim
from ..sources import library, metadata, spotify, ytdlp
from . import folder


def _safe(s):
    return re.sub(r'[\\/:*?"<>|]+', "", s).strip() or "track"


def _cover(meta, workdir, idx, embedded_from=None, lookup=True, explicit=None, prefer_source=False):
    """Cover order: explicit image given by you > the source video's own thumbnail (web links) > embedded art >
    online lookup > plain placeholder."""
    os.makedirs(workdir, exist_ok=True)
    base = os.path.join(workdir, f"cover{idx:02d}")
    if explicit:
        return _square_png(explicit, base + ".png")
    if prefer_source and meta.get("cover_url"):
        try:
            return _square_png_from_url(meta["cover_url"], base + ".png")
        except Exception:
            pass
    if embedded_from:
        c = folder._embedded_cover(embedded_from, base + ".jpg")
        if c:
            return c
    url = meta.get("cover_url")
    if lookup and meta.get("artist") and meta.get("title"):  # prefer clean square 1200px art
        try:
            m = metadata.resolve(f"{meta['artist']} - {meta['title']}")
            url = m["cover_url"] if not m["needs_review"] and m["cover_url"] else url
        except Exception:
            pass
    if url:
        try:
            return metadata.download_cover(url, base + ".jpg")
        except Exception:
            pass
    return folder._plain_cover(meta.get("title", ""), base + ".png")


def _square_png(src, out):
    from PIL import Image
    im = Image.open(src).convert("RGB")
    s = min(im.size)
    im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2))
    im.resize((1000, 1000), Image.LANCZOS).save(out)
    return out


def _square_png_from_url(url, out):
    import tempfile
    raw = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False).name
    metadata.download_cover(url, raw)
    return _square_png(raw, out)


def _finish(src_audio, meta, audio_dir, workdir, idx, fmt, normalize, lookup, rights, link="", trim=False,
            cover=None, prefer_source=False):
    """Process audio with FFmpeg, tag it with Mutagen, fetch cover, return the track dict."""
    try:
        existing = tags.read(src_audio)
    except Exception:  # e.g. raw .webm/.opus-in-webm from YouTube: mutagen can't parse it, FFmpeg can
        existing = {"title": "", "artist": "", "album": "", "duration": audio.probe(src_audio)["duration"]}
    title = meta.get("title") or existing["title"] or os.path.splitext(os.path.basename(src_audio))[0]
    artist = meta.get("artist") or existing["artist"]
    album = meta.get("album") or existing["album"]
    cut = {"start": 0.0, "end": None, "reasons": []}
    if trim:   # ONLY when asked (--trim): drop silence / non-music extras at start/end (see media/trim.py)
        full = audio.probe(src_audio)["duration"]
        found = autotrim.detect(src_audio, full)
        if found["reasons"] and (found["start"] > 0 or found["end"] < full):
            cut = {"start": found["start"], "end": found["end"], "reasons": found["reasons"],
                   "removed": round(full - (found["end"] - found["start"]), 1)}
    out = audio.process(src_audio, audio_dir, name=_safe(f"{artist} - {title}" if artist else title),
                        fmt=fmt, normalize=normalize, start=cut["start"], end=cut["end"])
    explicit_cover = cover
    cover = _cover({**meta, "title": title, "artist": artist}, workdir, idx, embedded_from=src_audio, lookup=lookup,
                   explicit=cover, prefer_source=prefer_source)
    note = f"Imported by Senora; rights: {rights['basis']}" + (f"; source: {link}" if link else "")
    tags.write(out, title=title, artist=artist, album=album, cover=cover, comment=note)
    info = audio.probe(out)
    if explicit_cover:
        image_source = f"upload: {explicit_cover}"
    elif prefer_source and meta.get("cover_url"):
        image_source = f"link thumbnail: {link or meta.get('source_link', '')}"
    else:
        image_source = "auto cover (online lookup or plain)"
    track = {"title": title, "artist": artist, "album": album, "duration": info["duration"],
             "cover": cover, "audio": out, "source_link": link, "rights": rights,
             "audio_source": f"link: {link}" if link else f"file: {src_audio}",
             "image_source": image_source}
    if cut["reasons"]:
        track["trim"] = {**cut, "original": src_audio}
    return track


def import_one(source, audio_dir, workdir, start_index=1, fmt="mp3", normalize=False,
               authorized=False, lookup=True, audio_source=None, library_dir=None, trim=False, cover=None):
    """Import one source. Returns a list of track dicts (Spotify albums/playlists give several).

    audio_source: optional authorized local file/URL providing the audio for a metadata-only source
    (e.g. a Spotify link paired with the file you own). library_dir: folder searched for matching audio.
    """
    source = source.strip()
    out, i = [], start_index
    if spotify.is_spotify(source):
        for m in spotify.tracks(source):
            a = audio_source if (audio_source and len(out) == 0) else None
            out.append(_from_metadata(m, a, library_dir or audio_dir, audio_dir, workdir, i, fmt,
                                      normalize, authorized, lookup, trim=trim))
            i += 1
        return out
    if metadata.is_url(source):
        meta = ytdlp.info(source)
        path, meta, basis = ytdlp.fetch_audio(source, os.path.join(workdir, "_dl"), authorized, meta)
        out.append(_finish(path, meta, audio_dir, workdir, i, fmt, normalize, lookup,
                           {"basis": basis, "license": meta.get("license", "")}, link=meta["source_link"], trim=trim,
                           cover=cover, prefer_source=True))
        return out
    if os.path.isdir(source):
        names = [n for n in sorted(os.listdir(source)) if os.path.splitext(n)[1].lower() in library.AUDIO_EXT]
        for n in names:
            out += import_one(os.path.join(source, n), audio_dir, workdir, i, fmt, normalize, authorized, lookup, trim=trim)
            i = start_index + len(out)
        return out
    if os.path.isfile(source):
        if not authorized:
            raise ytdlp.NotAuthorized(f"{source}: confirm you own or are licensed to use it with --authorized")
        out.append(_finish(source, {}, audio_dir, workdir, i, fmt, normalize, lookup, {"basis": "user-attested"}, trim=trim))
        return out
    # free text 'Artist - Title': metadata lookup, audio from library_dir (or audio_source)
    m = metadata.resolve(source)
    return [_from_metadata(m, audio_source, library_dir or audio_dir, audio_dir, workdir, i, fmt,
                           normalize, authorized, lookup, trim=trim)]


def _from_metadata(m, audio_source, library_dir, audio_dir, workdir, idx, fmt, normalize, authorized, lookup, trim=False):
    """Metadata-only source: audio comes from an authorized file/URL, or a matching file in library_dir."""
    link = m.get("source_link", "")
    if audio_source and metadata.is_url(audio_source):
        path, _, basis = ytdlp.fetch_audio(audio_source, os.path.join(workdir, "_dl"), authorized)
        return _finish(path, m, audio_dir, workdir, idx, fmt, normalize, lookup, {"basis": basis}, link, trim=trim)
    path = audio_source or (library_dir and os.path.isdir(library_dir) and
                            (library.find_audio(library_dir, m["title"], m.get("artist", ""))
                             or library.find_audio(library_dir, m.get("query", m["title"]))))
    if path:
        if not authorized:
            raise ytdlp.NotAuthorized(f"{path}: confirm you own or are licensed to use it with --authorized")
        return _finish(path, m, audio_dir, workdir, idx, fmt, normalize, lookup, {"basis": "user-attested"}, link, trim=trim)
    cover = _cover(m, workdir, idx, lookup=False)  # metadata kept; audio must be supplied -> flagged
    return {"title": m["title"], "artist": m.get("artist", ""), "album": m.get("album", ""),
            "duration": m.get("duration", 0), "cover": cover, "audio": None, "source_link": link,
            "needs_audio": True}


def add_to_project(project_path, tracks, title=None, position=None):
    """Append tracks to a project.json (creating it if needed). This is the playlist the renderer builds."""
    if os.path.exists(project_path):
        proj = json.load(open(project_path))
    else:
        proj = {"title": title or "Playlist", "theme": title or "Playlist", "tracks": []}
    have = {t.get("audio") for t in proj["tracks"] if t.get("audio")}
    new = [t for t in tracks if not (t.get("audio") and t["audio"] in have)]
    at = len(proj["tracks"]) if position is None else position
    proj["tracks"][at:at] = new
    os.makedirs(os.path.dirname(os.path.abspath(project_path)), exist_ok=True)
    json.dump(proj, open(project_path, "w"), indent=1)
    return proj
