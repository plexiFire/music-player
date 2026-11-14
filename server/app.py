"""Senora UI server. Runs the engine as background jobs; media lives in DATA_DIR (never in git).

Run:  python -m uvicorn server.app:app --port 8000   (from the repo root)
Later the same server can run on a cloud machine; the browser only talks to this API.
"""
import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, UploadFile, File  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from engine import cli, publish  # noqa: E402
from engine.titles import suggest as suggest_titles  # noqa: E402
from engine.video import timestamps as _stamps  # noqa: E402
from engine.media import audio, level as _level, trim as autotrim, voice as _voice  # noqa: E402
from engine.look import vinyl  # noqa: E402
from engine.publish import thumbs as _thumbs  # noqa: E402
from engine.titles import profile as _profile  # noqa: E402
from engine.sources import metadata as _metadata, musicbrainz as _mb  # noqa: E402
from server.library import Library  # noqa: E402
from engine.playlist import importer  # noqa: E402
from engine.sources import ytdlp  # noqa: E402

DATA = Path(os.environ.get("SENORA_DATA", ROOT / "work" / "ui"))
DATA.mkdir(parents=True, exist_ok=True)
JOBS: dict = {}
LOCK = threading.Lock()
RENDER_FACTOR = 1.7   # measured on this Mac: 1080p render took ~1.7x the video length
EXTRACT_MIN_PER_LINK = 0.5  # rough: download + convert per link

app = FastAPI(title="Senora")
STATIC = Path(__file__).parent / "static"


# ---------- storage helpers ----------
def pdir(pid):
    if not re.fullmatch(r"[a-f0-9]{8}", pid or ""):
        raise HTTPException(404, "no such project")
    d = DATA / pid
    if not d.exists():
        raise HTTPException(404, "no such project")
    return d


def load(pid):
    return json.loads((pdir(pid) / "project.json").read_text())


_SAVE_LOCK = threading.Lock()


def save(pid, p):
    """Write to a temp file, then swap it in: a reader never sees half-written JSON."""
    target = pdir(pid) / "project.json"
    tmp = target.with_suffix(".json.tmp")
    with _SAVE_LOCK:
        tmp.write_text(json.dumps(p, indent=1, ensure_ascii=False))
        os.replace(tmp, target)


def new_job(kind, pid):
    jid = uuid.uuid4().hex[:8]
    with LOCK:
        JOBS[jid] = {"id": jid, "kind": kind, "project": pid, "state": "running", "message": "starting",
                     "started": time.time(), "log": ""}
    return jid


def set_job(jid, **kw):
    with LOCK:
        JOBS[jid].update(kw)


def run_bg(jid, fn, *args):
    def wrap():
        try:
            fn(jid, *args)
            set_job(jid, state="done", message="done")
        except Exception as e:  # shown in the UI, never crashes the server
            set_job(jid, state="failed", message=str(e))
    threading.Thread(target=wrap, daemon=True).start()


# ---------- channel defaults: remembered for every new playlist ----------
DEFAULT_KEYS = ("channel", "contact_email", "disc", "bg_mode", "bg_color")
DEFAULTS_FILE = DATA / "_defaults.json"


def load_defaults():
    try:
        d = json.loads(DEFAULTS_FILE.read_text())
    except (OSError, ValueError):
        d = {}
    return {k: d.get(k, [] if k == "hashtags" else "") for k in DEFAULT_KEYS}


def save_defaults(d):
    tmp = DEFAULTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: d.get(k) for k in DEFAULT_KEYS}, indent=1, ensure_ascii=False))
    os.replace(tmp, DEFAULTS_FILE)


# ---------- models ----------
class NewProject(BaseModel):
    name: str


class Links(BaseModel):
    links: list[str]


class Extract(BaseModel):
    rights_confirmed: bool


class CoverLink(BaseModel):
    url: str


class Trim(BaseModel):
    start: float = 0.0
    end: float | None = None


class Settings(BaseModel):
    mood: str = ""
    channel: str = ""
    contact_email: str = ""
    hashtags: list[str] = []
    youtube_title: str = ""
    disc: str = "vinyl"
    bg_mode: str = "cover"       # "cover" = follows each song's cover (default) | "solid" = one dark colour | "sky" = twinkling stars
    bg_color: str = "blue"


class DescriptionEdit(BaseModel):
    text: str = ""          # empty = go back to the automatic description


class PreviewReq(BaseModel):
    online: bool = False
    use_llm: bool = False
    exclude: list[str] = []      # titles already shown: Refresh offers different ones


class BuildReq(BaseModel):
    preview: bool = False
    offline: bool = False
    no_llm: bool = False


