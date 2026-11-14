"""Your song library: songs you listened to and sorted into categories (sad songs, gym songs, late night ...).
Only links and metadata are stored (title, artist, thumbnail address, length, tags). No audio is downloaded here."""
import json
import os
import re
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

PRESETS = {
    "Time of day": ["Morning walk songs", "Morning energy", "Afternoon focus", "Evening chill", "Late night songs",
                    "Dark night songs", "3 AM thoughts", "Sunrise", "Sunset drive"],
    "Mood": ["Sad songs", "Heartbreak", "Lonely", "Nostalgic", "Dreamy", "Romantic", "Happy and feel good",
             "Calm and peaceful", "Angry and intense", "Hopeful", "Moody"],
    "Activity": ["Gym songs", "Running", "Study and focus", "Work from home", "Road trip", "Cooking", "Cleaning",
                 "Cycling", "Meditation", "Sleep"],
    "Weather and season": ["Rainy day", "Monsoon", "Winter cozy", "Summer vibes", "Autumn"],
    "Style": ["Indie", "Lo-fi", "Acoustic", "Pop", "Hip hop", "R&B", "Rock", "Electronic", "Bollywood",
              "Classical and instrumental", "Jazz"],
    "Occasion": ["Party", "Friends hangout", "Date night", "Breakup", "Wedding", "Birthday"],
    "Era": ["2000s throwback", "90s classics", "2010s hits"],
}
_lock = threading.RLock()


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "category"


def preset_categories():
    return [{"id": slug(n), "name": n, "group": g, "builtin": True} for g, names in PRESETS.items() for n in names]


