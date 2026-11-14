import argparse
import json
import os
import sys

from . import publish
from .media import audio
from .playlist import importer
from .sources import library, metadata, ytdlp
from .titles import suggest as suggest_titles
from .video import render


THUMB_TEXT = "PlayList"


def cmd_resolve(a):
    lines = [l.strip() for l in open(a.links) if l.strip() and not l.startswith("#")]
    os.makedirs(a.workdir, exist_ok=True)
    tracks = []
    for i, line in enumerate(lines, 1):
        m = metadata.resolve(line)
        cover = None
        if m["cover_url"]:
            cover = metadata.download_cover(m["cover_url"], os.path.join(a.workdir, f"cover{i:02d}.jpg"))
        audio = None
        if a.audio_dir:  # try what the user typed first, then the looked-up names
            audio = (library.find_audio(a.audio_dir, m["query"])
                     or library.find_audio(a.audio_dir, m["title"], m["artist"]))
        flag = "" if (not m["needs_review"] and audio and cover) else "  <-- REVIEW"
        print(f"{i:>2}. {m['title']} - {m['artist'] or '?'} | cover:{'ok' if cover else 'MISSING'} | "
              f"audio:{os.path.basename(audio) if audio else 'MISSING'}{flag}")
        tracks.append({**{k: m[k] for k in ("title", "artist", "album", "duration")},
                       "cover": cover, "audio": audio, "source_link": line if metadata.is_url(line) else ""})
    json.dump({"title": a.title, "theme": a.theme or a.title, "tracks": tracks},
              open(a.out, "w"), indent=1)
    print(f"\nWrote {a.out}. Fix any REVIEW rows (edit the json), then run: build {a.out}")


