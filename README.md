# Senora - playlist video studio (local, free)

Turns a song list + your audio files into a finished YouTube-style playlist video:
looping background, spinning vinyl, cover art that changes per song, timestamps,
title ideas, description, tags and thumbnail.

## Install (macOS)
    brew install ffmpeg            # already present on this machine
    python3 -m venv .venv && .venv/bin/pip install numpy pillow mutagen requests fastapi "uvicorn[standard]" pytest

## Use
1. Put one song per line in a text file, in play order (a YouTube/Spotify link or `Artist - Title`).
   Links are used for metadata and artwork only.
2. Put your audio files (files you own or are licensed to use) in a folder.
3. Resolve, review, build:

       .venv/bin/python -m engine.cli resolve songs.txt --audio-dir my_audio --title "Late Night" -o work/project.json
       .venv/bin/python -m engine.cli build work/project.json -o out/late-night.mp4 --preview   # fast 720p
       .venv/bin/python -m engine.cli build work/project.json -o out/late-night.mp4             # final 1080p

   Any row marked REVIEW needs a manual fix in project.json (title, artist, audio or cover path).
   Output: `.mp4`, `.description.txt`, `.titles.txt`, `.thumbnail.jpg`.

## Folder mode (no links file needed)
Put your audio files in a folder and run:

    .venv/bin/python -m engine.cli folder my_audio --title "Event Chill" -o work/project.json
    .venv/bin/python -m engine.cli build work/project.json -o out/event.mp4

Title and artist come from the files' tags (or the filename). Cover art comes from the file's embedded art,
else an online lookup (`--offline` to skip), else a plain cover. Add `--order order.txt` (one filename per line)
to set the play order; the rest follow alphabetically.

## Quick start: links -> finished video (manual, step by step)
Run from the `senora/senora` folder. Only use audio you own, are licensed to use, or that is Creative Commons.

    # 1. one-time setup (see Install above), then for Spotify links only:
    export SPOTIFY_CLIENT_ID=...  SPOTIFY_CLIENT_SECRET=...

    # 2. list your sources, one per line, in play order -> sources.txt
    #    https://youtu.be/<id>                                   (web audio)
    #    https://open.spotify.com/track/<id> | my_audio/Song.flac (Spotify metadata + your own audio file)
    #    my_audio/Artist - Song.wav                              (local file)

    # 3. import: downloads/converts/tags audio and adds tracks to work/project.json
    .venv/bin/python -m engine.cli import --file sources.txt --title "Late Night" --authorized --project work/project.json

    # 4. check the output: any "AUDIO MISSING" / SKIPPED line needs fixing (add the audio file, or edit project.json)
    # 5. build: fast 720p preview first, then the final 1080p
    .venv/bin/python -m engine.cli build work/project.json -o out/late-night.mp4 --preview
    .venv/bin/python -m engine.cli build work/project.json -o out/late-night.mp4

Result in `out/`: `.mp4`, `.description.txt`, `.titles.txt`, `.thumbnail.jpg`.
Useful import flags: `--format mp3|m4a|flac|wav`, `--normalize`, `--offline`, `--library <folder>`, `--audio-dir <folder>`.
Remove `--authorized` to allow only Creative Commons web sources. Get help with `.venv/bin/python -m engine.cli import --help`.

## Look options (project.json, all optional)
    "background": {"mode": "cover"}    # default: each track's own cover, enlarged + blurred, slowly drifting;
                                       #   the next background fades in ~1.2s BEFORE its cover (tune: "bg_lead")
                                       #   "darken": 0.3 (0 = bright and pastel, 0.5 = moody)
    "background": {"mode": "marble", "palette": "wine"}   # dark generated swirl, same for the whole video
    "transition": "cut"                # default hard cut between covers; "fade" + "fade": 0.6 for a cross-fade
    "stars": 3                         # glitter star stickers on the vinyl (0 = none)
    "fps": 30                          # 60 is smoother but renders about twice as slow

## Project layout
    engine/
      cli.py        commands: resolve | folder | import | download | build
      sources/      where tracks come from: metadata.py, spotify.py, ytdlp.py (rights check), library.py
      media/        audio files: audio.py (FFmpeg), tags.py (Mutagen), trim.py (auto-trim start/end)
      playlist/     project.json: importer.py (unified importer), folder.py
      look/         visuals: coverbg.py (default), background.py (marble), vinyl.py
      video/        render.py (FFmpeg graph), timestamps.py
      publish/      text.py (tags, description), thumb.py
      titles/       research.py, generate.py, score.py, llm.py (Groq), history.py, pipeline.py
    tests/          mirrors engine/ (tests/sources, tests/media, ...)
Each folder's `__init__.py` lists what its files do.

## Titles (research + rank, for you to review)
    .venv/bin/python -m engine.cli titles work/projects/<name>/project.json --mood "sad, late night" -n 10
    .venv/bin/python -m engine.cli titles work/projects/<name>/project.json --pick 3     # save option 3 as youtube_title
