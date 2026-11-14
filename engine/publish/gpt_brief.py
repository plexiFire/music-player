"""One text you can paste (or a zip you can upload) into ChatGPT so it understands this playlist video, how it was made, the style rules
learned from the reference channels, and what to improve. Nothing secret goes in: the contact e-mail is replaced by a placeholder,
and no audio, no video and no local paths are included."""
import re

from ..titles import channel
from . import thumbs

# the eight reference thumbnails that the styles were learned from (views as seen when they were studied; brightness/saturation measured)
THUMB_STUDY = [
    (3840035, 0.27, 0.43, "night photo, big concept title ('Late Night Melodies') with four covers around it"),
    (2846410, 0.32, 0.12, "black-and-white swirl, serif 'Playlist', six covers"),
    (485216, 0.54, 0.47, "sunset bokeh, small sans 'Playlist', six covers"),
    (303150, 0.56, 0.46, "illustration with a meme equation ('= peak')"),
    (284536, 0.47, 0.44, "cloudy sky, big condensed concept title, four covers and two chat bubbles"),
    (71796, 0.42, 0.12, "swirl, huge bold title, video-length badge, six covers"),
    (52263, 0.55, 0.60, "autumn illustration, italic 'Playlist', six covers"),
    (21446, 0.48, 0.41, "snow photo, no text at all"),
]
YOUTUBE_RULES = [
    "Only up to 3 hashtags from the description are shown above the video title.",
    "More than 60 hashtags on a video: YouTube ignores all of them.",
    "Hashtags must be directly related to the video; unrelated or misleading ones can get the video removed.",
    "No spaces inside a hashtag.",
]
PROMPT = """I run a YouTube music-playlist channel. Below is everything about ONE finished playlist video: the songs, the thumbnail styles,
the title and description my tool wrote, and the research the tool's style is based on. Please:
1. Tell me what is weak, generic or risky in the title, description, hashtags and thumbnail.
2. Give me 10 new title options in the same style (same pattern rules, nothing that is untrue for these songs).
3. Rewrite the description in the same structure (keep the tracklist exactly as given).
4. Give me 12-15 hashtags (a mix of big and small ones) that follow the YouTube rules listed below.
5. Suggest 3 thumbnail concepts (text, colours, layout) that fit the reference findings, and say which one you would test first.
Only use what is true for these songs. If something I gave you looks wrong, say so."""


