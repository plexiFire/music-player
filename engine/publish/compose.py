"""Build the YouTube description and tags for a project. The CLI build and the web UI both call these,
so what you preview in the page is exactly what the build writes."""
from . import text


def _ctx(project):
    prof = project.get("profile") or {}
    typed = [m.strip() for m in (project.get("mood") or "").split(",") if m.strip()]
    return {"moods": typed or prof.get("moods") or [], "genre": prof.get("genre", ""),
            "artists": [t["artist"] for t in project.get("tracks", []) if t.get("artist")],
            "track_titles": [t["title"] for t in project.get("tracks", []) if t.get("title")]}


def hook_for(project, title, use_llm=False):
    """One sentence that finishes the feeling of the title (Groq, else the title itself), then the channel's closing line."""
    from ..titles import channel, llm
    ctx = _ctx(project)
    first = (llm.sentence(channel.hook_prompt(title, ctx)) if use_llm else None) \
        or channel.sentence_case(title.replace(channel.PREFIX, "")) + "."
    return first.rstrip() + " Press play, get comfortable, and let the music do the rest."


def sync_tracklist(desc, timestamps_text):
    """Put the CURRENT timestamps into the TRACKLIST block of a (possibly hand-edited) description, and touch nothing else. A cut, a removed
    song or a new order changes the timestamps; the text you wrote around them stays. No TRACKLIST block = nothing to do."""
    lines = desc.split("\n")
    head = next((i for i, l in enumerate(lines) if "TRACKLIST" in l.upper() and "\u25c6" in l), None)
    if head is None:
        return desc
    end = head + 1
    while end < len(lines) and lines[end].strip():
        end += 1
    new = []
    for line in timestamps_text.splitlines():
        stamp, _, rest = line.partition(" ")
        new.append(f"{stamp} \u25b8 {rest}")
    return "\n".join(lines[:head + 1] + new + lines[end:])


def title_tag(title):
    """The hashtag made from the title (#Songsthattakeyouback), as written by channel.hashtags."""
    import re
    from ..titles import channel
    slug = re.sub(r"[^a-z0-9]", "", title.replace(channel.PREFIX, "").lower())
    return (slug[:1].upper() + slug[1:]) if 8 <= len(slug) <= 40 else ""


def hook_paragraph(desc):
    """The hook paragraph of a generated description (third block: hashtags / welcome / hook)."""
    parts = desc.strip().split("\n\n")
    return parts[2] if len(parts) > 2 else ""


def retitle(desc, old_title, new_title, old_hook=""):
    """The title changed: update ONLY what comes from the title (the hook line and the title hashtag) in a description
    that may have been edited by hand. Anything else - your wording, hashtags you added - is left exactly as it is."""
    import re
    old_hook = old_hook or hook_for({}, old_title)
    new_hook = hook_for({}, new_title)
    if old_hook and old_hook in desc:
        desc = desc.replace(old_hook, new_hook, 1)
    ot, nt = title_tag(old_title), title_tag(new_title)
    if ot:
        desc = re.sub(r"#" + re.escape(ot) + r"\b", "#" + nt if nt else "", desc, count=1, flags=re.I)
        desc = re.sub(r"[ \t]{2,}", " ", desc)
    elif nt:
        pass
    return desc


def description_text(project, title, timestamps_text, theme=None, use_llm=False):
    from ..titles import channel
    theme = theme or project.get("theme") or project.get("title") or "Playlist"
    tags = [h.lstrip("#") for h in (project.get("hashtags") or [])]
    if tags:
        top, full = tags[:3], tags
    else:
        from ..titles import hashtags as H
        ctx = _ctx(project)
        top, full = channel.hashtags(ctx, title, project.get("channel") or "",
                                     pool=(project.get("profile") or {}).get("tag_pool"),
                                     extra=H.groq_tags(ctx) if use_llm else None)
    intro = project.get("intro") or hook_for(project, title, use_llm)
    return text.description(title, theme, timestamps_text, project["tracks"], notice=project.get("notice"),
                            hashtags=full, channel=project.get("channel"), email=project.get("contact_email"),
                            intro=intro, top_hashtags=project.get("top_hashtags") or top)


def tags_list(project, theme=None):
    from ..titles.generate import mood_phrase
    theme = theme or project.get("theme") or project.get("title") or "Playlist"
    mood = project.get("mood", "")
    extra = [x for x in ([f"{mood} playlist", mood_phrase(mood).lower()] if mood else []) if x]
    return text.tags(theme, project["tracks"], extra=extra)