class Library:
    def __init__(self, path):
        self.path = str(path)

    # ---- storage (atomic write, same idea as the project files) ----
    def _load(self):
        try:
            return json.load(open(self.path))
        except (OSError, ValueError):
            return {"custom": [], "songs": {}}

    def _save(self, d):
        tmp = self.path + ".tmp"
        json.dump(d, open(tmp, "w"), indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    # ---- categories ----
    def categories(self):
        with _lock:
            d = self._load()
            cats = preset_categories() + [{**c, "group": "My categories", "builtin": False} for c in d["custom"]]
            out = []
            for c in cats:
                songs = d["songs"].get(c["id"], [])
                out.append({**c, "count": len(songs), "minutes": round(sum(s.get("duration") or 0 for s in songs) / 60, 1)})
            return out

    def add_category(self, name):
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            raise ValueError("give the category a name")
        with _lock:
            d = self._load()
            ids = {c["id"] for c in preset_categories()} | {c["id"] for c in d["custom"]}
            cid = slug(name)
            if cid in ids:
                raise ValueError("a category with that name already exists")
            d["custom"].append({"id": cid, "name": name, "created": time.time()})
            self._save(d)
            return cid

    def delete_category(self, cid):
        """Custom categories only; presets can't be deleted (they just stay empty). Removes the saved entries, never files."""
        with _lock:
            d = self._load()
            if cid not in {c["id"] for c in d["custom"]}:
                raise ValueError("built-in categories can't be deleted")
            d["custom"] = [c for c in d["custom"] if c["id"] != cid]
            d["songs"].pop(cid, None)
            self._save(d)

    def _known(self, d, cid):
        return cid in {c["id"] for c in preset_categories()} | {c["id"] for c in d["custom"]}

    # ---- songs ----
    def songs(self, cid):
        with _lock:
            d = self._load()
            if not self._known(d, cid):
                raise KeyError(cid)
            return list(d["songs"].get(cid, []))

    def add_songs(self, cid, links, fetch):
        """fetch(link) -> {title, artist, duration, cover_url, id, web_tags, views, source_link}. Returns (added, problems)."""
        links = [l.strip() for l in links if l.strip()]
        with ThreadPoolExecutor(4) as ex:
            got = list(ex.map(lambda l: _safe(fetch, l), links))
        added, problems = [], []
        with _lock:
            d = self._load()
            if not self._known(d, cid):
                raise KeyError(cid)
            have = d["songs"].setdefault(cid, [])
            seen = {s.get("vid") or s["link"] for s in have}
            for link, (meta, err) in zip(links, got):
                if err:
                    problems.append({"link": link, "error": err})
                    continue
                key = meta.get("id") or link
                if key in seen:
                    problems.append({"link": link, "error": "already in this category"})
                    continue
                seen.add(key)
                song = {"id": uuid.uuid4().hex[:8], "vid": meta.get("id") or "", "link": meta.get("source_link") or link,
                        "title": meta.get("title") or link, "artist": meta.get("artist") or "", "duration": meta.get("duration") or 0,
                        "cover_url": meta.get("cover_url") or "", "views": meta.get("views") or 0,
                        "tags": (meta.get("web_tags") or [])[:20], "added": time.time(), "used_in": []}
                have.append(song)
                added.append(song)
            self._save(d)
        return added, problems

    def remove_song(self, cid, sid):
        with _lock:
            d = self._load()
            before = len(d["songs"].get(cid, []))
            d["songs"][cid] = [s for s in d["songs"].get(cid, []) if s["id"] != sid]
            if len(d["songs"][cid]) == before:
                raise KeyError(sid)
            self._save(d)

    def copy_song(self, cid, sid, to, move=False):
        with _lock:
            d = self._load()
            if not self._known(d, to):
                raise KeyError(to)
            song = next((s for s in d["songs"].get(cid, []) if s["id"] == sid), None)
            if not song:
                raise KeyError(sid)
            dest = d["songs"].setdefault(to, [])
            if not any((s.get("vid") or s["link"]) == (song.get("vid") or song["link"]) for s in dest):
                dest.append({**song, "id": uuid.uuid4().hex[:8], "added": time.time()})
            if move:
                d["songs"][cid] = [s for s in d["songs"][cid] if s["id"] != sid]
            self._save(d)

    def mark_used(self, cid, sids, playlist_name):
        with _lock:
            d = self._load()
            for s in d["songs"].get(cid, []):
                if s["id"] in sids:
                    s.setdefault("used_in", []).append({"playlist": playlist_name, "at": time.time()})
            self._save(d)

    # ---- the data side ----
    def stats(self, cid):
        songs = self.songs(cid)
        artists = Counter(s["artist"] for s in songs if s.get("artist"))
        tags = Counter(t for s in songs for t in set(s.get("tags", [])) if 2 < len(t) < 25)
        views = [s["views"] for s in songs if s.get("views")]
        total = sum(s.get("duration") or 0 for s in songs)
        return {"songs": len(songs), "minutes": round(total / 60, 1), "top_artists": artists.most_common(5),
                "top_tags": tags.most_common(8), "avg_views": int(sum(views) / len(views)) if views else 0,
                "never_used": sum(1 for s in songs if not s.get("used_in")),
                "ready": len(songs) >= 5 and total >= 15 * 60}


def friendly_error(raw):
    """Plain words for the usual reasons a link can't be read."""
    low = raw.lower()
    for key, words in (("not a valid url", "this does not look like a song link"), ("unsupported url", "this site is not supported: use a YouTube or Spotify song link"),
                       ("not a bot", "YouTube is asking this computer to prove it is not a bot: wait a few minutes and try again"),
                       ("private video", "this video is private"), ("unavailable", "this video is unavailable (removed, private or blocked in your country)"),
                       ("sign in", "YouTube wants a sign-in for this video (age-restricted?)"), ("timed out", "the site took too long to answer: try again"),
                       ("playlist", "this is a playlist link: paste a single song link"), ("urlopen", "no internet connection")):
        if key in low:
            return words
    return ((raw.splitlines() or ["could not read this link"])[-1])[:160]


def _safe(fetch, link):
    try:
        return fetch(link), None
    except Exception as e:
        return None, friendly_error(str(e))