# ---------- projects ----------
def _new_project(name, links=()):
    pid = uuid.uuid4().hex[:8]
    d = DATA / pid
    (d / "audio").mkdir(parents=True)
    (d / "work").mkdir()
    (d / "out").mkdir()
    name = name.strip() or "Playlist"
    dflt = load_defaults()
    save(pid, {"id": pid, "name": name, "title": name, "theme": name, "created": time.time(), "links": list(links), "tracks": [],
               "rights_confirmed": False, "mood": "", "channel": dflt["channel"], "contact_email": dflt["contact_email"],
               "hashtags": [], "disc": dflt["disc"] or "vinyl", "youtube_title": "",
               "bg_mode": dflt.get("bg_mode") or "cover", "bg_color": dflt.get("bg_color") or "blue",
               "watermark": True, "background": _bg(dflt.get("bg_mode") or "cover", dflt.get("bg_color") or "blue")})
    return pid


@app.post("/api/projects")
def create(req: NewProject):
    return {"id": _new_project(req.name)}


@app.get("/api/projects")
def list_projects():
    out = []
    for d in DATA.iterdir():
        f = d / "project.json"
        if f.exists():
            try:
                p = json.loads(f.read_text())
            except ValueError:
                continue
            out.append({"id": p["id"], "name": p["name"], "tracks": len(p["tracks"]), "links": len(p["links"]),
                        "created": p.get("created") or f.stat().st_mtime})
    return sorted(out, key=lambda x: -x["created"])            # newest first


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    """Remove a playlist and everything stored for it (audio, pictures, built videos)."""
    d = pdir(pid)
    with LOCK:
        busy = [j for j in JOBS.values() if j["project"] == pid and j["state"] == "running"]
    if busy:
        raise HTTPException(409, "a job is still running for this playlist; wait for it to finish")
    shutil.rmtree(d)
    return {"deleted": pid}


def with_estimate(p):
    """Every project response carries the same estimate block, so the page never has to guess."""
    total = sum(float(t.get("duration") or 0) for t in p["tracks"])
    p["estimate"] = {
        "extract_minutes": round(len(p["links"]) * EXTRACT_MIN_PER_LINK, 1),
        "render_minutes": round(total / 60 * RENDER_FACTOR, 1),
        "video_minutes": round(total / 60, 1),
        "note": "rough estimates; the render time is measured on this Mac",
    }
    return p


def _bg(mode, color):
    return {"mode": mode, "color": color} if mode in ("solid", "sky") else {"mode": "cover"}


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return with_estimate(load(pid))


@app.put("/api/projects/{pid}/links")
def set_links(pid: str, req: Links):
    p = load(pid)
    p["links"] = [l.strip() for l in req.links if l.strip()]   # order = play order
    p["tracks"] = []                                           # links changed: extract again
    p.pop("description_override", None)
    save(pid, p)
    return with_estimate(p)


@app.put("/api/projects/{pid}/settings")
def set_settings(pid: str, req: Settings):
    p = load(pid)
    p["mood"] = req.mood.strip()
    p["channel"] = req.channel.strip()
    p["contact_email"] = req.contact_email.strip()
    p["hashtags"] = [h.strip().lstrip("#").replace(" ", "") for h in req.hashtags if h.strip()]
    new_title = req.youtube_title.strip()
    meta = p.get("desc_meta") or {}
    old_title = meta.get("title") or p.get("youtube_title") or ""
    if p.get("description_override") and new_title and old_title and new_title != old_title:
        # you picked another title: change only the title-based parts, keep every edit you made
        p["description_override"] = publish.compose.retitle(p["description_override"], old_title, new_title, meta.get("hook", ""))
        p["desc_meta"] = {"title": new_title, "hook": publish.compose.hook_for({}, new_title)}
    p["youtube_title"] = new_title
    if req.disc not in vinyl.STYLES:
        raise HTTPException(400, f"unknown disc style; choose one of {', '.join(vinyl.STYLES)}")
    p["disc"] = req.disc
    if req.bg_mode not in ("cover", "solid", "sky"):
        raise HTTPException(400, "background must be 'cover', 'solid' or 'sky'")
    p["bg_mode"], p["bg_color"], p["watermark"] = req.bg_mode, req.bg_color, True     # the channel-name mark is mandatory
    p["background"] = _bg(req.bg_mode, req.bg_color)
    save(pid, p)
    d = load_defaults()                       # remember non-empty channel settings for the next playlists
    for k in DEFAULT_KEYS:
        if p.get(k):
            d[k] = p[k]
    save_defaults(d)
    return with_estimate(p)


