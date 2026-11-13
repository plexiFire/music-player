"""Candidate titles from data-filled templates. Deterministic per playlist, different across playlists."""
import hashlib
import random
import re
from datetime import date

HOOKS = ["songs you'll want on repeat", "press play and stay a while", "for the quiet hours", "songs that stay with you",
         "turn it up and unwind", "your next favourite songs", "slow down with these", "songs for when words aren't enough",
         "the soundtrack to your evening", "playlist to get lost in", "songs worth replaying", "one more song, then sleep"]


def nice(s):
    s = s.strip()
    return s if re.search(r"[A-Z]", s) else s.title()


TEMPLATES = [
    "{Theme} Playlist | {hook}",
    "[Playlist] {Theme} - {hook}",
    "{Theme} 🎧 {hook}",
    "{a1}, {a2} & More | {Theme} Playlist",
    "{Sug}",
    "{Sug} | {a1}, {a2}, {a3}",
    "{n} Songs {hook_short} | {Theme} ({year})",
    "{kw} {Theme} Playlist {year}",
    "{Theme} Playlist ({kw}) | {t1} & {t2} and more",
    "{Sug} - {hook}",
    "{a1} x {a2} | {Theme} Playlist",
    "Playlist: {Theme} - {kw}, {kw2}",
]


def candidates(ctx, limit=40):
    seed = int(hashlib.sha256((ctx["theme"] + "|".join(ctx.get("avoid", [])[-5:])).encode()).hexdigest(), 16)
    rng = random.Random(seed)
    artists = list(dict.fromkeys(ctx.get("artists", [])))
    songs = list(dict.fromkeys(ctx.get("track_titles", [])))
    kws = [k.title() for k in ctx.get("keywords", [])[:10]] or [""]
    core = re.sub(r"\bplaylist\b", "", ctx["theme"], flags=re.I).strip() or ctx["theme"]  # templates add "Playlist" themselves
    sugs = [nice(s) for s in ctx.get("suggestions", [])[1:] if len(s) > len(ctx["theme"])] or [""]
    out = []
    for _ in range(limit * 4):
        t = rng.choice(TEMPLATES)
        hook = rng.choice(HOOKS)
        slots = {"Theme": nice(core), "hook": hook, "hook_short": "You'll Replay", "year": str(date.today().year),
                 "n": str(len(songs) or ""), "kw": rng.choice(kws), "kw2": rng.choice(kws), "Sug": rng.choice(sugs),
                 "a1": artists[0] if artists else "", "a2": artists[1] if len(artists) > 1 else "",
                 "a3": artists[2] if len(artists) > 2 else "", "t1": songs[0] if songs else "",
                 "t2": songs[1] if len(songs) > 1 else ""}
        used = re.findall(r"\{(\w+)\}", t)
        if any(not slots[u] for u in used) or (len(songs) < 3 and "{n}" in t):
            continue
        title = re.sub(r"\s+", " ", t.format(**slots)).strip()
        if title not in out:
            out.append(title)
        if len(out) >= limit:
            break
    return out
