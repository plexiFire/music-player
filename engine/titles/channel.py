"""The channel's own title + description style, learned from 7 reference playlists (views are as seen on the pages).

What the references share (measured by analyse() below):
  * every title starts '[Playlist] ', then 22-48 characters, 4-8 words, sentence case
  * one feeling, spoken to the listener; never a genre, an artist, a song, a number or an emoji
  * three openings only: 'Songs that feel/make you ...', 'Songs worth ...', 'When music is ...'
"""
import re

from . import history, research

REFERENCE = [   # (title, views, channel subscribers)
    ("music that makes your soul leave your body", 300511, 389),
    ("When music is all you need", 263323, 749),
    ("When music is all you need", 5120667, 14700),
    ("Songs worth hearing again", 972256, 14700),
    ("When music is what i need", 406287, 11500),
    ("songs that feel like a dream", 465935, 1530),
    ("Songs that make you believe in love", 3033, 14700),
]
PREFIX = "[Playlist] "
FEELING = set("you your feel feels make makes miss believe dream dreams memory memories need again soul heart quiet slow breath "
              "take takes worth hearing love hold stay still world little softer".split())

# feeling -> title endings in the channel's voice (all true to a playlist of that mood; none is a reference title)
BANK = {
    ("sad", "melancholy", "heartbreak", "lonely", "emotional"): [
        "Songs for when you miss someone", "Songs that hurt in a good way", "Songs that understand how you feel",
        "Songs that say what you can't", "Music for the quiet in your head", "When music is the only thing that listens",
        "Songs that make it okay to feel", "Songs for the ones you never said goodbye to", "Music that sits with you when you're low",
        "Songs for when words run out", "Songs that feel like missing someone", "When music is the only one who gets it",
        "Songs to cry a little to", "Songs that stay after midnight thoughts"],
    ("chill", "calm", "slow", "mellow", "peaceful", "relax"): [
        "Songs to slow down with", "Songs that feel like a deep breath", "Music for when the world is too loud",
        "Songs that make everything feel softer", "Songs to sit quietly with", "When music is how you rest",
        "Songs that let you breathe out", "Music for the slow moments", "Songs that make time move gently",
        "Songs for when you need to unwind", "Music that feels like a soft landing", "When music is the calm you need",
        "Songs that quiet the noise", "Songs worth slowing down for"],
    ("nostalgic", "memories", "throwback"): [
        "Songs that take you back", "Songs that feel like a memory", "Songs you forgot you loved",
        "Songs that remind you of someone", "Music that brings it all back", "Songs worth hearing again",
        "Songs that sound like an old summer", "Music for the days you miss", "Songs that feel like coming home",
        "When music is a time machine", "Songs that bring back who you were", "Songs that still feel like then"],
    ("dreamy", "dream", "aesthetic", "warm"): [
        "Songs that feel like floating", "Music that makes you drift away", "Songs for your own little world",
        "Songs that make ordinary moments feel like a movie", "Music for daydreaming", "Songs that feel like a soft glow",
        "When music turns the day into a dream", "Songs that make the world feel far away"],
    ("romantic", "love"): [
        "Songs that make you fall a little more", "Songs for the one you can't forget", "Songs that feel like holding on",
        "Songs that make you believe in someone", "Music for the ones you love", "When music sounds like their name",
        "Songs for butterflies you can't explain", "Songs that feel like a slow dance"],
    ("upbeat", "energetic", "feel good", "happy"): [
        "Songs that make everything feel better", "Songs for a good day", "Music that lifts you up",
        "Songs that make you move without noticing", "When music is all the energy you need", "Songs to turn the day around",
        "Music that puts a smile on your face", "Songs that feel like a green light"],
    ("dark", "late night", "night"): [
        "Songs for the hours nobody talks about", "Music for when you can't sleep", "Songs that keep you company",
        "Songs for the quiet after midnight", "Music for the city asleep", "Songs for the long way home",
        "When music is the only light on", "Songs that feel like 3 AM thoughts"],
}
GENERIC = ["Songs worth a second listen", "Songs that stay with you", "Songs for when you need them most",
           "Music that feels like it knows you"]


