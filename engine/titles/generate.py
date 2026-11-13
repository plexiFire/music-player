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


MOOD_NOUNS = {"evening", "night", "morning", "afternoon", "drive", "walk", "commute", "weekend", "rain", "sunset",
              "sunrise", "study", "workout", "dinner", "coffee", "trip", "day", "nights", "evenings", "mornings"}


def mood_phrase(mood):
    """'slow evening' -> 'Songs for a slow evening';  'sad' -> 'Sad songs';  '' -> ''."""
    mood = (mood or "").split(",")[0].strip()
    if not mood:
        return ""
    if mood.lower().split()[-1] in MOOD_NOUNS:
        return f"Songs for a {mood.lower()}"
    return f"{mood.capitalize()} songs"


def mood_templates(mood):
    """'[Playlist] ...' titles built from the mood phrase. Noun-like moods ('slow evening') read as 'for a slow evening';
    adjective moods ('sad') read as 'sad songs'."""
    if not mood:
        return []
    last = mood.lower().split()[-1]
    if last in MOOD_NOUNS:
        return ["[Playlist] Songs for a {mood}", "[Playlist] Songs for your {mood}", "[Playlist] {Mood} Songs - {hook}",
                "[Playlist] {a1}, {a2} and more for a {mood}"]
    return ["[Playlist] {Mood} Songs - {hook}", "[Playlist] Songs that feel {mood}", "[Playlist] {Mood} Songs for {kw}"]


def candidates(ctx, limit=40):
    seed = int(hashlib.sha256((ctx["theme"] + "|".join(ctx.get("avoid", [])[-5:])).encode()).hexdigest(), 16)
    rng = random.Random(seed)
    artists = list(dict.fromkeys(ctx.get("artists", [])))
    songs = list(dict.fromkeys(ctx.get("track_titles", [])))
    kws = [k.title() for k in ctx.get("keywords", [])[:10]] or [""]
    core = re.sub(r"\bplaylist\b", "", ctx["theme"], flags=re.I).strip() or ctx["theme"]  # templates add "Playlist" themselves
    from .research import tokens as _tok
    if not _tok(core):                       # a name like "Playlist 5" says nothing: use the mood, or skip theme templates
        core = (ctx.get("mood") or "").split(",")[0].strip()
    sugs = [nice(s) for s in ctx.get("suggestions", [])[1:] if len(s) > len(ctx["theme"])] or [""]
    out = []
    mood = (ctx.get("mood") or "").split(",")[0].strip()
    mt = mood_templates(mood)
    pool = TEMPLATES + mt * 4            # mood titles are weighted up: they are the style we want
    for _ in range(limit * 4):
        t = rng.choice(pool)
        hook = rng.choice(HOOKS)
        slots = {"Theme": nice(core), "hook": hook, "hook_short": "You'll Replay", "year": str(date.today().year),
                 "n": str(len(songs) or ""), "kw": rng.choice(kws), "kw2": rng.choice(kws), "Sug": rng.choice(sugs),
                 "a1": artists[0] if artists else "", "a2": artists[1] if len(artists) > 1 else "",
                 "a3": artists[2] if len(artists) > 2 else "", "t1": songs[0] if songs else "",
                 "t2": songs[1] if len(songs) > 1 else "", "mood": mood.lower(), "Mood": nice(mood) if mood else ""}
        used = re.findall(r"\{(\w+)\}", t)
        if any(not slots[u] for u in used) or (len(songs) < 3 and "{n}" in t):
            continue
        title = re.sub(r"\s+", " ", t.format(**slots)).strip()
        if title not in out:
            out.append(title)
        if len(out) >= limit:
            break
    return out