def cmd_build(a):
    """One command, in order: video -> thumbnail -> title -> description. Each step's output feeds the next."""
    project = json.load(open(a.project))
    missing = [t["title"] for t in project["tracks"] if not t.get("audio") or not t.get("cover")]
    if missing:
        sys.exit("Missing audio or cover for: " + ", ".join(missing))
    stem = os.path.splitext(a.out)[0]
    base = os.path.dirname(os.path.abspath(a.project))
    theme = project.get("theme", project.get("title", "Playlist"))

    # 1. VIDEO (volume evened out between songs only if you switched that on after listening to the difference)
    print("[1/4] video ...", flush=True)
    render_project = project
    if project.get("level_audio"):
        from .media import level
        outdir = os.path.join(base, "work", "leveled")
        tracks = []
        for t in project["tracks"]:
            lufs = t.get("lufs") if t.get("lufs") is not None else level.measure(t["audio"])
            g = level.gain_for(lufs)
            dst = os.path.join(outdir, f"{os.path.splitext(os.path.basename(t['audio']))[0]}.{g:+.1f}dB.mp3")
            if abs(g) >= 0.3 and not os.path.exists(dst):
                level.apply(t["audio"], dst, g)
            tracks.append({**t, "audio": dst if abs(g) >= 0.3 else t["audio"]})
            print(f"      volume: {t['title'][:32]}  {lufs} LUFS -> {g:+.1f} dB")
        render_project = {**project, "tracks": tracks}
    res = render.render(render_project, a.out, preview=a.preview)
    print(f"      {a.out} ({res['duration']:.1f}s)")

    # 2. THUMBNAIL (uses the short thumbnail text, which doesn't depend on the title)
    print("[2/4] thumbnail ...", flush=True)
    thumb_text = project.get("thumb_title") or THUMB_TEXT          # always "PlayList", never the playlist's own name
    publish.thumbnail(res["bg"], stem + ".thumbnail.jpg", thumb_text,
                      [t["cover"] for t in project["tracks"]], at=res.get("thumb_at", 5.0))
    print(f"      {stem}.thumbnail.jpg  (text: {thumb_text!r})")
    picked = project.get("thumbs_selected") or []
    if picked:        # the thumbnails you chose in the gallery: A, B, C for YouTube's thumbnail test; A also becomes the main file
        from .publish import thumbs
        prof = project.get("profile") or {}
        tctx = {"moods": [m.strip() for m in (project.get("mood") or "").split(",") if m.strip()] or prof.get("moods", []),
                "title": project.get("youtube_title") or (project.get("desc_meta") or {}).get("title", ""),
                "minutes": res["duration"] / 60}
        covers = [t["cover"] for t in project["tracks"]]
        for letter, sel in zip("ABC", picked[:3]):
            path = f"{stem}.thumbnail-{letter}.jpg"
            thumbs.save_jpeg(thumbs.render(sel["family"], sel["variant"], covers, tctx), path)
            if letter == "A":
                thumbs.save_jpeg(thumbs.render(sel["family"], sel["variant"], covers, tctx), stem + ".thumbnail.jpg")
            print(f"      {path}  ({sel['family']}/{sel['variant']})")

    # 3. TITLE (research + rank; the chosen title is saved and used by the description)
    print("[3/4] title ...", flush=True)
    hist = os.path.join(os.path.dirname(base), "titles_history.json")
    if project.get("youtube_title"):
        chosen, why = project["youtube_title"], "set in project.json"
    else:
        found = suggest_titles(project, n=10, mood=project.get("mood", ""), online=not a.offline, use_llm=not a.no_llm,
                               history_path=hist, project_name=os.path.basename(base))
        opts = found["titles"]
        chosen = opts[0]["title"] if opts else publish.title_ideas(theme)[0]
        why = f"top score {opts[0]['score']}/100 [{opts[0]['source']}]" if opts else "fallback template"
        open(os.path.join(base, "titles.md"), "w").write(
            "\n".join(f"{i}. {c['title']}  ({c['score']}/100, {c['source']})" for i, c in enumerate(opts, 1)) + "\n")
        json.dump(found, open(os.path.join(base, "titles.json"), "w"), indent=1, ensure_ascii=False)
        for w in found["warnings"]:
            print(f"      NOTE: {w}")
    print(f"      chosen: {chosen}  ({why})")

    # 4. DESCRIPTION (uses the final title)
    print("[4/4] description ...", flush=True)
    desc = project.get("description_override") or publish.description_text(project, chosen, res["timestamps"], theme,
                                                                           use_llm=not a.no_llm)   # a hand-edited text wins
    open(stem + ".description.txt", "w").write(desc)
    open(stem + ".titles.txt", "w").write(chosen + "\n")
    print(f"      {stem}.description.txt, {stem}.titles.txt")
    print("\nSOURCES (audio / image, per track)")
    for n, t in enumerate(project["tracks"], 1):
        print(f"  {n}. {t['title']}\n     audio: {t.get('audio_source', '?')}\n     image: {t.get('image_source', '?')}")
    print("\nTIMESTAMPS\n" + res["timestamps"])
    print(f"\nDone: {a.out}")


def cmd_folder(a):
    from .playlist import folder
    project = folder.build_project(a.folder, a.title, a.workdir, a.order, lookup=not a.offline)
    json.dump(project, open(a.out, "w"), indent=1)
    for i, t in enumerate(project["tracks"], 1):
        print(f"{i:>2}. {t['title']} - {t['artist'] or '?'}")
    print(f"\nWrote {a.out}. Next: build {a.out}")


def cmd_download(a):
    urls = list(a.urls)
    if a.file:
        urls += [l.strip() for l in open(a.file) if l.strip() and not l.startswith("#")]
    if not urls:
        sys.exit("Give at least one URL or --file")
    sys.exit(ytdlp.download(urls, a.out_dir, video=a.video, audio_format=a.format,
                               playlist=a.playlist, attested=a.authorized))