def bank_for(moods):
    out = []
    ms = [m.lower() for m in moods]
    for keys, endings in BANK.items():
        if any(k in " ".join(ms) for k in keys):
            out += endings
    return out or GENERIC


def candidates(moods):
    return [PREFIX + e for e in dict.fromkeys(bank_for(moods))]


def sentence_case(body):
    body = re.sub(r"\s+", " ", body).strip().rstrip(".")
    body = re.sub(r"\bi\b", "I", body.lower())
    return body[:1].upper() + body[1:]


def normalise(title):
    """Force the channel look: '[Playlist] ' + sentence case (the references have no names inside, so lowering is safe)."""
    body = re.sub(r"^\s*\[playlist\]\s*", "", title, flags=re.I)
    return PREFIX + sentence_case(body)


def analyse(refs=REFERENCE):
    """Numbers behind the rules above, measured from the references (used by the tests and the Groq prompt)."""
    bodies = [t for t, _, _ in refs]
    lens = sorted(len(b) for b in bodies)
    words = sorted(len(b.split()) for b in bodies)
    first = {}
    for b in bodies:
        w = b.split()[0].lower()
        first[w] = first.get(w, 0) + 1
    return {"len_min": lens[0], "len_max": lens[-1], "len_median": lens[len(lens) // 2],
            "words_min": words[0], "words_max": words[-1], "openings": first}


def score(title, ctx):
    """0-100 closeness to the channel style, 0 if it breaks a hard rule. ctx: moods/genre/artists/track_titles/avoid."""
    if not title.startswith(PREFIX):
        return 0, ["must start with [Playlist]"]
    body = title[len(PREFIX):]
    low = body.lower()
    if re.search(r"[|:\d]|[^\x00-ɏ’]", body):
        return 0, ["no numbers, colons, pipes or emojis"]
    if any(c in low for c in ("secret", "shocking", "you won't believe", "must listen", "viral")):
        return 0, ["clickbait wording"]
    names = [x.lower() for x in ctx.get("artists", []) + ctx.get("track_titles", []) if x and len(x) > 3]
    if any(n in low for n in names):
        return 0, ["names an artist or song (the channel style never does)"]
    stated = set(research.tokens(" ".join(ctx.get("moods", [])) + " " + ctx.get("genre", "")))
    claimed = [w for w in re.findall(r"[a-z]+", low) if (w in research.GENRES or w in research.TIMES or w in research.USES)
               and w not in stated]
    if claimed:
        return 0, [f"claims '{claimed[0]}', which the songs don't say"]
    if any(low == t.lower() for t, _, _ in REFERENCE):
        return 0, ["identical to a reference title"]
    s, why = 0, []
    n = len(body)
    s += 30 if 22 <= n <= 48 else max(0, 30 - 3 * min(abs(n - 22) if n < 22 else abs(n - 48), 10))
    nw = len(body.split())
    s += 20 if 4 <= nw <= 8 else 6
    first = low.split()[0]
    s += 20 if first in ("songs", "music", "when") else 8
    s += min(15, 5 * len(set(re.findall(r"[a-z]+", low)) & FEELING))
    s += 15 if not any(ch.isupper() for ch in body[1:]) else 5
    s -= 25 * max([history.similarity(title, a) for a in ctx.get("avoid", [])] or [0]) ** 2   # don't repeat old titles
    return max(0, round(s)), why or ["matches the channel style"]


def llm_prompt(ctx, n):
    ex = "\n".join(f"- {PREFIX}{t}  ({v:,} views, channel of {s:,} subscribers)" for t, v, s in REFERENCE)
    a = analyse()
    return (
        f"You write YouTube titles for a music-playlist channel. Here are real titles from this channel's niche that did well:\n{ex}\n\n"
        f"Their shared pattern: they start with '[Playlist] ', then {a['len_min']}-{a['len_max']} characters ({a['words_min']}-{a['words_max']} words), "
        "sentence case, ONE feeling spoken to the listener ('you'), openings like 'Songs that feel like ...', "
        "'Songs that make you ...', 'Songs worth ...', 'When music is ...', 'Music for ...'. "
        "They never name a genre, artist or song, never use numbers, colons, pipes or emojis, and never claim a time of day or an activity.\n\n"
        f"This playlist feels: {', '.join(ctx.get('moods', [])) or 'n/a'}. Genre (do NOT put it in the title): {ctx.get('genre') or 'n/a'}.\n"
        f"Write {n} NEW titles in exactly that style, each with a different feeling or angle. Do not copy the examples. "
        "Do not resemble these earlier titles:\n" + "\n".join(f"- {t}" for t in ctx.get("avoid", [])[:12]) + "\n"
        'Reply with JSON only: {"titles": ["[Playlist] ...", "..."]}')


def hook_prompt(title, ctx):
    return (f"Playlist title: {title}\nFeeling: {', '.join(ctx.get('moods', []))}\n"
            "Write ONE short sentence (max 16 words) for the top of the video description that completes the feeling of the title, "
            "in a warm plain voice, no emojis, no genre, no artist names, no quotes. Example for 'Songs that make you believe in love': "
            "'Some songs make you believe in love a little more.' Reply with the sentence only.")


CORE = {  # feeling -> the hashtag the references use for it
    "sad": "sadplaylist", "melancholy": "sadplaylist", "emotional": "sadplaylist", "lonely": "sadplaylist",
    "late night": "latenightplaylist", "dark": "latenightplaylist", "night": "latenightplaylist",
    "dream": "dreamyplaylist", "dreamy": "dreamyplaylist", "warm": "dreamyplaylist",
    "chill": "chillmusic", "relax": "chillmusic", "calm": "chillmusic", "slow": "chillmusic", "mellow": "chillmusic",
    "nostalgic": "nostalgicmusic", "romantic": "romanticplaylist", "love": "lovesongs",
    "upbeat": "feelgoodplaylist", "energetic": "feelgoodplaylist", "feel good": "feelgoodplaylist",
}
GENRE_TAG = {"indie pop": "indieplaylist", "indie": "indieplaylist", "pop": "popmusic", "alternative": "alternativeplaylist",
             "rock": "rockplaylist", "r&b": "rnbplaylist", "hip hop": "hiphopplaylist", "jazz": "jazzplaylist",
             "lofi": "lofiplaylist", "folk": "folkplaylist", "acoustic": "acousticplaylist"}


def hashtags(ctx, title, channel="", pool=None, extra=None, total=15):
    """Top 3 (shown above the title by YouTube) + the full block, 12-15 tags: the channel's own, the title as a tag,
    the feeling tags the references use, then researched / Groq / synonym tags (see hashtags.py)."""
    from . import hashtags as H
    feel = []
    for m in ctx.get("moods", []):
        for k, t in CORE.items():
            if k in m.lower() and t not in feel:
                feel.append(t)
    g = ctx.get("genre", "").lower().replace("lo-fi", "lofi")
    genre = [GENRE_TAG[g]] if g in GENRE_TAG else next(([t] for k, t in sorted(GENRE_TAG.items(), key=lambda kv: kv[0] != "lofi") if k in g), [])
    # always 3 on top (YouTube shows three above the title); top up with the channel's fixed mood tags
    top = list(dict.fromkeys(feel[:2] + genre + ["aestheticplaylist"] + feel[2:] + ["dreamyplaylist", "chillmusic"]))[:3]
    slug = re.sub(r"[^a-z0-9]", "", title.replace(PREFIX, "").lower())
    block = []
    if channel:
        block.append(re.sub(r"[^a-z0-9]", "", channel.lower()) + "playlist")
    if 8 <= len(slug) <= 40:
        block.append(slug[:1].upper() + slug[1:])
    block += top + feel + genre + ["aestheticplaylist", "dreamyplaylist"]
    seen, full = set(), []
    for t in block + H.choose(ctx, list(pool or []), list(extra or []), total=total):
        k = t.lower()
        if k not in seen and k != "playlist":
            seen.add(k)
            full.append(t)
    return top, full[:total]
