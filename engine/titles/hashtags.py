"""Hashtag engine. YouTube's rules (official help page): up to 3 hashtags from the description show above the title;
more than 60 on a video and ALL are ignored; hashtags must be directly related to the video or it may be removed.

Sources, merged and filtered for relevance:
  1. research: hashtags + tags used by the top YouTube videos for the playlist's mood/genre (yt-dlp, weighted by views)
  2. Groq: broad and niche hashtags for this playlist (optional)
  3. bank: synonyms of the detected moods/genres, so there are always enough
Every candidate must pass relevance (names a detected mood/genre/synonym or a generic playlist word) and the blocklist.
"""
import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import llm, research

GENERIC = {"playlist", "music", "songs", "song", "vibes", "vibe", "mix", "aesthetic", "newmusic", "playlists", "mood", "tracks", "listen"}
BLOCK = {"shorts", "short", "subscribe", "fyp", "viral", "trending", "like", "follow", "free", "foryou", "foryoupage", "reels",
         "youtube", "youtuber", "ringtone", "ringtones", "copyrightfree", "nocopyright", "nocopyrightmusic", "dj", "remix"}
SYN = {   # detected word -> related hashtag words people use (kept to ones that are true for that feeling)
    "chill": ["chillmusic", "chillplaylist", "chillvibes", "chillsongs", "relaxingmusic", "chillbeats"],
    "relaxed": ["relaxingmusic", "relaxplaylist", "chillvibes"], "calm": ["calmmusic", "peacefulmusic", "relaxingmusic"],
    "slow": ["slowsongs", "slowplaylist", "slowmusic"], "mellow": ["mellowvibes", "mellowmusic"],
    "sad": ["sadsongs", "sadplaylist", "sadmusic", "sadvibes", "heartbreaksongs", "emotionalsongs"],
    "melancholy": ["melancholy", "sadsongs", "sadplaylist", "emotionalsongs"],
    "emotional": ["emotionalsongs", "emotionalmusic", "sadsongs"],
    "nostalgic": ["nostalgicmusic", "nostalgia", "nostalgicsongs", "throwbacksongs"],
    "dreamy": ["dreamyplaylist", "dreampop", "dreamyvibes", "dreamymusic"],
    "romantic": ["romanticplaylist", "lovesongs", "lovemusic", "romanticsongs"],
    "upbeat": ["feelgoodmusic", "feelgoodplaylist", "happysongs"], "energetic": ["energymusic", "feelgoodplaylist"],
    "feel good": ["feelgoodmusic", "feelgoodplaylist", "happysongs"], "dark": ["darkmusic", "darkvibes", "moodymusic"],
    "warm": ["warmvibes", "cozyplaylist", "cozymusic"], "late night": ["latenightplaylist", "latenightvibes", "latenightmusic"],
}
GENRE_SYN = {
    "indie pop": ["indiepop", "indiepopplaylist", "indieplaylist", "indiemusic"], "indie": ["indieplaylist", "indiemusic", "indievibes"],
    "pop": ["popmusic", "popplaylist", "popsongs"], "alternative": ["alternativemusic", "altplaylist", "alternativeplaylist"],
    "rock": ["rockmusic", "rockplaylist"], "r&b": ["rnbmusic", "rnbplaylist", "rnbsongs"],
    "hip hop": ["hiphopmusic", "hiphopplaylist", "rapmusic"], "lofi": ["lofi", "lofibeats", "lofiplaylist", "lofimusic"],
    "jazz": ["jazzmusic", "jazzplaylist"], "folk": ["folkmusic", "folkplaylist"], "acoustic": ["acousticmusic", "acousticplaylist"],
    "electronic": ["electronicmusic", "electronicplaylist"], "soul": ["soulmusic", "soulplaylist"], "bollywood": ["bollywoodsongs", "hindisongs"],
}
BROAD = ["musicplaylist", "songsplaylist", "playlistvibes", "newplaylist", "musicvibes"]


def _ytdlp():
    from ..sources.ytdlp import _ytdlp as base      # one place decides how yt-dlp is called (cookies included)
    return base()


def _tags_in(text):
    return [t.lower() for t in re.findall(r"#([A-Za-z0-9_]{3,30})", text or "")]


