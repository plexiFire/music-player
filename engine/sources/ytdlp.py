"""yt-dlp: metadata extraction and AUTHORIZED audio download.

Downloads are allowed only when
  * the source declares a Creative Commons licence (e.g. YouTube's CC-BY flag), or
  * the user attests they own / are licensed to use the audio (authorized=True / --authorized).
Anything else is refused. Metadata extraction never downloads media.
"""
import json
import os
import shutil
import subprocess
import sys

from . import metadata


class NotAuthorized(RuntimeError):
    pass


def _ytdlp():
    exe = shutil.which("yt-dlp")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]


def info(url):
    """Extract metadata (no download). Returns a normalised dict."""
    r = subprocess.run(_ytdlp() + ["-J", "--no-playlist", "--no-warnings", url],
                       capture_output=True, text=True)
    if r.returncode != 0:
        last = (r.stderr.strip().splitlines() or ["yt-dlp failed"])[-1]
        raise RuntimeError(f"yt-dlp could not read {url}: {last}")
    j = json.loads(r.stdout)
    artist = j.get("artist") or j.get("creator") or ""
    title = j.get("track") or j.get("title") or ""
    if not artist and " - " in title:  # 'Artist - Song' uploads
        artist, title = title.split(" - ", 1)
    chan = metadata.clean_title(j.get("channel") or j.get("uploader") or "")
    if not artist and chan.endswith(" - Topic"):      # YouTube's auto-made artist channels carry the real artist name
        artist = chan.removesuffix(" - Topic")        # any other channel is only the uploader (a source), never an artist
    artist = metadata.clean_title(artist)
    return {"title": metadata.clean_title(title), "artist": artist.strip(),
            "album": j.get("album") or "", "duration": float(j.get("duration") or 0),
            "cover_url": j.get("thumbnail"), "license": j.get("license") or "",
            "id": j.get("id"), "extractor": j.get("extractor_key"),
            "source_link": j.get("webpage_url") or url, "source": "ytdlp"}


def authorization(meta, attested=False):
    """Return the rights basis ('creative-commons' | 'user-attested') or raise NotAuthorized."""
    if "creative commons" in (meta.get("license") or "").lower():
        return "creative-commons"
    if attested:
        return "user-attested"
    raise NotAuthorized(
        f"'{meta.get('title') or meta.get('source_link')}' has no Creative Commons licence. "
        "Download refused. If you own it or are licensed to use it, confirm with --authorized.")


def fetch_audio(url, out_dir, attested=False, meta=None):
    """Download the best audio of one URL into out_dir after the rights check.

    Returns (path, meta, basis). The file keeps its native format; convert it with audio.process.
    """
    meta = meta or info(url)
    basis = authorization(meta, attested)
    os.makedirs(out_dir, exist_ok=True)
    r = subprocess.run(
        _ytdlp() + ["-f", "bestaudio/best", "--no-playlist", "--no-warnings", "--retries", "5",
                    "--extractor-retries", "3",
                    "-o", os.path.join(out_dir, "%(id)s.%(ext)s"),
                    "--print", "after_move:filepath", url],
        capture_output=True, text=True)
    paths = [l for l in r.stdout.splitlines() if l.strip()]
    if r.returncode != 0 or not paths or not os.path.exists(paths[-1]):
        raise RuntimeError("download failed: " + (r.stderr.strip().splitlines() or ["unknown error"])[-1])
    return paths[-1], meta, basis


def download(urls, out_dir, video=False, audio_format="mp3", playlist=False, attested=False):
    """Bulk download for the `download` command. Each URL is rights-checked first."""
    os.makedirs(out_dir, exist_ok=True)
    rc = 0
    for u in urls:
        try:
            authorization(info(u), attested)
        except NotAuthorized as e:
            print("REFUSED:", e, file=sys.stderr)
            rc = 1
            continue
        cmd = _ytdlp() + ["-o", os.path.join(out_dir, "%(title)s.%(ext)s"),
                          "--yes-playlist" if playlist else "--no-playlist",
                          "--embed-thumbnail", "--add-metadata"]
        if video:
            cmd += ["-f", "bv*+ba/b", "--merge-output-format", "mp4"]
        else:
            cmd += ["-x", "--audio-format", audio_format, "--audio-quality", "0"]
        rc = subprocess.call(cmd + [u]) or rc
    return rc
