"""Title ideas, tags and description - generated locally, no API."""
import re

STOP = {"songs", "music", "playlist", "best", "with", "that", "from"}


def title_ideas(theme, mood=""):
    base = theme.strip()
    m = mood.strip()
    ideas = [f"[Playlist] {base}",
             f"[Playlist] {base} - for when you need them",
             f"{base} | a playlist for quiet hours",
             f"[Playlist] {base} - press play and stay a while",
             f"{base} playlist ({m or 'all moods'})"]
    return list(dict.fromkeys(ideas))


def tags(theme, tracks, extra=()):
    words = re.findall(r"[A-Za-z0-9']+", theme.lower())
    t = ["playlist", "music playlist", theme.lower(), *extra]
    t += [f"{w} playlist" for w in words if len(w) > 3 and w not in STOP]
    t += [tr["artist"] for tr in tracks if tr.get("artist")]
    return list(dict.fromkeys(x for x in t if x))[:25]


def description(title, theme, timestamps_text, tracks, welcome=None, notice=None, hashtags=()):
    parts = [welcome or f"Welcome. {theme} - a playlist to keep you company.",
             "", "Tracklist", timestamps_text, ""]
    albums = [f"{tr['title']} - {tr['artist']}" + (f" ({tr['album']})" if tr.get("album") else "")
              for tr in tracks]
    parts += ["Music credits"] + albums + [""]
    if notice:
        parts += [notice, ""]
    hs = " ".join("#" + re.sub(r"\W+", "", h) for h in hashtags)
    if hs:
        parts.append(hs)
    return "\n".join(parts).strip() + "\n"
