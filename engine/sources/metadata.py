"""Turn a song link (YouTube / Spotify / Apple) or 'Artist - Title' text into metadata + artwork.

Uses only free, keyless endpoints: oEmbed (YouTube, Spotify) and the iTunes Search API.
Links are used for METADATA ONLY. Audio comes from files supplied by the user.
"""
import re
import requests

UA = {"User-Agent": "senora-studio/0.1"}
OEMBED = {
    "youtube.com": "https://www.youtube.com/oembed",
    "youtu.be": "https://www.youtube.com/oembed",
    "open.spotify.com": "https://open.spotify.com/oembed",
}
_NOISE = re.compile(
    r"[\(\[][^\)\]]*(official|video|audio|lyric|visualizer|hd|4k|remaster|isolated|live)[^\)\]]*[\)\]]",
    re.I)


def clean_title(raw):
    t = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", raw or "")   # invisible characters
    t = t.split(" | ")[0]                                          # 'Song | keyword | keyword' -> 'Song'
    t = _NOISE.sub("", t)
    t = re.sub(r"\s*-\s*Topic\s*$", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -|")


def is_url(s):
    return s.strip().lower().startswith(("http://", "https://"))


def oembed(url):
    host = re.sub(r"^https?://(www\.)?", "", url.strip().lower()).split("/")[0]
    ep = OEMBED.get(host)
    if not ep:
        return None
    r = requests.get(ep, params={"url": url, "format": "json"}, headers=UA, timeout=15)
    r.raise_for_status()
    return r.json()


def itunes_search(query):
    r = requests.get("https://itunes.apple.com/search",
                     params={"term": query, "entity": "song", "limit": 5},
                     headers=UA, timeout=15)
    r.raise_for_status()
    return r.json().get("results", [])


def _tokens(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def score(query, hit):
    q = _tokens(query)
    h = _tokens(hit.get("trackName", "") + " " + hit.get("artistName", ""))
    return len(q & h) / max(1, len(q))


def display_title(track_name, query):
    """Drop '(... Live)', '[Remastered]' etc. unless the user's own text mentions them."""
    q = _tokens(query)
    def keep(m):
        toks = _tokens(m.group(0))
        return m.group(0) if toks and toks <= q else ""
    t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", keep, track_name)
    return re.sub(r"\s+", " ", t).strip() or track_name


def hires(art_url, size=1200):
    return re.sub(r"/\d+x\d+(bb)?\.(jpg|png)$", f"/{size}x{size}bb.jpg", art_url)


def resolve(line):
    """line: URL or free text. Returns dict (never raises on lookup failure; flags it)."""
    line = line.strip()
    fallback_cover, query, source = None, line, "text"
    if is_url(line):
        source = "link"
        try:
            o = oembed(line)
        except requests.RequestException:
            o = None
        if o:
            query = clean_title(o.get("title", ""))
            fallback_cover = o.get("thumbnail_url")
            # YouTube titles are usually 'Artist - Song'; Spotify gives the song only
            if "youtube" in line or "youtu.be" in line:
                query = query or clean_title(o.get("author_name", ""))
    hits = []
    try:
        hits = itunes_search(query)
    except requests.RequestException:
        pass
    best = max(hits, key=lambda h: score(query, h), default=None)
    if best and score(query, best) >= 0.5:
        return {"title": display_title(best["trackName"], query), "artist": best["artistName"],
                "album": best.get("collectionName", ""),
                "duration": best.get("trackTimeMillis", 0) / 1000,
                "cover_url": hires(best["artworkUrl100"]), "source": source,
                "query": query, "needs_review": False}
    return {"title": query, "artist": "", "album": "", "duration": 0,
            "cover_url": fallback_cover, "source": source, "query": query,
            "needs_review": True}


def download_cover(url, path):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    with open(path, "wb") as fh:
        fh.write(r.content)
    return path
