# Senora - Roadmap and future checklist

Status key: [x] done, [ ] planned. MVP audio rule: **tracks are used exactly as supplied. No audio processing.**

## Done (Milestone 1-2)
- [x] FFmpeg render engine: looping generated background, spinning vinyl, cover cross-fade per track
- [x] 1080p30 H.264 (CRF 16, slow) + AAC 256k final render; 720p fast preview
- [x] Accurate timestamps from real audio durations
- [x] Link / "Artist - Title" -> metadata + 1200px cover art (oEmbed + iTunes Search, no keys)
- [x] Audio matched from a local folder by name
- [x] Description, title ideas, tags, thumbnail (1280x720 JPEG < 2 MB)

- [x] Unified importer (`import`): yt-dlp / Spotify API metadata / FFmpeg processing / Mutagen tags -> project.json, with a rights gate

## Next (MVP completion)
- [ ] Tests for timestamps, metadata cleanup, library matching; render smoke test
- [ ] Real-music render check (quality, sync over a 20+ min video, memory)
- [ ] Jamendo adapter: link/search -> downloadable independent-artist MP3 (confirm free API terms first)
- [ ] Optional on-screen track name + artist text
- [ ] Background styles: colour palettes, speed, extra generators
- [ ] Simple local web UI (reorder, edit metadata, replace artwork, preview)

## Future: audio effects (planned, NOT in MVP)
Applied only to audio files the user owns or is licensed to use, as optional per-track or per-playlist switches:
- [ ] Slowed / sped-up (tempo + pitch)
- [ ] Reverb
- [ ] 8D / rotating-pan effect
- [ ] Bass boost / EQ presets
- [ ] Loudness normalisation across tracks (EBU R128)
- [ ] Crossfade / gapless transitions between songs (timestamps must stay exact)
- [ ] Per-track trim (start/end) and fade in/out

## Future: automation
- [ ] Telegram bot (send song list -> get video + title + description + thumbnail)
- [ ] Host the bot on GitHub-hosted infrastructure (check free-tier limits for long renders first)
- [ ] YouTube upload after manual approval
- [ ] Batch queue for several playlists
- [ ] Channel analytics log (CTR, AVD, subs, claims) for the 30-day validation plan
