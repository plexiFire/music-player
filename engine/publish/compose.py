"""Build the YouTube description and tags for a project. The CLI build and the web UI both call these,
so what you preview in the page is exactly what the build writes."""
from . import text


def description_text(project, title, timestamps_text, theme=None):
    from ..titles.generate import mood_phrase
    theme = theme or project.get("theme") or project.get("title") or "Playlist"
    mood = project.get("mood", "")
    intro = project.get("intro") or (mood_phrase(mood) + ". Dim the lights, press play, and let the music do the rest."
                                     if mood else None)
    return text.description(title, theme, timestamps_text, project["tracks"], notice=project.get("notice"),
                            hashtags=project.get("hashtags", []), channel=project.get("channel"),
                            email=project.get("contact_email"), intro=intro, top_hashtags=project.get("top_hashtags"))


def tags_list(project, theme=None):
    from ..titles.generate import mood_phrase
    theme = theme or project.get("theme") or project.get("title") or "Playlist"
    mood = project.get("mood", "")
    extra = [x for x in ([f"{mood} playlist", mood_phrase(mood).lower()] if mood else []) if x]
    return text.tags(theme, project["tracks"], extra=extra)
