"""suggest(): research -> candidates (templates + optional Groq) -> score -> diverse top N for review."""
from . import generate, history, llm, research, score


def context(project, mood="", research_data=None, avoid=(), theme=None):
    tracks = project.get("tracks", [])
    r = research_data or {}
    p = r.get("patterns", {})
    theme = theme or project.get("theme") or project.get("title") or "Playlist"
    ok = research.allowed_words(theme, mood + " " + (project.get("profile") or {}).get("genre", ""))      # truthfulness filter: no borrowed artists / languages / genres
    sugs = [x for x in r.get("suggestions", []) if research.safe_phrase(x, ok)]
    moods = research.tokens(mood)
    # the user's own mood words win; research words (neutral ones only) are used only when no mood was given
    kws = moods or [k for k in p.get("keywords", []) if k in ok]
    kws = [k for k in dict.fromkeys(kws) if k not in set(research.tokens(theme))]
    mood = mood or project.get("mood", "")
    return {"theme": theme, "mood": mood, "genre": (project.get("profile") or {}).get("genre", ""), "prefer_bracket": project.get("title_style", "bracket") == "bracket",
            "artists": [t["artist"] for t in tracks if t.get("artist")],
            "track_titles": [t["title"] for t in tracks if t.get("title")],
            "tracks_text": [f"{t['title']} - {t['artist']}" if t.get("artist") else t["title"] for t in tracks],
            "suggestions": sugs, "keywords": kws, "patterns": p,
            "avoid": list(avoid)}


def suggest(project, n=10, query=None, mood="", use_llm=True, online=True, history_path=None, project_name="",
            record=True):
    """Returns {"titles": [{title, score, reasons, source}], "research": {...}, "warnings": [...]}"""
    avoid = history.titles(history_path) if history_path else []
    theme = query or project.get("theme") or project.get("title") or "Playlist"
    prof = project.get("profile") or {}
    mood = mood or project.get("mood") or prof.get("mood") or ""     # nothing typed: use what the songs themselves say
    mood_q = mood.split(",")[0].strip()
    if not mood_q and not research.tokens(theme) and not query:
        # a name like "1234" says nothing and there is no mood: guessing would only give junk titles
        return {"titles": [], "research": {"query": "", "videos": [], "suggestions": [], "patterns": {}},
                "warnings": ["Extract the songs first: the mood and genre are detected from them (or type a mood)."]}
    rq = query or prof.get("query") or (f"{mood_q} playlist" if mood_q else theme)        # what people actually search for
    data = research.gather(rq) if online else {"query": rq, "videos": [], "suggestions": [], "patterns": {}}
    ctx = context(project, mood, data, avoid, theme)
    warnings = []
    if online and not data["videos"]:
        warnings.append("YouTube research returned nothing (offline or blocked): ranking uses the playlist only")
    cands = [(t, "template") for t in generate.candidates(ctx)]
    if use_llm:
        got, warn = llm.titles(ctx, n=max(n, 8))
        cands += [(t, "groq") for t in got]
        if warn:
            warnings.append(warn)
    scored = []
    seen = set()
    for t, src in cands:
        if t in seen:
            continue
        seen.add(t)
        s, why = score.score(t, ctx)
        if s > 0:
            scored.append({"title": t, "score": s, "reasons": why, "source": src})
    scored.sort(key=lambda c: -c["score"])
    if ctx.get("prefer_bracket"):          # the channel's title style: '[Playlist] ...' (keep others only if too few)
        bracket = [c for c in scored if c["title"].startswith("[Playlist]")]
        if len(bracket) >= min(n, 3):
            scored = bracket
    chosen, openings = [], {}
    for c in scored:  # keep the list diverse: no near-identical options, max 2 per opening
        key = " ".join(c["title"].lower().split()[:4])
        if openings.get(key, 0) < 2 and all(history.similarity(c["title"], x["title"]) < 0.6 for x in chosen):
            chosen.append(c)
            openings[key] = openings.get(key, 0) + 1
        if len(chosen) >= n:
            break
    if record:                       # a preview must not mark titles as used
        history.record(history_path, [c["title"] for c in chosen], project_name)
    return {"titles": chosen, "research": data, "warnings": warnings}
