"""SOURCES: where tracks and their metadata come from.
metadata.py - 'Artist - Title' / YouTube / Spotify oEmbed -> title, artist, cover (iTunes lookup)
spotify.py  - Spotify Web API metadata (never audio)
ytdlp.py    - yt-dlp: metadata extraction + rights-checked audio download
library.py  - match a track to an audio file in a folder
"""
