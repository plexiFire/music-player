"""Which songs of a playlist are already extracted, which still need extracting, and which were taken out.

The links are the truth (what you want in the playlist, in this order). Extracted tracks are matched to links by a stable key,
so you can add, remove or reorder links at any time - even while an extraction is running - and nothing already done is lost
or done twice. Pure functions, no server needed."""
import re


def link_key(link):
    """Same song, same key: youtu.be / watch?v= / music.youtube / shorts links of one video all give 'yt:<id>';
    other links are compared without tracking parameters (?si=..., #t=...)."""
    link = (link or "").strip()
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([\w-]{11})(?![\w-])", link)
    if m:
        return "yt:" + m.group(1)
    return re.sub(r"[?#].*$", "", link).rstrip("/")


def track_key(t):
    """The key of the link a track came from (new tracks store from_link; older ones fall back to source_link)."""
    return link_key(t.get("from_link") or t.get("source_link") or "")


def _usable(t):
    return bool(t.get("audio")) and not t.get("error")


def match(links, tracks):
    """-> (matched, removed): matched[i] = the list of tracks that belong to links[i] (in order), removed = tracks of no link now.
    A link listed twice gets its tracks in order (first link takes the first track, second link the second)."""
    pool = {}
    for t in tracks:
        pool.setdefault(track_key(t), []).append(t)
    matched = []
    for link in links:
        k = link_key(link)
        got = pool.get(k, [])
        # a link that expands to several songs (playlist, folder) owns all its tracks; a repeated link takes one at a time
        if got and sum(1 for l in links if link_key(l) == k) > 1:
            matched.append([got.pop(0)])
        else:
            matched.append(pool.pop(k, []))
    removed = [t for rest in pool.values() for t in rest]
    return matched, removed


def reconcile(links, tracks):
    """Tracks to keep, in the order of the links. Songs whose link is gone are dropped (their files stay on disk)."""
    matched, removed = match(links, tracks)
    legacy = [t for t in removed if not (t.get("from_link") or t.get("source_link"))]
    if legacy and len(legacy) == len([m for m in matched if not m]) and len(links) == len(tracks):
        # older projects: tracks without any link note. If the counts agree, trust the old positional order.
        it = iter(legacy)
        matched = [m or [next(it)] for m in matched]
        removed = [t for t in removed if t not in legacy]
    return [t for group in matched for t in group], removed


def plan(links, tracks):
    """What the Extract step shows: one row per link (done / pending / failed) plus the songs that were removed."""
    matched, removed = match(links, tracks)
    rows = []
    for link, group in zip(links, matched):
        if group and all(_usable(t) for t in group):
            rows.append({"link": link, "status": "done", "titles": [t.get("title", "") for t in group]})
        elif group:
            rows.append({"link": link, "status": "failed", "error": next((t.get("error") for t in group if t.get("error")), "no audio")})
        else:
            rows.append({"link": link, "status": "pending"})
    return {"rows": rows, "done": sum(r["status"] == "done" for r in rows), "pending": sum(r["status"] == "pending" for r in rows),
            "failed": sum(r["status"] == "failed" for r in rows),
            "removed": [{"title": t.get("title", ""), "artist": t.get("artist", "")} for t in removed]}


def todo(links, tracks):
    """Links that still need extracting: no track yet, or a failed one (so 'extract' also retries failures)."""
    return [r["link"] for r in plan(links, tracks)["rows"] if r["status"] != "done"]