def cmd_import(a):
    sources = list(a.sources)
    if a.file:
        sources += [l.strip() for l in open(a.file) if l.strip() and not l.startswith("#")]
    if not sources:
        sys.exit("Give at least one source or --file")
    tracks, failed = [], 0
    existing = len(json.load(open(a.project))["tracks"]) if os.path.exists(a.project) else 0
    for s in sources:  # 'metadata source | authorized audio file or url' pairs the two
        parts = [p.strip() for p in s.split("|")]          # source | audio-or-url | cover-image (both optional)
        src, aud, cov = (parts + ["", ""])[:3]
        try:
            got = importer.import_one(src, a.audio_dir, a.workdir, existing + len(tracks) + 1, a.format, a.normalize,
                                      a.authorized, not a.offline, aud or None, a.library, trim=a.trim, cover=cov or None)
        except (ytdlp.NotAuthorized, RuntimeError, ValueError) as e:
            print(f"SKIPPED {src}: {e}", file=sys.stderr)
            failed += 1
            continue
        for t in got:
            print(f"+ {t['title']} - {t['artist'] or '?'} | "
                  + (f"{t['duration']:.0f}s -> {os.path.basename(t['audio'])}" if t["audio"] else "AUDIO MISSING  <-- REVIEW"))
            for why in (t.get("trim") or {}).get("reasons", []):
                print(f"    trimmed: {why}")
        tracks += got
    importer.add_to_project(a.project, tracks, title=a.title)
    print(f"\nAdded {len(tracks)} track(s) to {a.project}. Next: build {a.project}")
    if failed:
        sys.exit(1)


def cmd_titles(a):
    project = json.load(open(a.project))
    base = os.path.dirname(os.path.abspath(a.project))
    hist = None if a.no_history else (a.history or os.path.join(os.path.dirname(base), "titles_history.json"))
    if a.pick:
        review = json.load(open(os.path.join(base, "titles.json")))
        if not 1 <= a.pick <= len(review["titles"]):
            sys.exit(f"--pick must be 1..{len(review['titles'])}")
        project["youtube_title"] = review["titles"][a.pick - 1]["title"]
        json.dump(project, open(a.project, "w"), indent=1)
        print("Chosen:", project["youtube_title"])
        return
    res = suggest_titles(project, n=a.n, query=a.query, mood=a.mood or "", use_llm=not a.no_llm,
                                online=not a.offline, history_path=hist, project_name=os.path.basename(base))
    json.dump(res, open(os.path.join(base, "titles.json"), "w"), indent=1, ensure_ascii=False)
    lines = [f"# Title options for: {a.query or project.get('theme') or project.get('title')}", ""]
    r = res["research"]
    if r.get("videos"):
        p = r["patterns"]
        lines += [f"Researched {len(r['videos'])} top YouTube results. Winners' median title length {p['median_len']} chars; "
                  f"{p['pct_pipe']}% use '|', {p['pct_brackets']}% use brackets, {p['pct_emoji']}% use an emoji.",
                  "Top search phrases: " + "; ".join(r["suggestions"][:6]), ""]
    for w in res["warnings"]:
        lines.append(f"NOTE: {w}")
    lines.append("")
    for i, c in enumerate(res["titles"], 1):
        lines += [f"{i}. {c['title']}", f"   score {c['score']}/100 [{c['source']}] - " + "; ".join(c["reasons"]), ""]
    lines.append("Pick one:  titles <project.json> --pick N")
    text = "\n".join(lines)
    open(os.path.join(base, "titles.md"), "w").write(text)
    print(text)
    print(f"\nSaved {os.path.join(base, 'titles.md')}")