def _video(url):
    try:
        r = subprocess.run(_ytdlp() + ["-j", "--skip-download", "--no-playlist", "--no-warnings", url],
                           capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        j = json.loads(r.stdout)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    tags = _tags_in(j.get("description", "")) + [re.sub(r"[^a-z0-9]", "", str(t).lower()) for t in (j.get("tags") or [])]
    return {"views": j.get("view_count") or 0, "tags": [t for t in tags if 3 <= len(t) <= 30]}


def research_pool(queries, per_query=8):
    """Hashtags used by the most-viewed videos for the queries. -> [{tag, weight, videos}] best first. [] on failure."""
    urls = []
    for q in queries:
        try:
            r = subprocess.run(_ytdlp() + ["--flat-playlist", "--dump-json", "--no-warnings", f"ytsearch{per_query + 6}:{q}"],
                               capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
        except (subprocess.TimeoutExpired, OSError):
            continue
        got = []
        for line in r.stdout.splitlines():
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if j.get("url") or j.get("id"):
                got.append((j.get("view_count") or 0, j.get("url") or f"https://www.youtube.com/watch?v={j['id']}"))
        urls += [u for _, u in sorted(got, reverse=True)[:per_query]]
    urls = list(dict.fromkeys(urls))
    with ThreadPoolExecutor(6) as ex:
        vids = [v for v in ex.map(_video, urls) if v]
    weight, seen = Counter(), defaultdict(int)
    for v in vids:
        w = math.log10(max(v["views"], 10))
        for t in set(v["tags"]):
            weight[t] += w
            seen[t] += 1
    return [{"tag": t, "weight": round(w, 1), "videos": seen[t]} for t, w in weight.most_common(80)]


def _allowed_words(ctx):
    ws = set()
    for m in ctx.get("moods", []):
        ws |= set(re.findall(r"[a-z]+", m.lower()))
    g = ctx.get("genre", "").lower().replace("lo-fi", "lofi")
    ws |= set(re.findall(r"[a-z]+", g))
    for k in list(SYN) + list(GENRE_SYN):
        if k in " ".join(ctx.get("moods", [])).lower() or k == g or k in g.split():
            ws |= set(re.findall(r"[a-z]+", k))
    return ws


def relevant(tag, ctx):
    """True if a hashtag is clearly about this playlist: mentions a detected mood/genre word or a generic playlist word,
    and is not on the blocklist, not a track/artist name, not a number."""
    t = re.sub(r"[^a-z0-9]", "", tag.lower())
    stated = _allowed_words(ctx)
    if re.search(r"\d", t):                                   # '...2024' tags go stale; numbers say nothing about the songs
        return False
    uses = set(research.USES) | {"study", "work", "background", "sleep", "focus", "gaming", "cooking"}
    if any(u in t for u in uses if u not in stated):          # 'studymusic' / 'nightdrive' claim a use the songs don't have
        return False
    if not (3 <= len(t) <= 30) or t in BLOCK or any(b in t for b in ("ringtone", "subscribe", "viral", "fyp")):
        return False
    names = {re.sub(r"[^a-z0-9]", "", x.lower()) for x in ctx.get("artists", []) + ctx.get("track_titles", [])}
    if any(n and len(n) > 3 and n in t for n in names):
        return False
    return any(w in t for w in _allowed_words(ctx) if len(w) > 2) or any(g in t for g in GENERIC)


def bank(ctx):
    out = []
    ms = " ".join(ctx.get("moods", [])).lower()
    for k, v in SYN.items():
        if k in ms:
            out += v
    g = ctx.get("genre", "").lower().replace("lo-fi", "lofi")
    for k, v in sorted(GENRE_SYN.items(), key=lambda kv: -len(kv[0])):
        if k in g:
            out += v
            break
    return out + BROAD


def groq_tags(ctx):
    """Ask Groq for broad and niche hashtags for this playlist. [] if no key or on error."""
    key = llm._env("GROQ_API_KEY")
    if not key:
        return []
    p = (f"A YouTube music playlist: moods {', '.join(ctx.get('moods', []))}; genre {ctx.get('genre') or 'unclear'}. "
         "Give 14 hashtags that listeners of this playlist really search or click: 6 broad (big audience) and 8 niche (smaller, specific). "
         "Rules: single words or joined words, lowercase, no # sign, no artist or song names, no ringtones, nothing that is not directly "
         'true for this playlist. Reply with JSON only: {"broad": ["..."], "niche": ["..."]}')
    try:
        r = llm._chat(key, p, temperature=0.4, json_mode=True)
        j = json.loads(re.search(r"\{.*\}", r.json()["choices"][0]["message"]["content"], re.S).group(0))
        return [re.sub(r"[^a-z0-9]", "", str(x).lower()) for x in j.get("broad", []) + j.get("niche", [])]
    except Exception:
        return []


def choose(ctx, pool=(), extra=(), total=15):
    """Final hashtag list, best first, mixing big-audience and small specific tags. Deduplicated, relevance-filtered."""
    ordered = []
    big = [p["tag"] for p in pool if p["videos"] >= 3]
    small = [p["tag"] for p in pool if p["videos"] < 3]
    bk = bank(ctx)
    # interleave: bank core, big research, niche (groq/research), more bank: so the set is wide, not one theme repeated
    lanes = [bk[:4], big, list(extra), small, bk[4:]]
    i = 0
    while any(lanes) and len(ordered) < total * 3:
        lane = lanes[i % len(lanes)]
        if lane:
            ordered.append(lane.pop(0))
        i += 1
        if i > 2000:
            break
    out, seen = [], set()
    for t in ordered:
        k = re.sub(r"[^a-z0-9]", "", t.lower())
        if k not in seen and relevant(k, ctx):
            seen.add(k)
            out.append(k)
        if len(out) >= total:
            break
    return out