@app.put("/api/projects/{pid}/description")
def set_description(pid: str, req: DescriptionEdit):
    """The description you edited by hand. Used as-is by the build until you reset it."""
    p = load(pid)
    if req.text.strip():
        p["description_override"] = req.text.replace("\r\n", "\n").rstrip() + "\n"
    else:
        p.pop("description_override", None)
    save(pid, p)
    return {"edited": bool(req.text.strip())}


@app.get("/api/defaults")
def get_defaults():
    return load_defaults()


@app.post("/api/projects/{pid}/preview")
def preview(pid: str, req: PreviewReq):
    """Title options + description + tags as they would be written by a build, without building anything."""
    p = load(pid)
    if not p["tracks"] or any(not t.get("audio") for t in p["tracks"]):
        raise HTTPException(400, "extract every song first")
    if not p.get("profile"):                      # playlists extracted before this feature existed
        p["profile"] = _profile.build(p["tracks"], online=False, use_llm=False)
        save(pid, p)
    if req.online and p.get("profile"):           # "Refresh with YouTube research": look at today's top videos again
        p["profile"]["tag_pool"] = _profile.tag_pool(p["profile"])
        save(pid, p)
    proj = {**p, "title": p.get("title") or p["name"], "theme": p.get("theme") or p["name"]}
    theme = proj["theme"]
    durs = [float(t.get("duration") or 0) for t in p["tracks"]]
    _, ts = _stamps.build(p["tracks"], durs)
    found = suggest_titles(proj, n=8, mood=p.get("mood", ""), online=req.online, use_llm=req.use_llm,
                           history_path=str(DATA / "titles_history.json"), project_name=p["name"], record=False,
                           exclude=req.exclude)
    opts = found["titles"]
    chosen = p.get("youtube_title") or (opts[0]["title"] if opts else publish.title_ideas(theme)[0])
    desc = p.get("description_override") or publish.description_text(proj, chosen, ts, theme, use_llm=req.use_llm)
    auto = publish.description_text(proj, chosen, ts, theme, use_llm=req.use_llm) if p.get("description_override") else desc
    suggested_tags = re.findall(r"#(\w+)", auto.strip().splitlines()[-1])         # the automatic set: you can add any of them by click
    if not p.get("description_override"):          # remember what the title-based parts are, so a later title change can patch them
        p["desc_meta"] = {"title": chosen, "hook": publish.compose.hook_paragraph(desc)}
        save(pid, p)
    used_tags = re.findall(r"#(\w+)", desc.strip().splitlines()[-1])          # exactly the hashtags the description ends with
    return {"titles": [{"title": c["title"], "score": c["score"], "source": c["source"]} for c in opts],
            "chosen": chosen, "description": desc, "edited": bool(p.get("description_override")), "recycled": bool(found.get("recycled")),
            "suggested_hashtags": suggested_tags, "researched": len((p.get("profile") or {}).get("tag_pool") or []) if req.online else None,
            "warnings": found["warnings"] + ([p["profile"]["warning"]] if (p.get("profile") or {}).get("warning") else []),
            "profile": {**{k: (p.get("profile") or {}).get(k) for k in ("genres", "moods", "source")}, "hashtags": used_tags}}


@app.get("/api/disc-styles")
def disc_styles():
    return [{"id": k, "label": v} for k, v in vinyl.STYLES.items()]


@app.get("/api/disc-preview/{style}.png")
def disc_preview(style: str):
    """Small picture of a disc style for the style picker (generated once, then cached)."""
    if style not in vinyl.STYLES:
        raise HTTPException(404, "unknown disc style")
    d = DATA / "_previews"
    d.mkdir(exist_ok=True)
    f = d / f"{style}_v2.png"
    if not f.exists():
        art = None
        if style == "art":                  # a sample picture so the preview shows what the art label looks like
            from PIL import Image
            import numpy as np
            y, x = np.mgrid[0:200, 0:200].astype(np.float32)
            g = np.dstack([60 + 160 * x / 200, 90 + 90 * y / 200, 190 - 120 * x / 200]).clip(0, 255).astype(np.uint8)
            art = str(d / "_sample_art.png")
            Image.fromarray(g).save(art)
        vinyl.make_disc(str(f), 180, style, art=art, stars=3)
    return FileResponse(f, media_type="image/png")


@app.get("/api/bg-colors")
def bg_colors():
    from engine.look import background
    return {"solid": [{"id": k} for k in background.SOLID],
            "sky": [{"id": k, "label": v[0]} for k, v in background.SKY.items()]}


