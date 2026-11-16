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
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Form, Header, HTTPException, UploadFile, File  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from engine import cli, publish  # noqa: E402
from engine.titles import suggest as suggest_titles  # noqa: E402
from engine.video import timestamps as _stamps  # noqa: E402
from engine.media import audio, level as _level, trim as autotrim, voice as _voice  # noqa: E402
from engine.look import vinyl  # noqa: E402
from engine.publish import gpt_brief as _gpt, thumbs as _thumbs  # noqa: E402
from engine.titles import profile as _profile  # noqa: E402
from engine.sources import metadata as _metadata, musicbrainz as _mb  # noqa: E402
from server.library import Library  # noqa: E402
from server import reconcile as _rec  # noqa: E402
from server.agent import Agent  # noqa: E402
from server.helper import Helper, files_of, cleanup as _cleanup_downloads  # noqa: E402
from engine.playlist import importer  # noqa: E402
from engine.sources import ytdlp  # noqa: E402

def _default_data_dir():
    if "SENORA_DATA" in os.environ:
        return Path(os.environ["SENORA_DATA"])
    app_support = Path.home() / "Library" / "Application Support" / "Senora" / "data"
    if app_support.is_dir():
        return app_support
    return ROOT / "work" / "ui"

DATA = _default_data_dir()
DATA.mkdir(parents=True, exist_ok=True)
JOBS: dict = {}
LOCK = threading.Lock()
RENDER_FACTOR = 0.35   # with segment concat optimization: ~0.35x real-time on cloud runners (~5-6m for 19.5m video)
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
    f = pdir(pid) / "project.json"
    try:
        return json.loads(f.read_text())
    except (ValueError, OSError):
        bak = f.with_suffix(".json.bak")                      # a crash in the middle of a write: go back to the version before it
        if bak.exists():
            p = json.loads(bak.read_text())
            shutil.copy2(bak, f)
            return p
        raise HTTPException(500, "this playlist's file is damaged and there is no backup")


_SAVE_LOCK = threading.Lock()


def save(pid, p):
    """Write to a temp file, then swap it in: a reader never sees half-written JSON."""
    target = pdir(pid) / "project.json"
    tmp = target.with_suffix(".json.tmp")
    with _SAVE_LOCK:
        tmp.write_text(json.dumps(p, indent=1, ensure_ascii=False))
        if target.exists():
            shutil.copy2(target, target.with_suffix(".json.bak"))           # the last good version, kept next to it
        os.replace(tmp, target)


_MUTATE = threading.RLock()


def mutate(pid, fn):
    """Read-change-write of a project as ONE step, so two things happening at once (an extraction finishing a song while you edit
    the links) can never overwrite each other. fn(p) changes p in place; if it raises, nothing is saved."""
    with _MUTATE:
        p = load(pid)
        fn(p)
        save(pid, p)
        return p


INTERRUPTED = ("The server stopped while this was running (a restart or a crash). Nothing that was already finished is lost: "
               "press the button again and only what is missing is done.")


def _persist_job(j):
    try:
        d = DATA / "_jobs"
        d.mkdir(exist_ok=True)
        tmp = d / f"{j['id']}.tmp"
        tmp.write_text(json.dumps(j, ensure_ascii=False))
        os.replace(tmp, d / f"{j['id']}.json")
    except OSError:
        pass


def _recover_jobs():
    """Jobs that were running when the server stopped are now 'interrupted' (and old records are tidied away after a week)."""
    d = DATA / "_jobs"
    if not d.exists():
        return
    for f in d.glob("*.json"):
        try:
            j = json.loads(f.read_text())
            if time.time() - f.stat().st_mtime > 7 * 86400:
                f.unlink()
            elif j.get("state") == "running":
                if j.get("kind") == "send":
                    jid = j.get("id")
                    pid = j.get("project")
                    with LOCK:
                        JOBS[jid] = dict(j)
                    def resume_watcher(j_id, p_id):
                        from helper import send as _send
                        dest = pdir(p_id) / "rendered"
                        dest.mkdir(parents=True, exist_ok=True)
                        try:
                            runs = _send.render_runs(("queued", "in_progress"))
                            if not runs:
                                set_job(j_id, state="interrupted", message="No active GitHub render found after restart.")
                                return
                            tag = runs[0].get("head_branch") or ""
                            rel_tag = tag.replace("send-", "job-")
                            assets = _send.wait_for_release(rel_tag, log=lambda m: set_job(j_id, message=m[:200]))
                            remote_meta = {}
                            for a in assets:
                                remote_meta[a["name"]] = {"url": a.get("browser_download_url", ""), "size": a.get("size", 0), "tag": rel_tag}
                                if not a["name"].endswith(".mp4"):
                                    _send.download(a, dest / a["name"])
                            (dest / "remote_assets.json").write_text(json.dumps(remote_meta, indent=2))
                            for adir in [pdir(p_id) / "audio", pdir(p_id) / "work"]:
                                if adir.exists():
                                    for af in adir.iterdir():
                                        if af.is_file():
                                            try: af.unlink()
                                            except Exception: pass
                            set_job(j_id, state="done", message="Render complete! Video ready.")
                        except Exception:
                            pass
                    threading.Thread(target=resume_watcher, args=(jid, pid), daemon=True).start()
                else:
                    j.update(state="interrupted", message=INTERRUPTED)
                    _persist_job(j)
        except (OSError, ValueError):
            continue


def new_job(kind, pid):
    jid = uuid.uuid4().hex[:8]
    with LOCK:
        JOBS[jid] = {"id": jid, "kind": kind, "project": pid, "state": "running", "message": "starting",
                     "started": time.time(), "log": ""}
        snap = dict(JOBS[jid])
    _persist_job(snap)
    return jid


def set_job(jid, **kw):
    with LOCK:
        JOBS[jid].update(kw)
        snap = dict(JOBS[jid])
    _persist_job(snap)


CANCEL = {}          # job id -> Event: set when you press Stop


def run_bg(jid, fn, *args):
    ev = CANCEL[jid] = threading.Event()

    def wrap():
        from engine import procs
        procs.bind(ev)
        try:
            fn(jid, *args)
            set_job(jid, state="done", message="done")
        except procs.Cancelled:
            set_job(jid, state="stopped", message="Stopped by you. Nothing was lost: press the button again and it carries on.")
        except Exception as e:  # shown in the UI, never crashes the server
            if ev.is_set():
                set_job(jid, state="stopped", message="Stopped by you. Nothing was lost: press the button again and it carries on.")
            else:
                set_job(jid, state="failed", message=str(e))
        finally:
            CANCEL.pop(jid, None)
    threading.Thread(target=wrap, daemon=True).start()


# ---------- the local helper: this computer fetches songs from YouTube, only while it is switched on ----------
MODE = os.environ.get("SENORA_MODE", "local")       # "local": this page runs on your computer. "cloud": hosted; songs come from your helper
HELPER = Helper(DATA / "_helper.json")
AGENT = Agent(DATA / "_agent")


