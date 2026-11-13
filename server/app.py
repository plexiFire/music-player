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

from engine import cli  # noqa: E402
from engine.media import audio  # noqa: E402
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


class BuildReq(BaseModel):
    preview: bool = True
    offline: bool = False
    no_llm: bool = False


# ---------- projects ----------
@app.post("/api/projects")
def create(req: NewProject):
    pid = uuid.uuid4().hex[:8]
    d = DATA / pid
    (d / "audio").mkdir(parents=True)
    (d / "work").mkdir()
    (d / "out").mkdir()
    name = req.name.strip() or "Playlist"
    save(pid, {"id": pid, "name": name, "title": name, "theme": name, "links": [], "tracks": [],
               "rights_confirmed": False, "mood": "", "channel": "", "contact_email": "", "hashtags": [],
               "youtube_title": ""})
    return {"id": pid}


@app.get("/api/projects")
def list_projects():
    out = []
    for d in sorted(DATA.iterdir()):
        if (d / "project.json").exists():
            p = json.loads((d / "project.json").read_text())
            out.append({"id": p["id"], "name": p["name"], "tracks": len(p["tracks"]), "links": len(p["links"])})
    return out


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


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return with_estimate(load(pid))


@app.put("/api/projects/{pid}/links")
def set_links(pid: str, req: Links):
    p = load(pid)
    p["links"] = [l.strip() for l in req.links if l.strip()]   # order = play order
    p["tracks"] = []                                           # links changed: extract again
    save(pid, p)
    return with_estimate(p)


@app.put("/api/projects/{pid}/settings")
def set_settings(pid: str, req: Settings):
    p = load(pid)
    p["mood"] = req.mood.strip()
    p["channel"] = req.channel.strip()
    p["contact_email"] = req.contact_email.strip()
    p["hashtags"] = [h.strip().lstrip("#").replace(" ", "") for h in req.hashtags if h.strip()]
    p["youtube_title"] = req.youtube_title.strip()
    save(pid, p)
    return with_estimate(p)


# ---------- step 2: extract ----------
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
    p["tracks"] = tracks
    save(pid, p)


@app.post("/api/projects/{pid}/extract")
def extract(pid: str, req: Extract):
    p = load(pid)
    if not p["links"]:
        raise HTTPException(400, "add at least one link first")
    if not req.rights_confirmed:
        raise HTTPException(400, "confirm you own or are licensed to use these audio files")
    p["rights_confirmed"] = True
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
def _build(jid, pid, req):
    import contextlib
    import io
    d = pdir(pid)
    p = load(pid)
    slug = re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-") or "playlist"
    out = d / "out" / f"{slug}.mp4"
    ns = argparse.Namespace(project=str(d / "project.json"), out=str(out), preview=req.preview,
                            offline=req.offline, no_llm=req.no_llm)
    buf = io.StringIO()
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
    head, _, tags = tit.read_text().partition("\n\nTAGS\n")
    return {"title": head.strip(), "tags": tags.strip(), "description": desc.read_text().strip()}


@app.get("/api/projects/{pid}/outputs")
def outputs(pid: str):
    d = pdir(pid) / "out"
    return sorted(f.name for f in d.iterdir() if f.is_file()) if d.exists() else []


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