@app.get("/api/bg-preview/{name}.png")
def bg_preview(name: str):
    """Small sample of a background: 'blue' (constant colour) or 'sky-night' (twinkling stars)."""
    from engine.look import background
    sky = name.startswith("sky-")
    key = name[4:] if sky else name
    if key not in (background.SKY if sky else background.SOLID):
        raise HTTPException(404, "unknown background")
    d = DATA / "_previews"
    d.mkdir(exist_ok=True)
    f = d / f"bg_{name}_v2.png"
    if not f.exists():
        from PIL import Image
        if sky:
            Image.fromarray(background.sky_frame(320, 180, 0.3, key)).save(f)
        else:
            background.make_solid(str(f), (240, 135), key)
    return FileResponse(f, media_type="image/png")


# ---------- step 2: extract ----------
def _suggest_cut(t):
    """A cut SUGGESTION for one song (never applied by itself): extra audio after a fade, long silence, or spoken words.
    Spoken words are found from the sound (engine/media/voice.py) and always worded as 'looks like', never 'is'."""
    full = audio.probe(t["audio"])["duration"]
    found = autotrim.recommend(t["audio"], full)
    talk = _voice.find(t["audio"], full)
    start, end, reasons = (found["start"], found["end"], list(found["reasons"])) if found else (0.0, full, [])
    for v in talk:
        if v["where"] == "end":
            end = min(end, v["start"] - 0.5)
        else:
            start = max(start, v["end"] + 0.3)
        if v["reason"] not in reasons:
            reasons.append(v["reason"])
    t.pop("suggestion", None)
    if reasons and (start > 0.3 or end < full - 0.3):
        t["suggestion"] = {"start": round(start, 1), "end": round(end, 1), "reasons": reasons, "voice": bool(talk)}


@app.post("/api/projects/{pid}/scan-voice")
def scan_voice(pid: str):
    """Look again at every song for extra audio / spoken words (useful for playlists extracted earlier). Only suggests."""
    p = load(pid)
    n = 0
    for t in p["tracks"]:
        if t.get("audio") and not t.get("trim") and not t.get("suggestion_dismissed"):
            try:
                _suggest_cut(t)
                n += 1 if t.get("suggestion") else 0
            except Exception:
                pass
    save(pid, p)
    return {**with_estimate(p), "flagged": n}


def _extract(jid, pid):
    d = pdir(pid)
    p = load(pid)
    tracks = []
    n = len(p["links"])
    for i, link in enumerate(p["links"], 1):
        set_job(jid, message=f"track {i}/{n}")
        try:
            tracks += importer.import_one(link, str(d / "audio"), str(d / "work"), len(tracks) + 1,
                                          authorized=True, lookup=True)
        except Exception as e:
            tracks.append({"title": link, "artist": "", "audio": None, "cover": None, "error": str(e),
                           "source_link": link, "audio_source": f"link: {link}", "image_source": "none"})
    for i, t in enumerate(tracks, 1):          # cut SUGGESTIONS only: nothing is cut unless the user presses Apply
        if not t.get("audio"):
            continue
        set_job(jid, message=f"analysing audio {i}/{len(tracks)}")
        try:
            _suggest_cut(t)
        except Exception:
            pass
    p["tracks"] = tracks
    if tracks:
        set_job(jid, message="checking artist names")
        try:
            _mb.fix_artists([t for t in tracks if t.get("audio")])      # replaces an uploader label by the real artist
        except Exception:
            pass
    if tracks and all(t.get("audio") for t in tracks):
        set_job(jid, message="detecting genre and mood")
        try:
            p["profile"] = _profile.build(tracks, online=True, use_llm=True)
        except Exception as e:
            p["profile"] = {"genres": [], "moods": [], "mood": "", "query": "", "hashtags": [], "features": [],
                            "source": [], "warning": f"genre detection failed: {type(e).__name__}"}
    save(pid, p)


@app.post("/api/projects/{pid}/extract")
def extract(pid: str, req: Extract):
    p = load(pid)
    if not p["links"]:
        raise HTTPException(400, "add at least one link first")
    if not req.rights_confirmed:
        raise HTTPException(400, "confirm you own or are licensed to use these audio files")
    p["rights_confirmed"] = True
    p.pop("description_override", None)                        # new extraction: the old hand-edited text no longer fits
    save(pid, p)
    jid = new_job("extract", pid)
    run_bg(jid, _extract, pid)
    return {"job": jid}


# ---------- step 3: images and trim ----------
def _track(p, n):
    if not 1 <= n <= len(p["tracks"]):
        raise HTTPException(404, "no such track")
    return p["tracks"][n - 1]


@app.get("/api/projects/{pid}/tracks/{n}/cover")
def cover(pid: str, n: int):
    t = _track(load(pid), n)
    if not t.get("cover") or not os.path.exists(t["cover"]):
        raise HTTPException(404, "no image")
    return FileResponse(t["cover"])