from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
app.add_middleware(CORSMiddleware, allow_origin_regex=r"https://[a-z0-9-]+\.github\.io|http://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def _password_for_the_hosted_page(request, call_next):
    """Hosted (cloud mode) pages are public on the internet, so they ask for a password (SENORA_PASSWORD; any user name). Without one set,
    nothing is served. The helper on your computer uses its own token and is let through only on /api/agent/*."""
    if MODE == "cloud" and not request.url.path.startswith("/api/agent/"):
        import base64
        import secrets as _sec
        from fastapi.responses import PlainTextResponse
        want = os.environ.get("SENORA_PASSWORD", "")
        if not want:
            return PlainTextResponse("This hosted Senora has no password set. Set SENORA_PASSWORD on the host, then reload.", status_code=503)
        got = ""
        h = request.headers.get("authorization", "")
        if h.lower().startswith("basic "):
            try:
                got = base64.b64decode(h[6:]).decode().partition(":")[2]
            except Exception:
                got = ""
        if not _sec.compare_digest(got.encode(), want.encode()):
            return PlainTextResponse("Password needed", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Senora"'})
    return await call_next(request)


@app.get("/api/helper")
def helper_status():
    with LOCK:
        busy = next((j for j in JOBS.values() if j["kind"] == "extract" and j["state"] == "running"), None)
    on = HELPER.is_on()
    if MODE == "cloud":
        msg = ("Your computer is connected" + (": fetching songs now" if busy else ": waiting until a song has to be fetched")) if (on and AGENT.connected()) \
            else ("Not connected: press Connect my computer" if on else "Off")
    else:
        msg = ("Fetching songs now" if busy else "Waiting: it works only when a song has to be fetched") if on else "Off"
    return {"on": on, "busy": bool(busy), "message": msg, "mode": MODE, "connected": AGENT.connected()}


@app.get("/api/github-token")
def github_token():
    from helper import send as _send
    return {"token": _send._token()}


class HelperReq(BaseModel):
    on: bool


@app.put("/api/helper")
def helper_set(req: HelperReq):
    HELPER.set(req.on)
    return helper_status()


@app.post("/api/helper/pair")
def helper_pair():
    """A one-time code to type into the helper on your computer."""
    code, life = AGENT.new_code()
    return {"code": code, "expires_in": life}


@app.post("/api/helper/disconnect")
def helper_disconnect():
    AGENT.revoke_all()
    return helper_status()


class PairReq(BaseModel):
    code: str


@app.post("/api/agent/pair")
def agent_pair(req: PairReq):
    try:
        return {"token": AGENT.pair(req.code)}
    except ValueError as e:
        raise HTTPException(400, str(e))


def _agent(token):
    if not AGENT.check(token):
        raise HTTPException(401, "this computer is not connected: pair it again")


@app.get("/api/agent/next")
def agent_next(x_agent_token: str = Header(default="")):
    _agent(x_agent_token)
    AGENT.requeue_lost()
    if not HELPER.is_on():
        return {"task": None}
    return {"task": AGENT.claim()}


class Progress(BaseModel):
    message: str = ""


@app.post("/api/agent/tasks/{tid}/progress")
def agent_progress(tid: str, req: Progress, x_agent_token: str = Header(default="")):
    _agent(x_agent_token)
    try:
        AGENT.update(tid, message=req.message[:200])
    except KeyError:
        raise HTTPException(404, "no such task")
    return {"ok": True}


class Failed(BaseModel):
    error: str = ""


@app.post("/api/agent/tasks/{tid}/fail")
def agent_fail(tid: str, req: Failed, x_agent_token: str = Header(default="")):
    _agent(x_agent_token)
    try:
        AGENT.update(tid, state="failed", error=req.error[:300], message="failed")
    except KeyError:
        raise HTTPException(404, "no such task")
    return {"ok": True}


@app.post("/api/agent/tasks/{tid}/result")
async def agent_result(tid: str, meta: str = Form(...), files: list[UploadFile] = File(default=[]), x_agent_token: str = Header(default="")):
    """The songs the helper fetched: `meta` lists the tracks (with audio_name / cover_name), `files` carries those files."""
    _agent(x_agent_token)
    task = AGENT.get(tid)
    if not task:
        raise HTTPException(404, "no such task")
    d = pdir(task["pid"])
    (d / "audio").mkdir(exist_ok=True)
    (d / "work").mkdir(exist_ok=True)
    got = {os.path.basename(f.filename or ""): f for f in files}
    tracks = []
    for k, t in enumerate(json.loads(meta)):
        t = dict(t)
        for field, sub, kind in (("audio", "audio", "audio_name"), ("cover", "work", "cover_name")):
            name = os.path.basename(t.pop(kind, "") or "")
            t[field] = None
            if name and name in got:
                dst = d / sub / f"{task['id']}_{k}_{name}"
                dst.write_bytes(await got[name].read())
                t[field] = str(dst)
        t["from_helper"] = True
        tracks.append(t)
    AGENT.update(tid, state="done", tracks=tracks, message="uploaded")
    return {"ok": True, "tracks": len(tracks)}


@app.get("/api/agent/finished")
def agent_finished(x_agent_token: str = Header(default="")):
    """Playlists whose video is finished: the helper may now delete its own local copies for them."""
    _agent(x_agent_token)
    done = []
    for t in list(AGENT.tasks.values()):
        try:
            if t["state"] == "done" and load(t["pid"]).get("finished"):
                done.append(t["pid"])
        except HTTPException:
            done.append(t["pid"])                      # the playlist was deleted: nothing needs the local copy any more
    return {"playlists": sorted(set(done))}


def _fetch(jid, pid, link, idx, d, note):
    """One link -> track dicts. On your own computer: downloaded right here. Hosted: asked of your helper and uploaded to us."""
    if MODE != "cloud":
        return importer.import_one(link, str(d / "audio"), str(d / "work"), idx, authorized=True, lookup=True)
    from engine import procs
    tid = AGENT.enqueue(pid, link, idx)
    last = ""
    while True:
        procs.check()
        t = AGENT.get(tid)
        if t["state"] == "done":
            return t["tracks"]
        if t["state"] == "failed":
            raise RuntimeError(t["error"] or "your computer could not fetch it")
        msg = t["message"] if AGENT.connected() or t["state"] == "claimed" else "waiting: your computer is not connected (press Connect my computer)"
        if msg != last:
            note(msg)
            last = msg
        time.sleep(1)


# ---------- channel defaults: remembered for every new playlist ----------# ---------- channel defaults: remembered for every new playlist ----------
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
    force: bool = False          # true = throw the extracted songs away and extract everything again


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


def delete_github_release_for_project(project: dict):
    """Deletes matching GitHub Release and tag when a playlist is deleted."""
    try:
        from helper import send as _send
        tok = _send._token()
        if not tok:
            return []
        slug = re.sub(r"[^a-z0-9]+", "-", (project.get("name") or project.get("title") or "").lower()).strip("-")
        gh_tag = project.get("github_tag") or ""
        if not slug and not gh_tag:
            return []
        url = f"https://api.github.com/repos/{_send.OWNER_REPO}/releases?per_page=30"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            rels = json.loads(resp.read().decode())
        deleted = []
        for r in rels:
            assets = r.get("assets", [])
            tag = r.get("tag_name", "")
            match = False
            if gh_tag and tag == gh_tag:
                match = True
            elif slug and any(a.get("name", "").lower().startswith(slug) for a in assets):
                match = True
            if match:
                del_rel = urllib.request.Request(
                    f"https://api.github.com/repos/{_send.OWNER_REPO}/releases/{r['id']}",
                    method="DELETE",
                    headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
                )
                try:
                    urllib.request.urlopen(del_rel, timeout=10)
                    deleted.append(f"release {r['id']}")
                except Exception:
                    pass
                if tag:
                    del_tag = urllib.request.Request(
                        f"https://api.github.com/repos/{_send.OWNER_REPO}/git/refs/tags/{tag}",
                        method="DELETE",
                        headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
                    )
                    try:
                        urllib.request.urlopen(del_tag, timeout=10)
                        deleted.append(f"tag {tag}")
                    except Exception:
                        pass
        return deleted
    except Exception:
        return []


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    """Remove a playlist and everything stored for it (audio, pictures, built videos) locally and on GitHub."""
    d = pdir(pid)
    with LOCK:
        busy = [j for j in JOBS.values() if j["project"] == pid and j["state"] == "running"]
    if busy:
        raise HTTPException(409, "a job is still running for this playlist; wait for it to finish")
    p = None
    if (d / "project.json").exists():
        try:
            p = json.loads((d / "project.json").read_text())
        except Exception:
            pass
    if p:
        delete_github_release_for_project(p)
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
    p["plan"] = _rec.plan(p["links"], p["tracks"])                    # which links are extracted / still to do / failed / removed
    for row in p["plan"]["rows"]:
        row["seconds"] = round(sum(float(t.get("duration") or 0) for t in _rec.match([row["link"]], p["tracks"])[0][0]), 1)
    p["total_seconds"] = round(total, 1)
    return p


def _bg(mode, color):
    return {"mode": mode, "color": color} if mode in ("solid", "sky") else {"mode": "cover"}


def _repair_old_cuts(pid):
    """Cuts made before the fix lost the last seconds of the song when they started later than 0:00 (a fade-out in the wrong place).
    The original is always kept, so such a cut is simply made again, with the same start and end. Only the derived cut file is rewritten."""
    p = load(pid)
    bad = [i for i, t in enumerate(p["tracks"]) if t.get("trim") and t.get("audio_original") and os.path.exists(t["audio_original"])
           and os.path.exists(t.get("audio") or "") and float(t["trim"].get("start", 0)) > 0.05 and t["trim"].get("v") != 2]
    if not bad:
        return
    fixed = {}
    for i in bad:
        t = p["tracks"][i]
        dst = Path(t["audio"])
        out = audio.process(t["audio_original"], str(dst.parent), name=dst.stem, fmt=dst.suffix.lstrip(".") or "mp3",
                            start=float(t["trim"]["start"]), end=float(t["trim"]["end"]))
        fixed[t["audio"]] = (out, audio.probe(out)["duration"])

    def apply(p):
        for t in p["tracks"]:
            if t.get("audio") in fixed and t.get("trim") and t["trim"].get("v") != 2:
                t["audio"], t["duration"] = fixed[t["audio"]]
                t["trim"]["v"] = 2
    mutate(pid, apply)


def _repair_shared_covers(pid):
    """Two songs that point at the same cover file (an old numbering bug let a new song's cover overwrite another's): give each song
    its own picture again, from its own video's thumbnail. Pictures you uploaded are never touched."""
    p = load(pid)
    groups = {}
    for t in p["tracks"]:
        if t.get("cover"):
            groups.setdefault(t["cover"], []).append(t)
    bad = [t for g in groups.values() if len(g) > 1 for t in g if not str(t.get("image_source", "")).startswith("upload:")]
    if not bad:
        return
    d = pdir(pid) / "work" / "art"
    d.mkdir(parents=True, exist_ok=True)
    fixed = {}
    for t in bad:
        src = str(t.get("image_source", ""))
        link = src.split(": ", 1)[1] if src.startswith("link thumbnail:") else (t.get("from_link") or t.get("source_link") or "")
        key = _rec.link_key(link)
        if not key.startswith("yt:"):
            continue                                              # no video to take a picture from: leave it
        uid = t.get("uid") or uuid.uuid4().hex[:8]
        for name in ("maxresdefault", "hqdefault"):
            try:
                out = importer._square_png_from_url(f"https://i.ytimg.com/vi/{key[3:]}/{name}.jpg", str(d / f"cover_{uid}_fix.png"))
                fixed[(t.get("audio"), t.get("title"))] = (out, uid)
                break
            except Exception:
                continue
    if not fixed:
        return

    def apply(q):
        for t in q["tracks"]:
            f = fixed.get((t.get("audio"), t.get("title")))
            if f:
                t["cover"], t["uid"] = f
    mutate(pid, apply)


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    try:
        _repair_old_cuts(pid)
    except Exception:
        pass                                   # never stop a project from opening because a repair failed
    try:
        _repair_shared_covers(pid)
    except Exception:
        pass
    return with_estimate(load(pid))


@app.put("/api/projects/{pid}/links")
def set_links(pid: str, req: Links):
    """The links are what you want in the playlist, in this order. Songs already extracted for a link you keep are kept (even if you
    reorder), songs of removed links leave the playlist (their files stay on disk), new links wait for the next Extract."""
    links = [l.strip() for l in req.links if l.strip()]

    def change(p):
        before = [_rec.track_key(t) for t in p["tracks"]]
        p["links"] = links
        p["tracks"], _ = _rec.reconcile(links, p["tracks"])
        if before != [_rec.track_key(t) for t in p["tracks"]]:
            p.pop("description_override", None)                 # the tracklist changed: a hand-edited text no longer fits

    return with_estimate(mutate(pid, change))


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
        prof = _profile.build(p["tracks"], online=False, use_llm=False)
        p["profile"] = prof
        mutate(pid, lambda q: q.setdefault("profile", prof))
    if req.online and p.get("profile"):           # "Refresh with YouTube research": look at today's top videos again
        pool = _profile.tag_pool(p["profile"])
        p["profile"]["tag_pool"] = pool
        mutate(pid, lambda q: q["profile"].__setitem__("tag_pool", pool) if q.get("profile") is not None else None)
    proj = {**p, "title": p.get("title") or p["name"], "theme": p.get("theme") or p["name"]}
    theme = proj["theme"]
    durs = [float(t.get("duration") or 0) for t in p["tracks"]]
    _, ts = _stamps.build(p["tracks"], durs)
    found = suggest_titles(proj, n=8, mood=p.get("mood", ""), online=req.online, use_llm=req.use_llm,
                           history_path=str(DATA / "titles_history.json"), project_name=p["name"], record=False,
                           exclude=req.exclude)
    bank = _bank()
    hidden = set(bank["hidden"])
    opts = [c for c in found["titles"] if c["title"].lower() not in hidden]           # titles you crossed out never come back
    chosen = p.get("youtube_title") or (opts[0]["title"] if opts else publish.title_ideas(theme)[0])
    mine = [{"title": c["title"], "score": 100, "source": "mine", "id": c["id"]} for c in bank["custom"]]   # your own titles come first
    desc = publish.compose.sync_tracklist(p["description_override"], ts) if p.get("description_override") \
        else publish.description_text(proj, chosen, ts, theme, use_llm=req.use_llm)
    auto = publish.description_text(proj, chosen, ts, theme, use_llm=req.use_llm) if p.get("description_override") else desc
    suggested_tags = re.findall(r"#(\w+)", auto.strip().splitlines()[-1])         # the automatic set: you can add any of them by click
    if not p.get("description_override"):          # remember what the title-based parts are, so a later title change can patch them
        meta = {"title": chosen, "hook": publish.compose.hook_paragraph(desc)}
        mutate(pid, lambda q: None if q.get("description_override") else q.update(desc_meta=meta))
    used_tags = re.findall(r"#(\w+)", desc.strip().splitlines()[-1])          # exactly the hashtags the description ends with
    return {"titles": mine + [{"title": c["title"], "score": c["score"], "source": c["source"]} for c in opts],
            "hidden_titles": len(hidden),
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
    found = {}
    for t in p["tracks"]:
        if t.get("audio") and not t.get("trim") and not t.get("suggestion_dismissed"):
            c = dict(t)
            try:
                _suggest_cut(c)
                found[t["audio"]] = c.get("suggestion")
            except Exception:
                pass

    def store(q):
        for t in q["tracks"]:
            if t.get("audio") in found and not t.get("trim"):
                t.pop("suggestion", None)
                if found[t["audio"]]:
                    t["suggestion"] = found[t["audio"]]
    p = mutate(pid, store)
    return {**with_estimate(p), "flagged": sum(1 for v in found.values() if v)}


def _usable(t):
    return bool(t.get("audio")) and not t.get("error")


def _next_cover_index(d, p):
    """A number for the next cover file that no earlier cover (even of a removed song) ever used: the old 'songs + 1' reused numbers
    after a song was taken out, so a new song's cover overwrote another song's cover file."""
    used = {int(p.get("next_index", 1)) - 1, len(p["tracks"])}
    names = [f.name for f in (d / "work").glob("cover*")] if (d / "work").exists() else []
    names += [os.path.basename(t.get("cover") or "") for t in p["tracks"]]
    names += [os.path.basename((x.get("track") or {}).get("cover") or "") for x in p.get("trash", [])]
    for nme in names:
        m = re.match(r"cover(\d+)", nme)
        if m:
            used.add(int(m.group(1)))
    return max(used) + 1


def _extract(jid, pid):
    """Extract only what is missing. Every finished song is saved at once and merged with the CURRENT links, so you can go back,
    add / remove / reorder links while this runs: nothing done is lost, nothing removed comes back."""
    d = pdir(pid)
    p = load(pid)
    todo = _rec.todo(p["links"], p["tracks"])
    n = len(todo)
    songs = [{"link": l, "state": "waiting"} for l in todo]
    set_job(jid, songs=songs)
    for i, link in enumerate(todo, 1):
        cur = load(pid)
        if _rec.link_key(link) not in {_rec.link_key(l) for l in cur["links"]}:
            songs[i - 1]["state"] = "skipped"
            continue                                              # you removed this link meanwhile: skip it
        t0 = time.time()
        songs[i - 1]["state"] = "fetching"
        set_job(jid, message=f"track {i}/{n}", songs=[dict(x) for x in songs])
        idx = _next_cover_index(d, cur)
        try:
            def note(m, i=i):
                songs[i - 1]["note"] = m
                set_job(jid, songs=[dict(x) for x in songs])
            got = _fetch(jid, pid, link, idx, d, note)
            for t in got:
                t["from_link"] = link
                t["uid"] = uuid.uuid4().hex[:8]                  # a name for this song that never changes when songs move
            songs[i - 1].update(state="done", secs=round(time.time() - t0, 1), title=(got[0].get("title") if got else ""))
        except Exception as e:
            songs[i - 1].update(state="failed", secs=round(time.time() - t0, 1), error=str(e)[:160])
            got = [{"title": link, "artist": "", "audio": None, "cover": None, "error": str(e), "from_link": link,
                    "source_link": link, "audio_source": f"link: {link}", "image_source": "none"}]

        def merge(p, got=got, link=link, idx=idx):
            if _rec.link_key(link) not in {_rec.link_key(l) for l in p["links"]}:
                return                                            # removed while it was downloading: its files stay, nothing is added
            k = _rec.link_key(link)
            p["tracks"] = [t for t in p["tracks"] if not (_rec.track_key(t) == k and not _usable(t))]   # a retry replaces the failure
            p["tracks"] += got
            p["tracks"], _ = _rec.reconcile(p["links"], p["tracks"])
            p["downloaded"] = sorted(set(p.get("downloaded", [])) | set(files_of(got)))      # exactly what the helper fetched
            p["next_index"] = idx + len(got)
            p.pop("description_override", None)

        mutate(pid, merge)
        set_job(jid, songs=[dict(x) for x in songs])

    cur = load(pid)
    fresh = [t for t in cur["tracks"] if _usable(t) and not t.get("analysed")]
    found = {}
    for i, t in enumerate(fresh, 1):                              # cut SUGGESTIONS only: nothing is cut unless you press Apply
        set_job(jid, message=f"analysing audio {i}/{len(fresh)}")
        c = dict(t)
        try:
            _suggest_cut(c)
        except Exception:
            pass
        found[t["audio"]] = c.get("suggestion")
    if fresh:
        set_job(jid, message="checking artist names")
        copies = [dict(t) for t in fresh]
        try:
            _mb.fix_artists(copies)                               # replaces an uploader label by the real artist
        except Exception:
            pass
        names = {c["audio"]: {k: c[k] for k in ("title", "artist", "web_tags", "artist_was") if k in c} for c in copies}

        def apply(p):
            for t in p["tracks"]:
                if t.get("audio") in found and not t.get("analysed"):
                    t["analysed"] = True
                    if found[t["audio"]]:
                        t["suggestion"] = found[t["audio"]]
                    t.update(names.get(t["audio"], {}))
        mutate(pid, apply)

    cur = load(pid)
    everything = bool(cur["tracks"]) and all(_usable(t) for t in cur["tracks"]) and not _rec.todo(cur["links"], cur["tracks"])
    if everything and (fresh or not cur.get("profile")):
        set_job(jid, message="detecting genre and mood")
        try:
            prof = _profile.build([dict(t) for t in cur["tracks"]], online=True, use_llm=True)
        except Exception as e:
            prof = {"genres": [], "moods": [], "mood": "", "query": "", "hashtags": [], "features": [],
                    "source": [], "warning": f"genre detection failed: {type(e).__name__}"}
        mutate(pid, lambda p: p.update(profile=prof))


@app.post("/api/projects/{pid}/extract")
def extract(pid: str, req: Extract):
    p = load(pid)
    if not p["links"]:
        raise HTTPException(400, "add at least one link first")
    if not req.rights_confirmed:
        raise HTTPException(400, "confirm you own or are licensed to use these audio files")
    if not HELPER.is_on():
        raise HTTPException(400, "The helper is off. Switch it on at the top of the page so this computer can fetch the songs.")
    with LOCK:
        running = next((j for j in JOBS.values() if j["project"] == pid and j["kind"] == "extract" and j["state"] == "running"), None)
    if running:
        return {"job": running["id"], "already_running": True}    # one extraction at a time: join the one that is running

    def change(p):
        p["rights_confirmed"] = True
        if req.force:
            p["tracks"] = []                                      # extract everything again (the files of the old ones stay on disk)
            p.pop("profile", None)
    mutate(pid, change)
    jid = new_job("extract", pid)
    run_bg(jid, _extract, pid)
    return {"job": jid, "todo": len(_rec.todo(load(pid)["links"], load(pid)["tracks"]))}


@app.post("/api/jobs/{jid}/terminate")
def terminate_job(jid: str):
    """Hard terminate: kill local processes immediately, cancel GitHub Actions run, and mark job terminated."""
    set_job(jid, state="terminated", message="Terminated by you.")
    ev = CANCEL.get(jid)
    if ev:
        ev.set()
    from engine import procs
    procs.kill_all()                     # do not wait for the next check: end ffmpeg now
    if JOBS.get(jid, {}).get("kind") == "send":
        # end the render on GitHub too, in the background so this button answers at once
        from helper import send as _send
        threading.Thread(target=_send.cancel_all_renders, kwargs={"log": lambda m: print(m, flush=True)}, daemon=True).start()
    return {"stopped": True, "terminated": True}


@app.post("/api/jobs/{jid}/stop")
def stop_job(jid: str):
    """Stop the job and mark it stopped."""
    set_job(jid, state="stopped", message="Stopped by you.")
    ev = CANCEL.get(jid)
    if ev:
        ev.set()
    from engine import procs
    procs.kill_all()                     # do not wait for the next check: end ffmpeg now
    if JOBS.get(jid, {}).get("kind") == "send":
        # end the render on GitHub too, in the background so this button answers at once
        from helper import send as _send
        threading.Thread(target=_send.cancel_all_renders, kwargs={"log": lambda m: print(m, flush=True)}, daemon=True).start()
    return {"stopped": True}


@app.get("/api/projects/{pid}/active-job")
def active_job(pid: str):
    """The extraction or build that is running for this playlist right now (so the page can pick it up after you went back and forth)."""
    pdir(pid)
    with LOCK:
        j = next((dict(j) for j in JOBS.values() if j["project"] == pid and j["state"] == "running"), None)
    if not j:
        try:
            from helper import send as _send
            runs = _send.render_runs(("queued", "in_progress"))
            if runs:
                tag = runs[0].get("head_branch") or ""
                if tag.startswith("send-"):
                    jid = new_job("send", pid)
                    set_job(jid, message="rendering on GitHub...")
                    def resume_watcher(j_id, p_id, t):
                        dest = pdir(p_id) / "rendered"
                        dest.mkdir(parents=True, exist_ok=True)
                        try:
                            rel_tag = t.replace("send-", "job-")
                            assets = _send.wait_for_release(rel_tag, log=lambda m: set_job(j_id, message=m[:200]))
                            remote_meta = {}
                            for a in assets:
                                remote_meta[a["name"]] = {"url": a.get("browser_download_url", ""), "size": a.get("size", 0), "tag": rel_tag}
                                if not a["name"].endswith(".mp4"):
                                    _send.download(a, dest / a["name"])
                            (dest / "remote_assets.json").write_text(json.dumps(remote_meta, indent=2))
                            for adir in [pdir(p_id) / "audio", pdir(p_id) / "work"]:
                                if adir.exists():
                                    for af in adir.iterdir():
                                        if af.is_file():
                                            try: af.unlink()
                                            except Exception: pass
                            set_job(j_id, state="done", message="Render complete! Video ready.")
                        except Exception:
                            pass
                    threading.Thread(target=resume_watcher, args=(jid, pid, tag), daemon=True).start()
                    with LOCK:
                        j = dict(JOBS[jid])
        except Exception:
            pass
    return {"job": j}


@app.delete("/api/projects/{pid}/tracks/{n}")
def remove_track(pid: str, n: int):
    """Take a song out of the playlist (and its link). Its files stay on disk; 'undo' puts it back."""
    def change(p):
        if not 1 <= n <= len(p["tracks"]):
            raise HTTPException(404, "no such song")
        t = p["tracks"].pop(n - 1)
        k = _rec.track_key(t)
        at = next((i for i, l in enumerate(p["links"]) if _rec.link_key(l) == k), None)
        link = None
        if at is not None and not any(_rec.track_key(x) == k for x in p["tracks"]):
            link = p["links"].pop(at)                             # a link that still has other songs stays
        p.setdefault("trash", []).append({"track": t, "link": link, "link_index": at, "track_index": n - 1})
        p["trash"] = p["trash"][-10:]
        p.pop("description_override", None)
    return with_estimate(mutate(pid, change))


@app.post("/api/projects/{pid}/tracks/undo-remove")
def undo_remove_track(pid: str):
    def change(p):
        if not p.get("trash"):
            raise HTTPException(404, "nothing to undo")
        x = p["trash"].pop()
        if x["link"] is not None:
            p["links"].insert(min(x["link_index"] if x["link_index"] is not None else len(p["links"]), len(p["links"])), x["link"])
        p["tracks"].insert(min(x["track_index"], len(p["tracks"])), x["track"])
        p["tracks"], _ = _rec.reconcile(p["links"], p["tracks"])
        p.pop("description_override", None)
    return with_estimate(mutate(pid, change))


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
def _set_cover(pid, t0, cover, source):
    """Store a new cover for the song `t0` (found again by its audio file, so a reorder meanwhile can not hit the wrong song)."""
    box = {}

    def apply(q):
        tt = next((x for x in q["tracks"] if x.get("audio") == t0.get("audio") and x.get("title") == t0.get("title")), None)
        if tt is None:
            raise HTTPException(409, "the playlist changed meanwhile: try again")
        tt.setdefault("uid", t0.get("uid") or uuid.uuid4().hex[:8])
        tt["cover"], tt["image_source"] = cover, source
        box["t"] = tt
    mutate(pid, apply)
    return box["t"]


@app.post("/api/projects/{pid}/tracks/{n}/cover-upload")
async def cover_upload(pid: str, n: int, file: UploadFile = File(...)):
    t = _track(load(pid), n)
    uid = t.get("uid") or uuid.uuid4().hex[:8]                  # file names use the song's own id, never its position
    d = pdir(pid) / "work" / "art"
    d.mkdir(parents=True, exist_ok=True)
    raw = d / f"upload_{uid}_raw"
    raw.write_bytes(await file.read())
    out = importer._square_png(str(raw), str(d / f"cover_{uid}_upload.png"))
    return _set_cover(pid, {**t, "uid": uid}, out, f"upload: {file.filename}")


@app.post("/api/projects/{pid}/tracks/{n}/cover-link")
def cover_link(pid: str, n: int, req: CoverLink):
    t = _track(load(pid), n)
    uid = t.get("uid") or uuid.uuid4().hex[:8]
    info = ytdlp.info(req.url)
    d = pdir(pid) / "work" / "art"
    d.mkdir(parents=True, exist_ok=True)
    out = importer._square_png_from_url(info["cover_url"], str(d / f"cover_{uid}_link.png"))
    return _set_cover(pid, {**t, "uid": uid}, out, f"link thumbnail: {req.url}")


@app.post("/api/projects/{pid}/tracks/{n}/trim")
def trim_track(pid: str, n: int, req: Trim):
    """Cut a song. The times are those of the audio you are hearing NOW (the page shows and plays that audio). If the song was cut
    before, they are converted to the original recording's timeline, so a second cut never loses quality and Undo still restores the original."""
    p = load(pid)
    t = _track(p, n)
    before_audio = t["audio"]
    src = t.get("audio_original") or t["audio"]
    full = audio.probe(src)["duration"]
    offset = float((t.get("trim") or {}).get("start", 0.0)) if t.get("audio_original") else 0.0
    now_len = float(t.get("duration") or audio.probe(t["audio"])["duration"])
    rel_start = max(0.0, req.start)
    rel_end = min(now_len, req.end) if req.end else now_len
    if rel_end - rel_start < 5:
        raise HTTPException(400, "the kept part must be at least 5 seconds")
    start, end = offset + rel_start, min(full, offset + rel_end)
    d = pdir(pid) / "audio"
    uid = t.get("uid") or uuid.uuid4().hex[:8]
    out = audio.process(src, str(d), name=f"trim_{uid}", fmt="mp3", start=start, end=end)
    new_dur = audio.probe(out)["duration"]
    box = {}

    def apply(q):
        tt = next((x for x in q["tracks"] if x.get("audio") == before_audio), None)
        if tt is None:
            raise HTTPException(409, "the playlist changed while cutting: try again")
        tt.setdefault("audio_original", src)
        tt.setdefault("uid", uid)
        tt["audio"], tt["duration"] = out, new_dur
        tt["trim"] = {"start": round(start, 2), "end": round(end, 2), "by": "manual", "v": 2}   # always on the ORIGINAL timeline
        tt.pop("suggestion", None)
        tt.pop("lufs", None)                                  # the loudness of the old audio no longer applies
        box["t"] = tt
    mutate(pid, apply)
    return box["t"]


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
    t = _track(load(pid), n)
    if not t.get("audio_original"):
        return t
    cut_audio, original = t["audio"], t["audio_original"]
    dur = audio.probe(original)["duration"]
    box = {}

    def apply(q):
        tt = next((x for x in q["tracks"] if x.get("audio") == cut_audio), None)
        if tt is None:
            raise HTTPException(409, "the playlist changed meanwhile: try again")
        tt["audio"] = tt.pop("audio_original", original)
        tt.pop("trim", None)
        tt["duration"] = dur
        tt.pop("lufs", None)                                  # the loudness of the old audio no longer applies
        box["t"] = tt
    mutate(pid, apply)
    return box["t"]


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
    mutate(pid, lambda q: q.__setitem__("finished", True))           # the helper may now delete its own local copies
    _cleanup_downloads(d, load(pid))      # removes only helper downloads whose upload the cloud confirmed; nothing today, as nothing uploads yet


@app.post("/api/projects/{pid}/render-on-github")
def render_on_github(pid: str, req: BuildReq = BuildReq()):
    """Send this playlist's songs to GitHub, which renders the video; the finished files come back into this playlist's folder."""
    p = load(pid)
    if not any(t.get("audio") for t in p["tracks"]):
        raise HTTPException(400, "extract the songs first")
    if not p.get("thumbs_selected"):
        raise HTTPException(400, "pick at least one thumbnail style first")
    with LOCK:
        busy = next((j for j in JOBS.values() if j["kind"] == "send" and j["state"] == "running"), None)
    if busy:
        raise HTTPException(409, "a render is already running: wait for it, or press Stop on it first")
    from helper import send as _send
    job_id = time.strftime("%Y%m%d-%H%M%S")
    jid = new_job("send", pid)
    set_job(jid, gh_job_id=job_id, gh_tag=f"send-{job_id}", rel_tag=f"job-{job_id}")

    def go(jid, pid):
        dest = pdir(pid) / "rendered"
        _send.send(str(pdir(pid) / "project.json"), str(dest), log=lambda m: set_job(jid, message=m[:200]), preview=req.preview, no_llm=req.no_llm, job_id=job_id)
    run_bg(jid, go, pid)
    return {"job": jid, "gh_tag": f"send-{job_id}", "rel_tag": f"job-{job_id}"}


@app.get("/api/projects/{pid}/rendered")
def rendered(pid: str):
    d = pdir(pid) / "rendered"
    if not d.exists():
        return {"files": []}
    names = set(f.name for f in d.iterdir() if f.is_file() and not f.name.startswith(".") and f.name != "remote_assets.json")
    meta_file = d / "remote_assets.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            names.update(meta.keys())
        except Exception:
            pass
    return {"files": sorted(names)}


@app.get("/api/projects/{pid}/rendered/{name}")
def rendered_file(pid: str, name: str):
    f = pdir(pid) / "rendered" / os.path.basename(name)
    if f.is_file():
        return FileResponse(str(f), filename=f.name)
    meta_file = pdir(pid) / "rendered" / "remote_assets.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            if name in meta:
                return RedirectResponse(meta[name]["url"], status_code=302)
        except Exception:
            pass
    raise HTTPException(404, "not there")


@app.post("/api/projects/{pid}/build")
def build(pid: str, req: BuildReq):
    p = load(pid)
    if not p["tracks"] or any(not t.get("audio") for t in p["tracks"]):
        raise HTTPException(400, "extract every track first")
    todo = _rec.todo(p["links"], p["tracks"])
    if todo:
        raise HTTPException(400, f"{len(todo)} link(s) are not extracted yet: extract them, or remove them from the links")
    if not p.get("thumbs_selected"):
        raise HTTPException(400, "pick at least one thumbnail style first")
    jid = new_job("build", pid)
    run_bg(jid, _build, pid, req)
    return {"job": jid}


def pouts(pid: str) -> list[Path]:
    """All output files for a playlist from either rendered/ (GitHub build) or out/ (local build)."""
    files = {}
    for d in [pdir(pid) / "rendered", pdir(pid) / "out"]:
        if d.exists():
            for f in d.iterdir():
                if f.is_file() and not f.name.startswith(".") and not f.name.endswith(".part.mp4") and f.name != "remote_assets.json":
                    files[f.name] = f
    return [files[k] for k in sorted(files.keys())]


@app.get("/api/projects/{pid}/text")
def text(pid: str):
    """The title, tags and description from the last build, ready to copy into YouTube."""
    outs = pouts(pid)
    desc = next((f for f in outs if f.name.endswith(".description.txt")), None)
    tit = next((f for f in outs if f.name.endswith(".titles.txt")), None)
    if not desc or not tit:
        raise HTTPException(404, "build first")
    head, _, _old_tags = tit.read_text().partition("\n\nTAGS\n")        # older builds also wrote tags; they are ignored
    return {"title": head.strip(), "description": desc.read_text().strip()}


@app.get("/api/projects/{pid}/outputs")
def outputs(pid: str):
    file_names = set(f.name for f in pouts(pid))
    meta_file = pdir(pid) / "rendered" / "remote_assets.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            file_names.update(meta.keys())
        except Exception:
            pass
    return sorted(file_names)


VIEW_TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".png": "image/png", ".txt": "text/plain; charset=utf-8"}


@app.get("/api/projects/{pid}/view/{name}")
def view_output(pid: str, name: str):
    """Open a built file in the browser (play the video, show the thumbnail, read the text) instead of downloading it."""
    fname = Path(name).name
    f = next((x for x in pouts(pid) if x.name == fname), None)
    if f and f.exists() and f.is_file():
        return FileResponse(f, media_type=VIEW_TYPES.get(f.suffix.lower(), "application/octet-stream"))
    meta_file = pdir(pid) / "rendered" / "remote_assets.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            if fname in meta:
                return RedirectResponse(meta[fname]["url"], status_code=302)
        except Exception:
            pass
    raise HTTPException(404, "not found")


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
        files = []
        for od in [d / "rendered", d / "out"]:
            if od.exists():
                files.extend(x for x in od.iterdir() if x.is_file() and not x.name.startswith(".") and not x.name.endswith(".part.mp4") and x.name != "remote_assets.json")
        video = next((x for x in files if x.suffix.lower() == ".mp4"), None)
        thumb = next((x for x in files if x.name.endswith(".thumbnail.jpg")), None)
        desc = next((x for x in files if x.name.endswith(".description.txt")), None)
        tit = next((x for x in files if x.name.endswith(".titles.txt")), None)
        
        video_name = video.name if video else None
        video_size = video.stat().st_size if video else 0
        built_time = video.stat().st_mtime if video else None
        stored_location = str(video.parent) if video else str(d)
        
        meta_file = d / "rendered" / "remote_assets.json"
        if not video and meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
                rem_video = next((k for k in meta.keys() if k.endswith(".mp4")), None)
                if rem_video:
                    video_name = rem_video
                    video_size = meta[rem_video].get("size", 0)
                    built_time = meta_file.stat().st_mtime
                    stored_location = "GitHub Releases (cloud)"
            except Exception:
                pass

        size = sum(x.stat().st_size for x in d.rglob("*") if x.is_file() and x.name != "remote_assets.json") + video_size
        thumb_tests = [x.name for x in files if re.search(r"\.thumbnail-[ABC]\.jpg$", x.name)]
        cards.append({
            "id": p["id"], "name": p["name"], "songs": len(p.get("tracks", [])), "links": len(p.get("links", [])),
            "minutes": round(sum(float(t.get("duration") or 0) for t in p.get("tracks", [])) / 60, 1),
            "created": p.get("created") or f.stat().st_mtime, "built": bool(video_name),
            "built_at": built_time,
            "title": tit.read_text().partition("\n\nTAGS\n")[0].strip() if tit else "",
            "video": video_name, "thumbnail": thumb.name if thumb else None,
            "description": desc.name if desc else None,
            "thumb_tests": thumb_tests, "size_mb": round(size / 1e6, 1),
            "stored_in": stored_location})
    return sorted(cards, key=lambda c: -(c["built_at"] or c["created"]))


@app.get("/api/projects/{pid}/outputs/{name}")
def download(pid: str, name: str):
    fname = Path(name).name
    f = next((x for x in pouts(pid) if x.name == fname), None)
    if f and f.exists() and f.is_file():
        return FileResponse(f, filename=f.name)
    meta_file = pdir(pid) / "rendered" / "remote_assets.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            if fname in meta:
                return RedirectResponse(meta[fname]["url"], status_code=302)
        except Exception:
            pass
    raise HTTPException(404, "not found")


@app.get("/api/jobs/{jid}")
def job(jid: str):
    if jid in JOBS:
        return JOBS[jid]
    f = DATA / "_jobs" / f"{re.sub(r'[^a-f0-9]', '', jid)}.json"      # a job of an earlier run of the server
    try:
        j = json.loads(f.read_text())
    except (OSError, ValueError):
        raise HTTPException(404, "no such job")
    if j.get("state") == "running":
        j.update(state="interrupted", message=INTERRUPTED)
    return j


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text()


# ---------- cloud: a job file you can hand to the GitHub workflow ----------
@app.get("/api/projects/{pid}/cloud-job")
def cloud_job(pid: str):
    """This playlist as a job file for `build-playlist` (GitHub Actions). The contact e-mail is left out on purpose:
    workflow inputs are visible in a public repo, so the e-mail is a repository secret instead."""
    from fastapi.responses import JSONResponse
    p = load(pid)
    if not p["links"]:
        raise HTTPException(400, "add the links first")
    keys = ("mood", "channel", "hashtags", "disc", "background", "thumbs_selected", "thumb_text", "level_audio", "level_mode", "level_pairs", "level_adjust", "youtube_title", "description_override")
    settings = {k: p[k] for k in keys if p.get(k) not in (None, "", [], {})}
    job = {"name": p["name"], "links": p["links"], "authorized": bool(p.get("rights_confirmed")), "settings": settings,
           "preview": False, "offline": False, "no_llm": False}
    slug = re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-") or "playlist"
    return JSONResponse(job, headers={"Content-Disposition": f'attachment; filename="{slug}.job.json"'})


# ---------- volume between songs ----------
class LevelSwitch(BaseModel):
    mode: str | None = None          # "off" | "whole" (every song to the same level) | "pairs" (only the boundaries you pick)
    pairs: list[int] = []            # boundary numbers: 1 = between song 1 and song 2
    adjust: dict[str, dict[str, float]] = {}      # values set by hand per boundary: {"1": {"end": -2, "start": 3}}
    on: bool | None = None           # older single switch: true means "whole"


def _ensure_loud(pid):
    """Measure every song whose loudness is missing or no longer matches its audio (after a cut). Several at once; stored per song."""
    from concurrent.futures import ThreadPoolExecutor
    p = load(pid)
    todo = [t for t in p["tracks"] if t.get("audio") and os.path.exists(t["audio"])
            and (t.get("loud") or {}).get("key") != _level.loud_key(t["audio"])]
    if todo:
        with ThreadPoolExecutor(4) as ex:
            got = dict(zip([t["audio"] for t in todo], ex.map(lambda t: _level.loudness_of({"audio": t["audio"]}), todo)))

        def store(q):
            for t in q["tracks"]:
                if t.get("audio") in got and (t.get("loud") or {}).get("key") != got[t["audio"]]["key"]:
                    t["loud"] = got[t["audio"]]
                    t["lufs"] = got[t["audio"]]["lufs"]
        p = mutate(pid, store)
    return p


def _parse_adjust(text):
    """'1:-2:3,3:0:4' -> {1: {'end': -2, 'start': 3}, 3: {...}}  (boundary : end of the first song : start of the second)"""
    out = {}
    for part in (text or "").split(","):
        bits = part.split(":")
        if len(bits) == 3:
            try:
                out[int(bits[0])] = {"end": float(bits[1]), "start": float(bits[2])}
            except ValueError:
                pass
    return out


def _level_state(p, mode, pairs, adjust=None):
    """The plan for these choices, the loudness graph after it, and the jump at every boundary before and after.
    Each boundary also says what the AUTOMATIC suggestion would be and what is applied now (by hand or automatic)."""
    tracks = p["tracks"]
    curves = [t["loud"]["db"] for t in tracks]
    pairs = [i for i in pairs if 1 <= i < len(tracks)]
    plan = _level.plan_gains([t["loud"]["lufs"] for t in tracks], curves, mode, pairs, adjust=adjust)
    after = [_level.predict(c, pl, float(t.get("duration") or len(c) * _level.WINDOW)) for c, pl, t in zip(curves, plan, tracks)]
    before_j = _level.boundary_jumps(curves)
    after_j = _level.boundary_jumps(after, fades=[j["fade"] for j in before_j] + [False])      # fade-or-not is decided on the original
    def auto(b):
        d = b["jump"]
        if d is None:
            return (0.0, 0.0)
        if b.get("fade"):
            return (0.0, _level.clamp_adjust(d))                      # a fade-out is left alone: only the next start follows the music
        return (_level.clamp_adjust(-max(-24, min(24, d)) / 2), _level.clamp_adjust(max(-24, min(24, d)) / 2))
    def residual_jump(b, a):
        if b.get("jump") is None:
            return None
        return round(b["jump"] + plan[b["i"] - 1]["end"] - plan[b["i"]]["start"], 1)

    return {"mode": mode, "pairs": pairs, "plan": plan, "after": after, "adjust": {str(k): v for k, v in (adjust or {}).items()},
            "boundaries": [{**b, "jump_after": residual_jump(b, a), "auto_end": auto(b)[0], "auto_start": auto(b)[1],
                            "end_gain": plan[b["i"] - 1]["end"], "start_gain": plan[b["i"]]["start"]} for b, a in zip(before_j, after_j)]}


@app.get("/api/projects/{pid}/loudness")
def loudness(pid: str):
    """The loudness graph of every song and the jumps between them, with what the saved settings would do. Measuring changes nothing."""
    p = _ensure_loud(pid)
    ok = [t for t in p["tracks"] if t.get("loud")]
    if len(ok) != len(p["tracks"]) or not ok:
        raise HTTPException(400, "extract the songs first")
    mode, pairs = _level.settings_of(p)
    vals = [t["loud"]["lufs"] for t in ok if t["loud"]["lufs"] is not None]
    return {"target": _level.TARGET, "window": _level.WINDOW, "hold": _level.HOLD, "ramp": _level.RAMP,
            "tracks": [{"n": i, "title": t["title"], "artist": t.get("artist", ""), "lufs": t["loud"]["lufs"],
                        "duration": float(t.get("duration") or 0)} for i, t in enumerate(p["tracks"], 1)],
            "curves": [t["loud"]["db"] for t in p["tracks"]], "spread": round(max(vals) - min(vals), 1) if vals else 0,
            **_level_state(p, mode, pairs, _level.adjust_of(p))}


@app.get("/api/projects/{pid}/loudness-plan")
def loudness_plan(pid: str, mode: str = "off", pairs: str = "", adj: str = ""):
    """What these choices would do (used while you tick boundaries, before anything is saved)."""
    if mode not in ("off", "whole", "pairs"):
        raise HTTPException(400, "mode must be off, whole or pairs")
    p = _ensure_loud(pid)
    return _level_state(p, mode, [int(x) for x in pairs.split(",") if x.strip().isdigit()], _parse_adjust(adj))


@app.get("/api/projects/{pid}/level-demo")
def level_demo(pid: str, i: int = 1, version: str = "before", lmode: str = "", pairs: str = "", adj: str = ""):
    """The end of song i then the start of song i+1: 'before' as it is, 'after' with the chosen leveling (the saved one unless lmode/pairs are given)."""
    p = _ensure_loud(pid)
    if not 1 <= i < len(p["tracks"]):
        raise HTTPException(404, "pick a song that has another song after it")
    mode, saved = _level.settings_of(p)
    hand = _level.adjust_of(p)
    if lmode:
        mode, saved, hand = lmode, [int(x) for x in pairs.split(",") if x.strip().isdigit()], _parse_adjust(adj)
    a, b = p["tracks"][i - 1], p["tracks"][i]
    neutral = {"whole": 0.0, "start": 0.0, "end": 0.0}
    if version == "after":
        st = _level_state(p, mode, saved, hand)
        pa, pb = st["plan"][i - 1], st["plan"][i]
    else:
        pa = pb = neutral
    tag = "_".join(f"{x:+.1f}" for x in (pa["whole"], pa["start"], pa["end"], pb["whole"], pb["start"], pb["end"]))
    import hashlib
    ident = hashlib.md5(f"{_level.loud_key(a['audio'])}{_level.loud_key(b['audio'])}".encode()).hexdigest()[:8]     # changes when a cut changes the audio
    f = pdir(pid) / "work" / "leveldemo" / f"{i}-{ident}-{tag}.mp3"
    if not f.exists():
        try:
            _level.demo_clip_plan(a["audio"], b["audio"], pa, pb, float(a["duration"]), float(b["duration"]), str(f))
        except RuntimeError as e:
            raise HTTPException(500, str(e))
    return FileResponse(f, media_type="audio/mpeg")


@app.put("/api/projects/{pid}/leveling")
def set_leveling(pid: str, req: LevelSwitch):
    mode = req.mode or ("whole" if req.on else "off")
    if mode not in ("off", "whole", "pairs"):
        raise HTTPException(400, "mode must be off, whole or pairs")
    pairs = sorted(set(req.pairs))
    adjust = {}
    for k, v in req.adjust.items():
        if str(k).isdigit():
            adjust[str(int(k))] = {"end": _level.clamp_adjust(v.get("end", 0.0)), "start": _level.clamp_adjust(v.get("start", 0.0))}

    def change(p):
        p["level_mode"], p["level_pairs"], p["level_audio"], p["level_adjust"] = mode, pairs, mode != "off", adjust
    mutate(pid, change)
    return {"mode": mode, "pairs": pairs, "adjust": adjust}


# ---------- thumbnails: styles to pick from ----------
class ThumbPick(BaseModel):
    selected: list[dict] = []        # up to 3 of {"family": ..., "variant": ...}


def _thumb_ctx(p):
    prof = p.get("profile") or {}
    return {"moods": [m.strip() for m in (p.get("mood") or "").split(",") if m.strip()] or prof.get("moods", []),
            "title": p.get("youtube_title") or (p.get("desc_meta") or {}).get("title", ""),
            "thumb_text": p.get("thumb_text", ""), "channel": p.get("channel") or "",
            "tracks": [t.get("title", "") for t in p.get("tracks", []) if t.get("cover")],
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


class ThumbText(BaseModel):
    text: str = ""


@app.put("/api/projects/{pid}/thumb-text")
def set_thumb_text(pid: str, req: ThumbText):
    """The words on the concept-style thumbnails (Late night, Cloud sky). Empty = Senora picks a phrase of its own from the mood."""
    text = re.sub(r"\s+", " ", req.text).strip()[:60]
    mutate(pid, lambda p: p.update(thumb_text=text))
    return {"text": text}


@app.post("/api/projects/{pid}/thumbs/build")
def build_thumbs_now(pid: str):
    """Make the picked thumbnails right now (seconds, no video needed): handy after changing the picks when a video already exists."""
    p = load(pid)
    if not p.get("thumbs_selected"):
        raise HTTPException(400, "pick at least one thumbnail first")
    if not any(t.get("cover") for t in p["tracks"]):
        raise HTTPException(400, "extract the songs first: thumbnails are made from their covers")
    out = pdir(pid) / "out"
    out.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-") or "playlist"
    minutes = sum(float(t.get("duration") or 0) for t in p["tracks"]) / 60
    files = _thumbs.write_selected(p, str(out / slug), minutes)
    return {"files": [Path(f).name for f in files]}


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


class RenameCategory(BaseModel):
    name: str


@app.put("/api/library/categories/{cid}")
def library_rename_category(cid: str, req: RenameCategory):
    try:
        LIB.rename_category(cid, req.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/library/restore")
def library_restore():
    LIB.restore_defaults()
    return {"ok": True}


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


# ---------- your own titles: add, edit, hide ----------
class TitleText(BaseModel):
    title: str


def _bank():
    try:
        return json.loads((DATA / "title_bank.json").read_text())
    except (OSError, ValueError):
        return {"custom": [], "hidden": []}


def _save_bank(b):
    f = DATA / "title_bank.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(b, indent=1, ensure_ascii=False))
    os.replace(tmp, f)


def _clean_title(t):
    t = re.sub(r"\s+", " ", t or "").strip()
    if not 3 <= len(t) <= 100:
        raise HTTPException(400, "a title needs 3 to 100 characters")
    return t


@app.get("/api/title-bank")
def title_bank():
    b = _bank()
    return {"custom": b["custom"], "hidden": len(b["hidden"])}


@app.post("/api/title-bank/custom")
def title_add(req: TitleText):
    t = _clean_title(req.title)
    b = _bank()
    b["hidden"] = [h for h in b["hidden"] if h != t.lower()]          # adding a title you hid earlier brings it back
    if not any(c["title"].lower() == t.lower() for c in b["custom"]):
        b["custom"].append({"id": uuid.uuid4().hex[:8], "title": t})
    _save_bank(b)
    return {"custom": b["custom"]}


@app.put("/api/title-bank/custom/{cid}")
def title_edit(cid: str, req: TitleText):
    t = _clean_title(req.title)
    b = _bank()
    c = next((c for c in b["custom"] if c["id"] == cid), None)
    if not c:
        raise HTTPException(404, "no such title")
    c["title"] = t
    _save_bank(b)
    return {"custom": b["custom"]}


@app.delete("/api/title-bank/custom/{cid}")
def title_delete(cid: str):
    b = _bank()
    b["custom"] = [c for c in b["custom"] if c["id"] != cid]
    _save_bank(b)
    return {"custom": b["custom"]}


@app.post("/api/title-bank/hide")
def title_hide(req: TitleText):
    """Never offer this suggested title again (your own titles are deleted instead)."""
    t = _clean_title(req.title)
    b = _bank()
    mine = next((c for c in b["custom"] if c["title"].lower() == t.lower()), None)
    if mine:
        b["custom"].remove(mine)
    elif t.lower() not in b["hidden"]:
        b["hidden"].append(t.lower())
    _save_bank(b)
    return {"custom": b["custom"], "hidden": len(b["hidden"])}


@app.post("/api/title-bank/restore")
def title_restore():
    b = _bank()
    b["hidden"] = []
    _save_bank(b)
    return {"hidden": 0}


# ---------- share with ChatGPT ----------
def _brief_inputs(pid):
    p = with_estimate(load(pid))
    proj = {**p, "title": p.get("title") or p["name"], "theme": p.get("theme") or p["name"]}
    ts = ""
    if p["tracks"] and all(t.get("duration") is not None for t in p["tracks"]):
        _, ts = _stamps.build(p["tracks"], [float(t.get("duration") or 0) for t in p["tracks"]])
    found = suggest_titles(proj, n=10, mood=p.get("mood", ""), online=False, use_llm=False, history_path=str(DATA / "titles_history.json"),
                           project_name=p["name"], record=False) if p["tracks"] else {"titles": []}
    opts = found["titles"]
    title = p.get("youtube_title") or (opts[0]["title"] if opts else publish.title_ideas(proj["theme"])[0])
    d = pdir(pid) / "out"
    built = sorted(f.name for f in d.iterdir() if f.is_file()) if d.exists() else []
    desc = publish.compose.sync_tracklist(p["description_override"], ts) if p.get("description_override") \
        else (publish.description_text(proj, title, ts, proj["theme"]) if p["tracks"] else "")
    return p, desc, title, opts, built


@app.get("/api/projects/{pid}/gpt-brief")
def gpt_brief(pid: str, question: str = ""):
    p, desc, title, opts, built = _brief_inputs(pid)
    if not p["tracks"]:
        raise HTTPException(400, "extract the songs first")
    return {"markdown": _gpt.build(p, desc, title, opts, built, question)}


@app.get("/api/projects/{pid}/gpt-brief.md")
def gpt_brief_file(pid: str, question: str = ""):
    """The same brief as a plain .md file download (to upload into ChatGPT as a file)."""
    from fastapi.responses import Response
    p, desc, title, opts, built = _brief_inputs(pid)
    if not p["tracks"]:
        raise HTTPException(400, "extract the songs first")
    return Response(_gpt.build(p, desc, title, opts, built, question).encode(), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="senora-brief.md"'})


@app.get("/api/projects/{pid}/gpt-pack.zip")
def gpt_pack(pid: str, question: str = ""):
    """brief.md + the thumbnails, the description, and the song covers. No audio, no video."""
    import io
    import zipfile
    from fastapi.responses import Response
    p, desc, title, opts, built = _brief_inputs(pid)
    if not p["tracks"]:
        raise HTTPException(400, "extract the songs first")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("brief.md", _gpt.build(p, desc, title, opts, built, question))
        out = pdir(pid) / "out"
        for name in built:
            if re.search(r"\.thumbnail.*\.jpg$", name):
                z.write(out / name, f"thumbnails/{name}")
        for i, t in enumerate(p["tracks"], 1):
            c = t.get("cover")
            if c and os.path.exists(c):
                z.write(c, f"covers/{i:02d}-{re.sub(r'[^A-Za-z0-9]+', '-', t.get('title', 'song'))[:30]}{os.path.splitext(c)[1]}")
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="senora-gpt-pack.zip"'})


# ---------- where you were ----------
class UiState(BaseModel):
    mode: str = "lib"            # "lib" (home) or "pl" (a playlist)
    pid: str = ""
    step: int = 0
    catId: str = ""
    scroll: int = 0


@app.get("/api/ui-state")
def get_ui_state():
    try:
        st = json.loads((DATA / "_ui_state.json").read_text())
    except (OSError, ValueError):
        return {}
    if st.get("mode") == "pl" and not (st.get("pid") and (DATA / st["pid"] / "project.json").exists()):
        return {"mode": "lib"}                                  # that playlist was deleted meanwhile: back to the home page
    return st


@app.put("/api/ui-state")
def put_ui_state(req: UiState):
    f = DATA / "_ui_state.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"mode": req.mode if req.mode in ("lib", "pl") else "lib", "pid": req.pid if re.fullmatch(r"[a-f0-9]{8}", req.pid or "") else "",
                               "step": max(0, min(3, req.step)), "catId": re.sub(r"[^a-z0-9-]", "", req.catId)[:80], "scroll": max(0, req.scroll)}))
    os.replace(tmp, f)
    return {"ok": True}


_recover_jobs()
try:
    from engine import procs as _procs
    _procs.orphans(str(DATA))            # ffmpeg left running by an earlier server that was killed hard: stop it
except Exception:
    pass
