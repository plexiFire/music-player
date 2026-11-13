"""TITLES: data-informed, relevant, non-repeating YouTube titles for review.
research.py - what already performs: yt-dlp search results (views) + YouTube autocomplete phrases
generate.py - candidates: data-filled templates (always) + optional Groq LLM
score.py    - relevance / length / keyword / demand / hygiene score, with reasons
history.py  - remembers titles already offered so playlists don't repeat each other
llm.py      - Groq chat API client (GROQ_API_KEY)
pipeline.py - suggest(): the one function the CLI calls
"""
from .pipeline import context, suggest