@app.get("/api/projects/{pid}/tracks/{n}/audio")
def track_audio(pid: str, n: int):
    t = _track(load(pid), n)
    if not t.get("audio") or not os.path.exists(t["audio"]):
        raise HTTPException(404, "no audio")
    return FileResponse(t["audio"], media_type="audio/mpeg")   # supports Range, so seeking works


@app.get("/api/projects/{pid}/tracks/{n}/peaks")
def track_peaks(pid: str, n: int, points: int = 600):
    """Waveform for the page: `points` loudness peaks (0..1) across the track."""
    import subprocess

    import numpy as np
    t = _track(load(pid), n)
    if not t.get("audio") or not os.path.exists(t["audio"]):
        raise HTTPException(404, "no audio")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", t["audio"], "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, stdin=subprocess.DEVNULL).stdout
    a = np.abs(np.frombuffer(raw, dtype=np.int16).astype(np.float32)) / 32768.0
    points = max(50, min(2000, points))
    if a.size == 0:
        raise HTTPException(400, "could not read audio")
    bins = np.array_split(a, points)
    peaks = [float(b.max()) if b.size else 0.0 for b in bins]
    top = max(peaks) or 1.0
    return {"peaks": [round(x / top, 3) for x in peaks], "duration": a.size / 8000.0}


@app.post("/api/projects/{pid}/tracks/{n}/cover-upload")
async def cover_upload(pid: str, n: int, file: UploadFile = File(...)):
    p = load(pid)
    t = _track(p, n)
    d = pdir(pid) / "work" / "art"
    d.mkdir(parents=True, exist_ok=True)
    raw = d / f"upload{n:02d}_raw"
    raw.write_bytes(await file.read())
    out = importer._square_png(str(raw), str(d / f"track{n:02d}_upload.png"))
    t["cover"] = out
    t["image_source"] = f"upload: {file.filename}"
    save(pid, p)
    return t


@app.post("/api/projects/{pid}/tracks/{n}/cover-link")
def cover_link(pid: str, n: int, req: CoverLink):
    p = load(pid)
    t = _track(p, n)
    info = ytdlp.info(req.url)
    d = pdir(pid) / "work" / "art"
    d.mkdir(parents=True, exist_ok=True)
    t["cover"] = importer._square_png_from_url(info["cover_url"], str(d / f"track{n:02d}_link.png"))
    t["image_source"] = f"link thumbnail: {req.url}"
    save(pid, p)
    return t


@app.post("/api/projects/{pid}/tracks/{n}/trim")
def trim_track(pid: str, n: int, req: Trim):
    p = load(pid)
    t = _track(p, n)
    src = t.get("audio_original") or t["audio"]
    full = audio.probe(src)["duration"]
    start = max(0.0, req.start)
    end = min(full, req.end) if req.end else full
    if end - start < 5:
        raise HTTPException(400, "the kept part must be at least 5 seconds")
    d = pdir(pid) / "audio"
    out = audio.process(src, str(d), name=f"track{n:02d}_trimmed", fmt="mp3", start=start, end=end)
    t.setdefault("audio_original", src)
    t["audio"] = out
    t["duration"] = audio.probe(out)["duration"]
    t["trim"] = {"start": start, "end": end, "by": "manual"}
    save(pid, p)
    return t


@app.post("/api/projects/{pid}/tracks/{n}/dismiss")
def dismiss_suggestion(pid: str, n: int):
    """'Keep as is': hide the cut suggestion for this song."""
    p = load(pid)
    t = _track(p, n)
    t["suggestion_dismissed"] = True
    save(pid, p)
    return t


@app.post("/api/projects/{pid}/tracks/{n}/restore")
def restore_track(pid: str, n: int):
    p = load(pid)
    t = _track(p, n)
    if t.get("audio_original"):
        t["audio"] = t.pop("audio_original")
        t.pop("trim", None)
        t["duration"] = audio.probe(t["audio"])["duration"]
        save(pid, p)
    return t


# ---------- step 4: build ----------
class _Live:
    """stdout stand-in: keeps the log, and turns '[2/4] thumbnail ...' lines into a live job message."""
    def __init__(self, jid):
        self.jid, self.parts = jid, []

    def write(self, text):
        self.parts.append(text)
        m = re.search(r"\[(\d)/4\] (\w+)", text)
        if m:
            set_job(self.jid, message=f"stage {m.group(1)}/4: {m.group(2)}")
        return len(text)

    def flush(self):
        pass

    def getvalue(self):
        return "".join(self.parts)