def cmd_thumb(a):
    """Save a video's thumbnail (metadata only, no video download). Square by default."""
    import subprocess
    from .playlist import importer as _imp
    from .sources import metadata as _md
    j = json.loads(subprocess.run(ytdlp._ytdlp() + ["-J", "--no-playlist", "--no-warnings", a.url],
                                  capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout or "{}")
    if not j.get("thumbnail"):
        sys.exit("No thumbnail found for that link")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    raw = a.out + ".raw.jpg"
    _md.download_cover(j["thumbnail"], raw)
    if a.square:
        _imp._square_png(raw, a.out)
    else:
        os.replace(raw, a.out)
    if a.square and os.path.exists(raw):
        os.remove(raw)
    print(f"{j.get('title', '')}\nSaved {a.out}")


def cmd_trim(a):
    """Never changes anything unless asked: no flags = suggestions only; --apply or --start/--end = cut; --restore = undo."""
    from .media import audio as _audio, tags as _tags, trim as _trim
    project = json.load(open(a.project))
    tracks = list(enumerate(project["tracks"], 1))
    if a.track:
        tracks = [x for x in tracks if x[0] == a.track]
        if not tracks:
            sys.exit(f"--track must be 1..{len(project['tracks'])}")
    manual = a.start is not None or a.end is not None
    if manual and not a.track:
        sys.exit("--start/--end need --track N")
    changed = 0
    for n, t in tracks:
        src = t.get("audio_original") or t["audio"]
        if a.restore:
            if t.get("audio_original"):
                t["audio"] = t.pop("audio_original"); t.pop("trim", None)
                t["duration"] = _audio.probe(t["audio"])["duration"]
                print(f"{n}. {t['title']}: restored original"); changed += 1
            continue
        full = _audio.probe(src)["duration"]
        if manual:
            r = {"start": a.start or 0.0, "end": a.end or full, "reasons": [f"manual cut {a.start or 0:.1f}-{a.end or full:.1f}s"]}
        else:
            r = _trim.detect(src, full)
        cut = bool(r["reasons"]) and (r["start"] > 0 or r["end"] < full)
        print(f"{n}. {t['title'][:34]:34} {full:6.1f}s  " + (f"-> keep {r['start']:.1f}-{r['end']:.1f}s | " + "; ".join(r["reasons"]) if cut else "no change"))
        if cut and (a.apply or manual):
            out = os.path.splitext(src)[0] + " (trimmed).mp3"
            _audio.process(src, os.path.dirname(out), name=os.path.basename(out)[:-4], fmt="mp3", start=r["start"], end=r["end"])
            _tags.write(out, title=t["title"], artist=t["artist"], album=t.get("album", ""), cover=t.get("cover"), comment="Trimmed by Senora")
            t["audio_original"], t["audio"] = src, out
            t["duration"] = _audio.probe(out)["duration"]
            t["trim"] = {**r, "original": src}
            changed += 1
    if changed:
        json.dump(project, open(a.project, "w"), indent=1)
        print(f"\nChanged {changed} track(s). Originals are kept (undo: trim <project> --track N --restore).")
    elif not (a.apply or manual or a.restore):
        print("\nSuggestions only - nothing changed. Apply with --apply, or cut by hand: --track N --start S --end E.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="senora")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve", help="links/names -> project.json with covers + matched audio")
    r.add_argument("links", help="text file: one song link or 'Artist - Title' per line, in order")
    r.add_argument("--audio-dir", help="folder with your audio files")
    r.add_argument("--title", required=True)
    r.add_argument("--theme")
    r.add_argument("--workdir", default="work")
    r.add_argument("-o", "--out", default="project.json")
    r.set_defaults(fn=cmd_resolve)
    f = sub.add_parser("folder", help="folder of audio files -> project.json (tags, covers, order)")
    f.add_argument("folder")
    f.add_argument("--title", required=True)
    f.add_argument("--order", help="optional text file: filenames in play order (default: sorted by name)")
    f.add_argument("--offline", action="store_true", help="no cover lookup online")
    f.add_argument("--workdir", default="work")
    f.add_argument("-o", "--out", default="project.json")
    f.set_defaults(fn=cmd_folder)
    b = sub.add_parser("build", help="render video + publishing assets")
    b.add_argument("project")
    b.add_argument("-o", "--out", default="out/video.mp4")
    b.add_argument("--preview", action="store_true")
    b.add_argument("--offline", action="store_true", help="title step without YouTube research")
    b.add_argument("--no-llm", action="store_true", help="title step without Groq")
    b.set_defaults(fn=cmd_build)
    d = sub.add_parser("download", help="download audio/video from a URL with yt-dlp")
    d.add_argument("urls", nargs="*")
    d.add_argument("--file", help="text file with one URL per line")
    d.add_argument("--out-dir", default="my_audio")
    d.add_argument("--video", action="store_true", help="download video (mp4) instead of audio")
    d.add_argument("--format", default="mp3", help="audio format (mp3, m4a, wav, flac...)")
    d.add_argument("--playlist", action="store_true", help="download whole playlist if URL is one")
    d.set_defaults(fn=cmd_download)
    d.add_argument("--authorized", action="store_true",
                   help="I own this or am licensed to use it (otherwise only Creative Commons sources)")
    i = sub.add_parser("import", help="add tracks (file/folder/YouTube/Spotify/text) to a project.json")
    i.add_argument("sources", nargs="*", help="local file/folder, URL, Spotify link, or 'Artist - Title'. "
                   "Pipes: 'source | audio-or-url | cover-image'. Web links use their own thumbnail as cover by default.")
    i.add_argument("--file", help="text file with one source per line")
    i.add_argument("--project", default="work/project.json")
    i.add_argument("--title", help="playlist title if the project is created")
    i.add_argument("--audio-dir", default="my_audio", help="where processed audio is written")
    i.add_argument("--library", help="folder searched for audio matching Spotify/text sources")
    i.add_argument("--workdir", default="work")
    i.add_argument("--format", default="mp3", choices=sorted(audio.FORMATS))
    i.add_argument("--normalize", action="store_true", help="EBU R128 loudness normalisation (-14 LUFS)")
    i.add_argument("--offline", action="store_true", help="skip online cover lookup")
    i.add_argument("--trim", action="store_true", help="auto-trim silence / extras at start+end (OFF by default: audio stays exactly as downloaded)")
    i.add_argument("--authorized", action="store_true",
                   help="I own this or am licensed to use it (otherwise only Creative Commons sources)")
    i.set_defaults(fn=cmd_import)
    th = sub.add_parser("thumb", help="save a YouTube link's thumbnail image (square by default)")
    th.add_argument("url")
    th.add_argument("-o", "--out", required=True, help="output image path, e.g. work/projects/x/art/song.png")
    th.add_argument("--wide", dest="square", action="store_false", help="keep the original 16:9 frame")
    th.set_defaults(fn=cmd_thumb)
    tr = sub.add_parser("trim", help="suggest / apply / undo cuts at the start+end of tracks (never automatic)")
    tr.add_argument("project")
    tr.add_argument("--track", type=int, help="only this track number (1-based)")
    tr.add_argument("--start", type=float, help="manual cut: keep from this second (needs --track)")
    tr.add_argument("--end", type=float, help="manual cut: keep until this second (needs --track)")
    tr.add_argument("--apply", action="store_true", help="apply the suggested cuts (default: suggestions only)")
    tr.add_argument("--restore", action="store_true", help="undo trimming: go back to the original audio")
    tr.set_defaults(fn=cmd_trim)
    t = sub.add_parser("titles", help="research + generate + rank YouTube titles for review (Groq optional)")
    t.add_argument("project")
    t.add_argument("--query", help="search phrase to research (default: the playlist theme)")
    t.add_argument("--mood", help="e.g. 'sad, late night'")
    t.add_argument("-n", type=int, default=10, help="how many options")
    t.add_argument("--no-llm", action="store_true", help="templates only, even if GROQ_API_KEY is set")
    t.add_argument("--offline", action="store_true", help="skip YouTube research")
    t.add_argument("--history", help="file remembering offered titles (default: work/projects/titles_history.json)")
    t.add_argument("--no-history", action="store_true")
    t.add_argument("--pick", type=int, help="choose option N from the last run and save it as youtube_title")
    t.set_defaults(fn=cmd_titles)
    c = sub.add_parser("cloud-build", help="headless: a job file (links + settings) -> finished video, thumbnails, title, description")
    c.add_argument("job")
    c.add_argument("--out", default="out")
    c.add_argument("--work")
    c.set_defaults(fn=lambda a: __import__("engine.cloud", fromlist=["main"]).main([a.job, "--out", a.out] + (["--work", a.work] if a.work else [])))
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
