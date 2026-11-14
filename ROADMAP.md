# Senora - roadmap and checklist

[x] done, [ ] planned. Rule that never changes: nothing is cut or changed in your audio unless you press the button.

## Done
- [x] Songs from YouTube links (yt-dlp) -> audio (FFmpeg) -> tags (Mutagen); Spotify links for details only
- [x] 1080p video: blurred-cover or night-sky background, spinning dark disc (6 styles), cover per song, hard cuts, channel-name mark
- [x] Timestamps from real durations; 4-step page with Back buttons; progress inside the page; delete playlists
- [x] Cut *recommendations* (extra audio after a fade, long silence, spoken words that look like talking) with Undo; manual cut stays
- [x] Volume between songs: measured, Before/After listening, off until you switch it on
- [x] Genre and mood detected from the songs (sound + YouTube tags + MusicBrainz + Groq); real artist from MusicBrainz
- [x] Titles and descriptions in the channel's own style (learned from 7 reference playlists); editable; picking a title only changes the title parts
- [x] Hashtags: 3 on top + 12-15 relevant ones (YouTube research, Groq, synonyms)
- [x] Thumbnails: 7 styles x 6 colours from your covers, pick 3 -> A/B/C files for YouTube's thumbnail test
- [x] Home library: 55 preset categories + your own, songs saved by link, make a playlist from a category; finished playlists as cards (watch / thumbnail / description / download / bin)
- [x] Cloud phase 1: `cloud-build` command, job file from the page, GitHub Actions workflows (`tests`, `cloud-check`, `build-playlist`), browser smoke test

## Before going all-in on the cloud
- [ ] Push to GitHub and get the `tests` workflow green (unit + smoke)
- [ ] Run `cloud-check`: does YouTube answer from GitHub's computers, and how long does 1080p take?
- [ ] One real playlist built by `build-playlist` and compared with the one built on the Mac

## Next updates (planned)
**Upload and automation**
- [ ] YouTube upload with an **Approve** button (Google OAuth, `videos.insert`, `thumbnails.set`, schedule, public/private)
- [ ] Set the A/B/C thumbnails automatically for YouTube's test (if the API allows it; otherwise guided by hand)
- [ ] Short teaser clips (30 s vertical) cut from each playlist
- [ ] Batch queue and a weekly schedule (3 videos a week)

**Thumbnails (more)**
- [ ] More styles and colours; your own backgrounds and fonts
- [ ] Record which thumbnail won each test and use it to order the styles

**Retention and engagement section (new part of the page)**
- [ ] Read YouTube Analytics after upload: views, click-through rate, average view duration, where viewers leave
- [ ] Per category / mood / title pattern / thumbnail style: what actually performed (replaces the 15 reference examples as the evidence)
- [ ] Suggest the next playlist's mood, title pattern and thumbnail from that data
- [ ] Alert when a video under-performs in its first 48 hours

**Hosting (phase 2)**
- [ ] The page online with a login; library and projects in a database; files in R2
- [ ] Start `build-playlist` from the page (GitHub token) and show progress
- [ ] Backups of the library

**Quality**
- [ ] Spoken-word detection with a trained model (needs a Python version that supports one) and more real test files
- [ ] Spotify audio source is not possible (details only); a licensed/own-files path stays as it is
- [ ] Visual regression checks for the thumbnails and video look
- [ ] Optional audio effects (slowed/sped-up, reverb, 8D, bass boost) as per-track switches, only for audio you may modify