def _build(jid, pid, req):
    import contextlib
    d = pdir(pid)
    p = load(pid)
    slug = re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-") or "playlist"
    out = d / "out" / f"{slug}.mp4"
    ns = argparse.Namespace(project=str(d / "project.json"), out=str(out), preview=req.preview,
                            offline=req.offline, no_llm=req.no_llm)
    set_job(jid, message="stage 1/4: video")
    buf = _Live(jid)
    with contextlib.redirect_stdout(buf):
        cli.cmd_build(ns)
    set_job(jid, log=buf.getvalue())


@app.post("/api/projects/{pid}/build")
def build(pid: str, req: BuildReq):
    p = load(pid)
    if not p["tracks"] or any(not t.get("audio") for t in p["tracks"]):
        raise HTTPException(400, "extract every track first")
    jid = new_job("build", pid)
    run_bg(jid, _build, pid, req)
    return {"job": jid}


@app.get("/api/projects/{pid}/text")
def text(pid: str):
    """The title, tags and description from the last build, ready to copy into YouTube."""
    d = pdir(pid) / "out"
    desc = next(iter(sorted(d.glob("*.description.txt"))), None)
    tit = next(iter(sorted(d.glob("*.titles.txt"))), None)
    if not desc or not tit:
        raise HTTPException(404, "build first")
    head, _, _old_tags = tit.read_text().partition("\n\nTAGS\n")        # older builds also wrote tags; they are ignored
    return {"title": head.strip(), "description": desc.read_text().strip()}


@app.get("/api/projects/{pid}/outputs")
def outputs(pid: str):
    d = pdir(pid) / "out"
    return sorted(f.name for f in d.iterdir() if f.is_file()) if d.exists() else []


VIEW_TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".png": "image/png", ".txt": "text/plain; charset=utf-8"}


@app.get("/api/projects/{pid}/view/{name}")
def view_output(pid: str, name: str):
    """Open a built file in the browser (play the video, show the thumbnail, read the text) instead of downloading it."""
    f = pdir(pid) / "out" / Path(name).name
    if not f.exists():
        raise HTTPException(404, "not found")
    return FileResponse(f, media_type=VIEW_TYPES.get(f.suffix.lower(), "application/octet-stream"))


@app.get("/api/home")
def home():
    """Every playlist as a card for the homepage: finished ones (with their video, thumbnail, title and description) and
    the ones still in progress. Newest first."""
    cards = []
    for d in DATA.iterdir():
        f = d / "project.json"
        if not f.exists():
            continue
        try:
            p = json.loads(f.read_text())
        except ValueError:
            continue
        out = d / "out"
        files = sorted(x for x in out.iterdir() if x.is_file()) if out.exists() else []
        video = next((x for x in files if x.suffix.lower() == ".mp4"), None)
        thumb = next((x for x in files if x.name.endswith(".thumbnail.jpg")), None)
        desc = next((x for x in files if x.name.endswith(".description.txt")), None)
        tit = next((x for x in files if x.name.endswith(".titles.txt")), None)
        size = sum(x.stat().st_size for x in d.rglob("*") if x.is_file())
        cards.append({
            "id": p["id"], "name": p["name"], "songs": len(p.get("tracks", [])), "links": len(p.get("links", [])),
            "minutes": round(sum(float(t.get("duration") or 0) for t in p.get("tracks", [])) / 60, 1),
            "created": p.get("created") or f.stat().st_mtime, "built": bool(video),
            "built_at": video.stat().st_mtime if video else None,
            "title": tit.read_text().partition("\n\nTAGS\n")[0].strip() if tit else "",
            "video": video.name if video else None, "thumbnail": thumb.name if thumb else None,
            "description": desc.name if desc else None,
            "thumb_tests": [x.name for x in files if re.search(r"\.thumbnail-[ABC]\.jpg$", x.name)], "size_mb": round(size / 1e6, 1),
            "stored_in": str(out) if video else str(d)})
    return sorted(cards, key=lambda c: -(c["built_at"] or c["created"]))


@app.get("/api/projects/{pid}/outputs/{name}")
def download(pid: str, name: str):
    f = pdir(pid) / "out" / Path(name).name
    if not f.exists():
        raise HTTPException(404, "not found")
    return FileResponse(f, filename=f.name)


@app.get("/api/jobs/{jid}")
def job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "no such job")
    return JOBS[jid]


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text()


# ---------- volume between songs ----------
class LevelSwitch(BaseModel):
    on: bool = False


