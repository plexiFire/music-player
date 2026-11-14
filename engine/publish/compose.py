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
