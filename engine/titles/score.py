"""Score a title 0-100 and say why. Relevance is a gate: a title that doesn't match the playlist can't rank."""
import re

from . import history, research

CLICKBAIT = {"shocking", "unbelievable", "insane", "gone wrong", "you won't believe", "exposed", "scam", "free money"}
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")


def score(title, ctx):
    """ctx: theme, artists[], track_titles[], suggestions[], keywords[], avoid[] (history). Returns (score, reasons)."""
    reasons, pts = [], 0.0
    low = title.lower()
    ttok = set(research.tokens(title))
    theme_tok = set(research.tokens(ctx["theme"]))
    # --- hard rejects
    if len(title) > 100:
        return 0, ["over YouTube's 100-character limit"]
    if any(c in low for c in CLICKBAIT):
        return 0, ["clickbait wording"]
    # --- relevance (40): must connect to the playlist's theme or its actual artists/songs
    theme_hit = len(theme_tok & ttok) / max(1, len(theme_tok))
    named = [a for a in ctx.get("artists", []) if a.lower() in low]
    named_songs = [t for t in ctx.get("track_titles", []) if t.lower() in low]
    rel = 25 * theme_hit + (10 if named else 0) + (5 if named_songs else 0)
    if rel < 10:
        return 0, ["not relevant: doesn't mention the theme, artists or songs"]
    pts += min(40, rel)
    reasons.append(f"relevance {min(40, rel):.0f}/40" + (f" (names {', '.join(named[:2])})" if named else ""))
    # --- length (20): full marks 40-70 chars (search results cut off around 70)
    n = len(title)
    ln = 20 if 40 <= n <= 70 else (14 if 30 <= n < 40 or 70 < n <= 85 else 8)
    pts += ln
    reasons.append(f"length {n} chars -> {ln}/20")
    # --- keyword up front (15)
    first = set(research.tokens(title[:40]))
    kp = 15 if theme_tok & first else 6
    pts += kp
    reasons.append(f"main keyword {'in first 40 chars' if kp == 15 else 'late'} -> {kp}/15")
    # --- demand (15): overlaps real search phrases / winners' keywords
    sug = {t for s in ctx.get("suggestions", []) for t in research.tokens(s)} - theme_tok
    win = set(ctx.get("keywords", [])[:10]) - theme_tok
    d = min(15, 5 * len(ttok & sug) + 3 * len(ttok & win))
    pts += d
    if d:
        reasons.append(f"matches search demand ({', '.join(sorted((ttok & sug) | (ttok & win))[:3])}) -> {d}/15")
    # --- hygiene (10)
    words = re.findall(r"[A-Za-z]{3,}", title)
    caps = sum(w.isupper() for w in words) / max(1, len(words))
    hy = 10 - (5 if caps > 0.5 else 0) - (3 if len(EMOJI.findall(title)) > 1 else 0) - (2 if "!!" in title else 0)
    pts += hy
    if hy < 10:
        reasons.append(f"style penalty -> {hy}/10")
    # --- repeats (penalty): too close to a title already used
    sim = max((history.similarity(title, a) for a in ctx.get("avoid", [])), default=0)
    if sim > 0.7:
        return 0, [f"too similar to an earlier title ({sim:.0%})"]
    if sim > 0.4:
        pts -= 15
        reasons.append(f"similar to an earlier title ({sim:.0%}) -> -15")
    return round(max(0, min(100, pts))), reasons