@app.get("/api/projects/{pid}/loudness")
def loudness(pid: str):
    """How loud each song is and what gain would even them out. Measuring changes nothing."""
    p = load(pid)
    changed = False
    for t in p["tracks"]:
        if t.get("audio") and t.get("lufs") is None:
            t["lufs"] = _level.measure(t["audio"])
            changed = True
    if changed:
        save(pid, p)
    rows = [{"n": i, "title": t["title"], "artist": t.get("artist", ""), "lufs": t.get("lufs"),
             "gain_db": _level.gain_for(t.get("lufs"))} for i, t in enumerate(p["tracks"], 1)]
    vals = [r["lufs"] for r in rows if r["lufs"] is not None]
    return {"target": _level.TARGET, "tracks": rows, "spread": round(max(vals) - min(vals), 1) if vals else 0,
            "on": bool(p.get("level_audio"))}


@app.get("/api/projects/{pid}/level-demo")
def level_demo(pid: str, i: int = 1, mode: str = "original"):
    """The end of song i then the start of song i+1, as they are (original) or with the gains applied (evened)."""
    p = load(pid)
    if not 1 <= i < len(p["tracks"]):
        raise HTTPException(404, "pick a song that has another song after it")
    a, b = p["tracks"][i - 1], p["tracks"][i]
    ga, gb = (_level.gain_for(a.get("lufs")), _level.gain_for(b.get("lufs"))) if mode == "evened" else (0.0, 0.0)
    f = pdir(pid) / "work" / "leveldemo" / f"{i}-{ga:+.1f}-{gb:+.1f}.mp3"
    if not f.exists():
        try:
            _level.demo_clip(a["audio"], b["audio"], ga, gb, str(f))
        except RuntimeError as e:
            raise HTTPException(500, str(e))
    return FileResponse(f, media_type="audio/mpeg")


@app.put("/api/projects/{pid}/leveling")
def set_leveling(pid: str, req: LevelSwitch):
    p = load(pid)
    p["level_audio"] = req.on
    save(pid, p)
    return {"on": req.on}


# ---------- thumbnails: styles to pick from ----------
class ThumbPick(BaseModel):
    selected: list[dict] = []        # up to 3 of {"family": ..., "variant": ...}


def _thumb_ctx(p):
    prof = p.get("profile") or {}
    return {"moods": [m.strip() for m in (p.get("mood") or "").split(",") if m.strip()] or prof.get("moods", []),
            "title": p.get("youtube_title") or (p.get("desc_meta") or {}).get("title", ""),
            "minutes": sum(float(t.get("duration") or 0) for t in p.get("tracks", [])) / 60}


def _sample_covers():
    """Six plain coloured squares, so the styles can be browsed before any song is extracted. Real covers replace them at build."""
    from PIL import Image, ImageDraw
    d = DATA / "_previews"
    d.mkdir(exist_ok=True)
    out = []
    for i, (a, b) in enumerate([((230, 120, 90), (90, 40, 120)), ((70, 150, 220), (20, 30, 90)), ((240, 200, 120), (180, 80, 60)),
                                ((120, 200, 160), (20, 90, 90)), ((210, 120, 190), (60, 30, 100)), ((200, 200, 210), (40, 40, 60))]):
        f = d / f"sample_cover{i}.png"
        if not f.exists():
            im = Image.new("RGB", (400, 400))
            px = im.load()
            for y in range(400):
                for x in range(400):
                    t = (x + y) / 800
                    px[x, y] = tuple(int(a[c] * (1 - t) + b[c] * t) for c in range(3))
            ImageDraw.Draw(im).ellipse([110, 110, 290, 290], outline=(255, 255, 255), width=6)
            im.save(f)
        out.append(str(f))
    return out


@app.get("/api/thumb-families")
def thumb_families():
    """The thumbnail styles, best-viewed reference first, with the numbers behind that order."""
    out = [{**f, "ref_views": _thumbs.REFERENCE[f["id"]]["views"], "note": _thumbs.REFERENCE[f["id"]]["note"]} for f in _thumbs.FAMILIES]
    return sorted(out, key=lambda f: -f["ref_views"])


