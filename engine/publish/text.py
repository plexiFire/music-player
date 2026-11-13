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
    t += [tr["title"] for tr in tracks if tr.get("title")]
    out, total = [], 0
    for x in dict.fromkeys(x for x in t if x):          # YouTube allows ~500 characters of tags in total
        if total + len(x) + 2 > 480 or len(out) >= 30:
            break
        out.append(x)
        total += len(x) + 2
    return out


def description(title, theme, timestamps_text, tracks, welcome=None, notice=None, hashtags=(),
                channel=None, email=None, intro=None, top_hashtags=None):
    """YouTube description: 3 hashtags on top (YouTube shows them above the title), welcome + short hook,
    tracklist with timestamps (first line must start at 0:00 so YouTube makes chapters), subscribe line,
    copyright notice with contact, and the full hashtag block at the end. No emojis; plain symbols only."""
    tags = [h.lstrip("#") for h in hashtags]
    top = [h.lstrip("#") for h in (top_hashtags or tags[:3])]
    out = []
    if top:
        out += [" ".join("#" + h for h in top), ""]
    out += [welcome or (f"Welcome to {channel}." if channel else "Welcome."), ""]
    named = re.sub(r"(?i)\bplaylist\b|\d+", "", theme or "")           # "Playlist 5" / "123" say nothing
    hook = "Dim the lights, press play, and let the music do the rest."
    out += [intro or (f"{theme}. {hook}" if len(re.findall(r"[A-Za-z]{3,}", named)) else hook), ""]
    out += ["\u25c6 TRACKLIST \u25c6"]
    for line in timestamps_text.splitlines():
        stamp, _, rest = line.partition(" ")
        out.append(f"{stamp} \u25b8 {rest}")           # '0:00 > Title - Artist': stamp stays at line start
    out += ["", "New playlists are added regularly. Subscribe and turn on notifications so you never miss one.", ""]
    out += ["\u25c6 COPYRIGHT NOTICE \u25c6",
            notice or ("All songs belong to their respective artists and labels. This playlist is shared for enjoyment "
                       "and discovery. If you are a rights holder and have a concern, please contact us and we will "
                       "respond promptly.")]
    if email:
        out.append(f"Contact: {email}")
    if tags:
        out += ["", " ".join("#" + h for h in tags)]
    return "\n".join(out).strip() + "\n"