def mmss(sec):
    sec = int(round(float(sec or 0)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def redact(text, email):
    return text.replace(email, "<my contact email>") if email else text


def build(project, description, title, title_options, built_files, my_question=""):
    """project: the project dict (tracks, profile, settings). description/title: the texts as they will be posted.
    title_options: [{"title","score","source"}]. built_files: names found in the output folder."""
    tracks = project.get("tracks", [])
    prof = project.get("profile") or {}
    total = sum(float(t.get("duration") or 0) for t in tracks)
    out = ["# Brief for ChatGPT: one playlist video", "", "## What I want from you", PROMPT, "",
           f"MY QUESTION: {my_question or '(write it here)'}", "", "## The video"]
    out += [f"- channel: {project.get('channel') or '(not set)'}",
            f"- songs: {len(tracks)}, total length {mmss(total)}",
            f"- look: dark disc ({project.get('disc', 'vinyl')}), background {((project.get('background') or {}).get('mode') or 'cover')}"
            + (f" ({(project.get('background') or {}).get('color')})" if (project.get("background") or {}).get("color") else "")
            + ", channel-name mark in the bottom-right corner, hard cuts between songs",
            f"- volume evened out between songs: {'yes' if project.get('level_audio') else 'no'}",
            f"- built: {'yes (' + ', '.join(built_files) + ')' if built_files else 'not built yet'}", ""]
    out += ["## Songs in order", "", "| # | starts | song | artist | length | detected tags | source |", "|---|---|---|---|---|---|---|"]
    t0 = 0.0
    for i, t in enumerate(tracks, 1):
        tags = ", ".join((t.get("web_tags") or [])[:5])
        out.append(f"| {i} | {mmss(t0)} | {t.get('title', '')} | {t.get('artist') or '-'} | {mmss(t.get('duration'))} | {tags or '-'} | {t.get('source_link') or '-'} |")
        t0 += float(t.get("duration") or 0)
    out += ["", "## What the tool detected from the songs",
            f"- genre: {', '.join(prof.get('genres') or []) or 'unclear'}", f"- mood: {', '.join(prof.get('moods') or []) or 'unclear'}",
            f"- sources of that guess: {', '.join(prof.get('source') or []) or 'n/a'}", ""]
    out += ["## Title", f"Chosen: **{title}**", ""]
    if title_options:
        out += ["Other options it offered:"] + [f"- {o['title']} (score {o.get('score', '?')}, {o.get('source', '')})" for o in title_options[:12]] + [""]
    out += ["## Description exactly as it will be posted", "```", description.strip(), "```", ""]
    last = description.strip().splitlines()[-1] if description.strip() else ""
    out += ["## Hashtags used", " ".join(re.findall(r"#\w+", last)) or "(none)", ""]
    picks = project.get("thumbs_selected") or []
    out += ["## Thumbnails", "Thumbnail text rule: header-style thumbnails always say 'PlayList'; concept-style ones use a short phrase picked from the mood, never the playlist name."]
    if picks:
        out += ["Chosen for YouTube's thumbnail test (A, B, C):"] + [f"- {'ABC'[i]}: style '{p['family']}', colour '{p['variant']}'" for i, p in enumerate(picks[:3])]
    else:
        out += ["No thumbnail styles chosen yet."]
    out += ["(The image files are in the zip pack, if I attached it.)", "", "Available styles: " + "; ".join(
        f"{f['id']} ({thumbs.REFERENCE[f['id']]['note']})" for f in thumbs.FAMILIES), ""]
    a = channel.analyse()
    out += ["## How my titles are written (learned from 7 reference playlists)",
            f"- always starts with '[Playlist] ', then {a['len_min']}-{a['len_max']} characters, {a['words_min']}-{a['words_max']} words, sentence case",
            "- one feeling spoken to the listener; never a genre, artist, song name, number, colon, pipe or emoji; never claims a time of day or activity",
            "- openings used: 'Songs that feel/make you ...', 'Songs worth ...', 'When music is ...', 'Music for ...'",
            "- reference titles with views (sample is small, so this is a pattern, not proof):"]
    out += [f"  - [Playlist] {t} ({v:,} views, channel of {s:,} subscribers)" for t, v, s in channel.REFERENCE]
    out += ["", "## How my descriptions are structured",
            "1. three hashtags on the first line (YouTube shows them above the title)", "2. 'Welcome to <channel>.'",
            "3. one hook sentence that finishes the feeling of the title + 'Press play, get comfortable, and let the music do the rest.'",
            "4. tracklist with timestamps (first line starts at 0:00 so YouTube makes chapters)",
            "5. 'New playlists added often. Subscribe so you never miss one.'", "6. copyright notice + contact line",
            "7. 12-15 hashtags at the end: channel tag, the title as a tag, mood and genre tags, a mix of big and small", "",
            "## Thumbnail research: eight reference thumbnails", "", "| views | brightness (0-1) | saturation | style |", "|---|---|---|---|"]
    out += [f"| {v:,} | {b} | {s} | {d} |" for v, b, s, d in THUMB_STUDY]
    out += ["", "Findings (n=8, a hint not a proof): darker thumbnails got more views (rank correlation of brightness with views -0.48); "
            "saturation showed no link (-0.05); the top five all had clear text, the least viewed had none; concept titles such as "
            "'Late Night Melodies' appeared at the top.", "", "## YouTube rules that apply"]
    out += [f"- {r}" for r in YOUTUBE_RULES]
    return redact("\n".join(out) + "\n", project.get("contact_email") or "")