@app.get("/api/projects/{pid}/thumb/{family}/{variant}.jpg")
def thumb_preview(pid: str, family: str, variant: str, w: int = 640):
    p = load(pid)
    covers = [t["cover"] for t in p["tracks"] if t.get("cover")] or _sample_covers()     # no songs yet: browse with sample covers
    w = max(240, min(1280, w))
    ctx = _thumb_ctx(p)
    d = pdir(pid) / "work" / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    try:
        f = d / f"{family}-{variant}-{w}-{_thumbs.cache_key(family, variant, covers, ctx, (w, w * 9 // 16))}.jpg"
        if not f.exists():
            _thumbs.save_jpeg(_thumbs.render(family, variant, covers, ctx, (w, w * 9 // 16)), str(f))
    except ValueError as e:
        raise HTTPException(404, str(e))
    return FileResponse(f, media_type="image/jpeg")


@app.put("/api/projects/{pid}/thumbs")
def set_thumbs(pid: str, req: ThumbPick):
    ok = {f["id"]: set(f["variants"]) for f in _thumbs.FAMILIES}
    sel = []
    for x in req.selected[:3]:
        if x.get("family") in ok and x.get("variant") in ok[x["family"]] and x not in sel:
            sel.append({"family": x["family"], "variant": x["variant"]})
    p = load(pid)
    p["thumbs_selected"] = sel
    save(pid, p)
    return {"selected": sel}


# ---------- library: songs you sorted into categories ----------
LIB = Library(DATA / "library.json")


class NewCategory(BaseModel):
    name: str


class LibLinks(BaseModel):
    links: list[str]


class CopyReq(BaseModel):
    to: str
    move: bool = False


class MakePlaylist(BaseModel):
    song_ids: list[str] = []
    name: str = ""


def _fetch_meta(link):
    """Title, artist, length, thumbnail of one link. Metadata only: nothing is downloaded."""
    if "spotify.com" in link:
        m = _metadata.resolve(link)
        return {"title": m["title"], "artist": m["artist"], "duration": m.get("duration") or 0,
                "cover_url": m.get("cover_url"), "source_link": link, "id": "", "web_tags": []}
    try:
        return ytdlp.info(link)
    except Exception as first:
        m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})", link)
        if not m:
            raise
        vid = m.group(1)                      # yt-dlp failed (e.g. YouTube's bot check): use YouTube's public oEmbed instead
        try:
            import requests
            r = requests.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"}, timeout=15)
            r.raise_for_status()
            j = r.json()
        except Exception:
            raise first
        title, artist = _metadata.clean_title(j.get("title", "")), ""
        if " - " in title:
            artist, title = [x.strip() for x in title.split(" - ", 1)]
        return {"title": title, "artist": artist, "duration": 0, "cover_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                "id": vid, "web_tags": [], "views": 0, "source_link": f"https://www.youtube.com/watch?v={vid}"}


@app.get("/api/library")
def library_home():
    return {"categories": LIB.categories()}


@app.post("/api/library/categories")
def library_new_category(req: NewCategory):
    try:
        return {"id": LIB.add_category(req.name)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/library/categories/{cid}")
def library_delete_category(cid: str):
    try:
        LIB.delete_category(cid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/library/{cid}")
def library_category(cid: str):
    try:
        cat = next(c for c in LIB.categories() if c["id"] == cid)
        return {"category": cat, "songs": LIB.songs(cid), "stats": LIB.stats(cid)}
    except (KeyError, StopIteration):
        raise HTTPException(404, "no such category")


@app.post("/api/library/{cid}/songs")
def library_add(cid: str, req: LibLinks):
    if not any(l.strip() for l in req.links):
        raise HTTPException(400, "paste at least one link")
    try:
        added, problems = LIB.add_songs(cid, req.links, _fetch_meta)
    except KeyError:
        raise HTTPException(404, "no such category")
    return {"added": added, "problems": problems}


@app.delete("/api/library/{cid}/songs/{sid}")
def library_remove(cid: str, sid: str):
    try:
        LIB.remove_song(cid, sid)
    except KeyError:
        raise HTTPException(404, "no such song")
    return {"ok": True}


@app.post("/api/library/{cid}/songs/{sid}/copy")
def library_copy(cid: str, sid: str, req: CopyReq):
    try:
        LIB.copy_song(cid, sid, req.to, req.move)
    except KeyError:
        raise HTTPException(404, "no such song or category")
    return {"ok": True}


@app.post("/api/library/{cid}/make-playlist")
def library_make_playlist(cid: str, req: MakePlaylist):
    """New playlist whose links are the chosen songs (or all of them), in the order shown. Then continue as usual."""
    try:
        cat = next(c for c in LIB.categories() if c["id"] == cid)
        songs = LIB.songs(cid)
    except (KeyError, StopIteration):
        raise HTTPException(404, "no such category")
    pick = [s for s in songs if not req.song_ids or s["id"] in req.song_ids]
    if req.song_ids:
        order = {sid: i for i, sid in enumerate(req.song_ids)}
        pick.sort(key=lambda s: order[s["id"]])
    if not pick:
        raise HTTPException(400, "this category has no songs yet")
    name = req.name.strip() or cat["name"]
    pid = _new_project(name, [s["link"] for s in pick])
    LIB.mark_used(cid, {s["id"] for s in pick}, name)
    return {"id": pid}
