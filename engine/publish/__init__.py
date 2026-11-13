"""PUBLISH: everything you paste into YouTube besides the video.
text.py   - title ideas, tags, description (with timestamps and credits)
thumb.py  - 1280x720 thumbnail
compose.py - description + tags for a project (used by the build and by the UI preview)
"""
from .text import description, tags, title_ideas
from .compose import description_text, tags_list
from .thumb import thumbnail
