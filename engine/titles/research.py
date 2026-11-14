"""Research: what titles already perform for a query. Keyless: yt-dlp search + YouTube autocomplete."""
import json
import math
import re
import shutil
import subprocess
import sys
from collections import Counter

import requests

STOP = set("""a an the and or of for to in on at with from by is are was be it its this that these those you your we our
i me my as vs ft feat official video audio lyrics lyric music songs song playlist mix best new top hours hour hd 4k full
part vol all more any can will when what who how why not no""".split())


# Words we may borrow from research because they describe a mood/time/use without claiming anything checkable.
# Artists, languages and genres (drake, hindi, r&b ...) are NEVER borrowed: they'd make the title untrue.
NEUTRAL = set("""sad chill slow romantic study studying sleep sleeping drive driving vibes vibe relax relaxing cozy dreamy
nostalgic emotional aesthetic rainy night evening morning moody soft calm acoustic mellow lonely heartbreak healing
focus peaceful comforting quiet dark deep warm gentle""".split())


# Genres and languages: never allowed in a title unless the playlist's own theme or mood says so (no false claims).
GENRES = set("""acoustic indie rock pop rap hip hop jazz lofi lo-fi edm metal country folk rnb bollywood hindi punjabi tamil telugu
kpop latin classical instrumental soul blues reggae house techno trap disco punk""".split())


# Times of day: the same rule (a "sunset" or "night" title for a "slow evening" playlist would be untrue).
TIMES = set("sunset sunrise twilight dusk dawn midnight morning afternoon noon night evening nighttime daybreak".split())


# Uses/activities: also never claimed unless the playlist says so ("for a drive", "to study to").
USES = set("drive driving drives study studying sleep sleeping workout gym running rainy road trip party work".split())


def allowed_words(theme, mood=""):
    m = tokens(mood)
    return {*tokens(theme), *m} if m else {*tokens(theme), *NEUTRAL}   # a stated mood overrides borrowed ones


def safe_phrase(phrase, allowed):
    """True if every meaningful word in a search phrase is neutral, from the theme, or from the user's mood."""
    words = re.findall(r"[a-z0-9&']+", phrase.lower())      # keep short words so 'r&b' can't hide as 'r','b'
    return bool(words) and all(w in allowed or w in STOP or w.isdigit() for w in words)


def _ytdlp():
    from ..sources.ytdlp import _ytdlp as base      # one place decides how yt-dlp is called (cookies included)
    return base()


def search(query, n=25):
    """Top YouTube results for query: [{title, views, duration, channel}], most viewed first. [] on failure."""
    try:
        r = subprocess.run(_ytdlp() + ["--flat-playlist", "--dump-json", "--no-warnings", f"ytsearch{n}:{query}"],
                           capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError):
        return []
    out = []
    for line in r.stdout.splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if j.get("title"):
            out.append({"title": j["title"], "views": j.get("view_count") or 0,
                        "duration": j.get("duration") or 0, "channel": j.get("channel") or ""})
    return sorted(out, key=lambda v: -v["views"])


def autocomplete(query):
    """Phrases people actually type into YouTube search that start with query. [] on failure."""
    try:
        r = requests.get("https://suggestqueries.google.com/complete/search",
                         params={"client": "firefox", "ds": "yt", "q": query}, timeout=10)
        r.raise_for_status()
        return [s for s in r.json()[1] if isinstance(s, str)]
    except (requests.RequestException, ValueError, IndexError):
        return []


def tokens(s):
    return [w for w in re.findall(r"[a-z0-9']+", s.lower()) if w not in STOP and len(w) > 2 and not w.isdigit()]


def analyse(videos, theme):
    """Patterns in the winners: weighted keywords + style stats. Weighted by log(views) so one viral title can't dominate."""
    theme_tokens = set(tokens(theme))
    kw = Counter()
    for v in videos:
        w = math.log10(max(v["views"], 10))
        for t in set(tokens(v["title"])):
            if t not in theme_tokens:
                kw[t] += w
    top = [v["title"] for v in videos[: max(5, len(videos) // 2)]]
    lens = sorted(len(t) for t in top)
    n = max(1, len(top))
    return {"keywords": [k for k, _ in kw.most_common(15)],
            "median_len": lens[len(lens) // 2] if lens else 0,
            "pct_pipe": round(100 * sum("|" in t for t in top) / n),
            "pct_brackets": round(100 * sum(bool(re.search(r"[\[\(]", t)) for t in top) / n),
            "pct_emoji": round(100 * sum(bool(re.search(r"[\U0001F300-\U0001FAFF☀-➿]", t)) for t in top) / n),
            "examples": top[:8]}


def gather(query, n=25):
    videos = search(query, n)
    return {"query": query, "videos": videos, "suggestions": autocomplete(query), "patterns": analyse(videos, query)}