How it works: searches YouTube (yt-dlp, no key) for what performs + reads search-bar suggestions, then builds candidates from
data-filled templates (always) plus Groq LLM titles if a key is set. Put it in `senora/.env` (copy `.env.example`):
`GROQ_API_KEY=your_key` (optional `GROQ_MODEL=...`), or `export GROQ_API_KEY=...` in the terminal.
Every candidate is scored 0-100 with reasons (relevance 40, length 20, keyword up front 15, search demand 15, style 10).
- **Relevance is a gate**: titles must match the theme or the real artists/songs. Artists, languages and genres found in
  research (e.g. "Drake", "Hindi", "R&B") are never borrowed, and if you pass `--mood` only your mood words are used.
- **No repeats**: offered titles are remembered in `work/projects/titles_history.json`; later playlists avoid similar ones
  (`--no-history` to turn off). Options are also kept varied (max 2 per opening).
- Output: `titles.md` (review list) and `titles.json` next to the project. `--offline` skips research, `--no-llm` skips Groq.
- `build` now also writes 5 offline, varied titles into `<name>.titles.txt` instead of 5 fixed ones.
No tool can promise a hit; this gives relevant, data-informed options and shows why each ranks where it does.

## Web UI (wizard)
    pip install -r requirements.txt
    python -m uvicorn server.app:app --port 8000        # then open http://localhost:8000
Steps (each has a Back button, and everything autosaves per playlist):
1. **Links**: one row per link, + / - to add/remove, drag to reorder. 2. **Extract**: downloads audio and takes each
song's own thumbnail as its picture (needs the "I have permission" checkbox); shows a rough time estimate.
3. **Tracks & clean-up**: replace a picture (upload or another link's thumbnail), cut the start/end of a song, undo the cut.
4. **Build & download**: timestamps, estimated render time, then video -> thumbnail -> title -> description; download the files.
Media is stored in `work/ui/` (change with `SENORA_DATA`), never in git. YouTube upload is not built yet.

## Where files go (one folder per playlist)
    work/projects/<name>/   project.json, downloaded audio, covers, sources.txt   (use --workdir/--audio-dir/--project here)
    work/references/        videos you downloaded only to study (never used in builds)
    out/<name>/             <name>.mp4 + .description.txt + .titles.txt + .thumbnail.jpg   (build -o out/<name>/<name>.mp4)
    out/early-tests/        first test renders
Example:
    .venv/bin/python -m engine.cli import --file work/projects/late-night/sources.txt --title "Late Night" --authorized \
        --audio-dir work/projects/late-night/audio --workdir work/projects/late-night --project work/projects/late-night/project.json
    .venv/bin/python -m engine.cli build work/projects/late-night/project.json -o out/late-night/late-night.mp4 --preview

## Notes
- Audio is used exactly as supplied (effects are on the roadmap, see ROADMAP.md).
- Final quality: libx264 CRF 16, preset slow, AAC 256k. Preview uses VideoToolbox.
- Tests: `.venv/bin/python -m pytest -q`

## Import tracks (yt-dlp + FFmpeg + Mutagen + Spotify metadata)
One command adds tracks to the playlist (`project.json`) from any source:

    .venv/bin/python -m engine.cli import song.wav "https://youtu.be/<cc-video>" --authorized --project work/project.json
    .venv/bin/python -m engine.cli import --file sources.txt --format m4a --normalize
    # sources.txt line pairing Spotify metadata with audio you own:
    #   https://open.spotify.com/track/<id> | my_audio/Artist - Song.flac

- **Local file/folder**: converted with FFmpeg (`--format mp3|m4a|flac|wav`, optional `--normalize` = -14 LUFS), tagged with Mutagen, cover art taken from the file or looked up.
- **YouTube / web URL**: metadata via yt-dlp, audio downloaded then processed the same way.
- **Spotify link** (track/album/playlist): metadata + cover via the Web API (set `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`). Spotify audio is never downloaded; audio comes from `--library <folder>` (matched by name) or the `| audio` pairing, else the track is flagged `AUDIO MISSING`.
- **Rights gate**: web downloads are allowed only for Creative Commons-licensed sources or with `--authorized` (you own it / are licensed). Local files also need `--authorized`. The basis is saved on each track as `rights` and in the file's comment tag.
- `download` (bulk raw download) uses the same gate.
- **Trimming is never automatic** (some songs have spoken parts that belong to them). Audio stays exactly as downloaded unless you ask:
  `import ... --trim` auto-trims silence/extras at the start/end while importing, or on an existing project:
  `.venv/bin/python -m engine.cli trim work/projects/<name>/project.json` (suggestions only, changes nothing),
  `... trim <project> --apply` (apply suggestions), `... trim <project> --track 2 --end 187.7` (cut by hand),
  `... trim <project> --track 2 --restore` (undo). Originals are always kept. Detection is by loudness only (no speech
  recognition), never cuts >25% of a track or the middle of a song, and marks risky cuts REVIEW.

