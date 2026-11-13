def fmt(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build(tracks, durations):
    """tracks: list of dicts with title/artist; durations: seconds. Returns (starts, text)."""
    starts, t = [], 0.0
    for d in durations:
        starts.append(t)
        t += d
    lines = [f"{fmt(s)} {tr['title']}" + (f" - {tr['artist']}" if tr.get("artist") else "")
             for tr, s in zip(tracks, starts)]
    return starts, "\n".join(lines)
