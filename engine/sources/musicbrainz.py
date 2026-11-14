"""MusicBrainz (open music database, no key): the real artist of a song, plus its community genre tags.
Used only when a track's artist is missing or is really the uploader (e.g. 'Anime Ringtones')."""
import re
import time

import requests

URL = "https://musicbrainz.org/ws/2/recording"
UA = {"User-Agent": "SenoraPlaylistTool/0.1 (open-source hobby project)"}
SOURCEY = re.compile(r"(?i)\b(ringtones?|records?|recordings|vevo|topic|official|channel|tv|entertainment|lyrics?|"
                     r"anytunz|tunes|music videos?|network|media|productions?|cover|karaoke|status|reels?)\b")
NOT_ORIGINAL = re.compile(r"(?i)\b(cover|emulation|8-?bit|karaoke|tribute|remix|flip|instrumental|piano version|lullaby|"
                          r"made famous|originally performed|ringtone|reprise|slowed|sped up|nightcore|arcade)\b")
_last = [0.0]


def looks_like_source(artist):
    """True when the 'artist' is really an uploader/channel label rather than a person or band."""
    return not artist or bool(SOURCEY.search(artist))


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2}


def lookup(title, hint="", timeout=15):
    """-> {"title", "artist", "tags"} for the best match, or None. Never raises. Obeys MusicBrainz's 1 request/second rule."""
    q = re.sub(r"(?i)\b(ringtones?|official|video|audio|lyrics?|hd|marimba|nokia)\b|[()\[\]\"]", " ", f"{title} {hint}")
    q = re.sub(r"\s+", " ", q).strip()
    if not q or (not _words(hint) and len(re.findall(r"[A-Za-z0-9']+", q)) < 3):
        return None                                 # a short title with no artist clue ('Unforgettable') matches the wrong song
    for attempt in range(3):
        wait = 1.1 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = requests.get(URL, params={"query": q, "fmt": "json", "limit": 12}, headers=UA, timeout=timeout)
        except requests.RequestException:
            return None
        if r.status_code == 503:                    # rate limited: back off and retry
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code != 200:
            return None
        want = _words(title) | _words(hint)
        for rec in r.json().get("recordings", []):
            names = [a["name"] for a in rec.get("artist-credit", []) if isinstance(a, dict) and a.get("name")]
            # accept only a confident hit whose title or artist shares words with what we know
            if NOT_ORIGINAL.search(rec["title"] + " " + " ".join(names)) and not NOT_ORIGINAL.search(q):
                continue                                    # covers, remixes, emulations: never the real artist
            if looks_like_source(" ".join(names)):
                continue
            if rec.get("score", 0) >= 90 and names and (_words(rec["title"]) | _words(" ".join(names))) & want \
                    and _words(rec["title"]) & want:
                return {"title": rec["title"], "artist": " & ".join(names[:2]) if len(names) > 1 else names[0],
                        "tags": [t["name"] for t in rec.get("tags", [])][:6]}
        return None
    return None


def fix_artists(tracks):
    """Replace a missing/uploader-style artist by the real one. Returns notes for the log. Touches nothing else."""
    notes = []
    for t in tracks:
        if not looks_like_source(t.get("artist", "")):
            continue
        hit = lookup(t.get("title", ""), t.get("artist", ""))
        if hit:
            notes.append(f"{t.get('title')} - {t.get('artist') or '?'}  ->  {hit['title']} - {hit['artist']}")
            t["artist_was"] = t.get("artist", "")
            t["title"], t["artist"] = hit["title"], hit["artist"]
            t["web_tags"] = list(dict.fromkeys(t.get("web_tags", []) + [x.lower() for x in hit["tags"]]))
        elif t.get("artist") and SOURCEY.search(t["artist"]):
            t["artist_was"], t["artist"] = t["artist"], ""        # no real artist found: show the song alone, never the uploader
            notes.append(f"{t.get('title')}: dropped uploader label '{t['artist_was']}'")
    return notes
