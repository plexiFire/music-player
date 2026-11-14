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
from engine.publish import gpt_brief as _gpt, thumbs as _thumbs  # noqa: E402
from engine.titles import profile as _profile  # noqa: E402
from engine.sources import metadata as _metadata, musicbrainz as _mb  # noqa: E402
from server.library import Library  # noqa: E402
from server import reconcile as _rec  # noqa: E402
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


_MUTATE = threading.RLock()


def mutate(pid, fn):
    """Read-change-write of a project as ONE step, so two things happening at once (an extraction finishing a song while you edit
    the links) can never overwrite each other. fn(p) changes p in place; if it raises, nothing is saved."""
    with _MUTATE:
        p = load(pid)
        fn(p)
        save(pid, p)
        return p


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


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    try:
        _repair_old_cuts(pid)
    except Exception:
        pass                                   # never stop a project from opening because a repair failed
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
    desc = p.get("description_override") or publish.description_text(proj, chosen, ts, theme, use_llm=req.use_llm)
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


def _extract(jid, pid):
    """Extract only what is missing. Every finished song is saved at once and merged with the CURRENT links, so you can go back,
    add / remove / reorder links while this runs: nothing done is lost, nothing removed comes back."""
    d = pdir(pid)
    p = load(pid)
    todo = _rec.todo(p["links"], p["tracks"])
    n = len(todo)
    for i, link in enumerate(todo, 1):
        cur = load(pid)
        if _rec.link_key(link) not in {_rec.link_key(l) for l in cur["links"]}:
            continue                                              # you removed this link meanwhile: skip it
        set_job(jid, message=f"track {i}/{n}")
        idx = max(cur.get("next_index", 0), len(cur["tracks"]) + 1)
        try:
            got = importer.import_one(link, str(d / "audio"), str(d / "work"), idx, authorized=True, lookup=True)
            for t in got:
                t["from_link"] = link
        except Exception as e:
            got = [{"title": link, "artist": "", "audio": None, "cover": None, "error": str(e), "from_link": link,
                    "source_link": link, "audio_source": f"link: {link}", "image_source": "none"}]

        def merge(p, got=got, link=link, idx=idx):
            if _rec.link_key(link) not in {_rec.link_key(l) for l in p["links"]}:
                return                                            # removed while it was downloading: its files stay, nothing is added
            k = _rec.link_key(link)
            p["tracks"] = [t for t in p["tracks"] if not (_rec.track_key(t) == k and not _usable(t))]   # a retry replaces the failure
            p["tracks"] += got
            p["tracks"], _ = _rec.reconcile(p["links"], p["tracks"])
            p["next_index"] = idx + len(got)
            p.pop("description_override", None)

        mutate(pid, merge)

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


@app.get("/api/projects/{pid}/active-job")
def active_job(pid: str):
    """The extraction or build that is running for this playlist right now (so the page can pick it up after you went back and forth)."""
    pdir(pid)
    with LOCK:
        j = next((dict(j) for j in JOBS.values() if j["project"] == pid and j["state"] == "running"), None)
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
    out = audio.process(src, str(d), name=f"track{n:02d}_trimmed", fmt="mp3", start=start, end=end)
    new_dur = audio.probe(out)["duration"]
    box = {}

    def apply(q):
        tt = next((x for x in q["tracks"] if x.get("audio") == before_audio), None)
        if tt is None:
            raise HTTPException(409, "the playlist changed while cutting: try again")
        tt.setdefault("audio_original", src)
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


@app.post("/api/projects/{pid}/build")
def build(pid: str, req: BuildReq):
    p = load(pid)
    if not p["tracks"] or any(not t.get("audio") for t in p["tracks"]):
        raise HTTPException(400, "extract every track first")
    todo = _rec.todo(p["links"], p["tracks"])
    if todo:
        raise HTTPException(400, f"{len(todo)} link(s) are not extracted yet: extract them, or remove them from the links")
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


# ---------- cloud: a job file you can hand to the GitHub workflow ----------
@app.get("/api/projects/{pid}/cloud-job")
def cloud_job(pid: str):
    """This playlist as a job file for `build-playlist` (GitHub Actions). The contact e-mail is left out on purpose:
    workflow inputs are visible in a public repo, so the e-mail is a repository secret instead."""
    from fastapi.responses import JSONResponse
    p = load(pid)
    if not p["links"]:
        raise HTTPException(400, "add the links first")
    keys = ("mood", "channel", "hashtags", "disc", "background", "thumbs_selected", "level_audio", "level_mode", "level_pairs", "youtube_title", "description_override")
    settings = {k: p[k] for k in keys if p.get(k) not in (None, "", [], {})}
    job = {"name": p["name"], "links": p["links"], "authorized": bool(p.get("rights_confirmed")), "settings": settings,
           "preview": False, "offline": False, "no_llm": False}
    slug = re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-") or "playlist"
    return JSONResponse(job, headers={"Content-Disposition": f'attachment; filename="{slug}.job.json"'})


# ---------- volume between songs ----------
class LevelSwitch(BaseModel):
    mode: str | None = None          # "off" | "whole" (every song to the same level) | "pairs" (only the boundaries you pick)
    pairs: list[int] = []            # boundary numbers: 1 = between song 1 and song 2
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


def _level_state(p, mode, pairs):
    """The plan for these choices, the loudness graph after it, and the jump at every boundary before and after."""
    tracks = p["tracks"]
    curves = [t["loud"]["db"] for t in tracks]
    pairs = [i for i in pairs if 1 <= i < len(tracks)]
    plan = _level.plan_gains([t["loud"]["lufs"] for t in tracks], curves, mode, pairs)
    after = [_level.predict(c, pl, float(t.get("duration") or len(c) * _level.WINDOW)) for c, pl, t in zip(curves, plan, tracks)]
    before_j, after_j = _level.boundary_jumps(curves), _level.boundary_jumps(after)
    return {"mode": mode, "pairs": pairs, "plan": plan, "after": after,
            "boundaries": [{**b, "jump_after": a["jump"]} for b, a in zip(before_j, after_j)]}


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
            **_level_state(p, mode, pairs)}


@app.get("/api/projects/{pid}/loudness-plan")
def loudness_plan(pid: str, mode: str = "off", pairs: str = ""):
    """What these choices would do (used while you tick boundaries, before anything is saved)."""
    if mode not in ("off", "whole", "pairs"):
        raise HTTPException(400, "mode must be off, whole or pairs")
    p = _ensure_loud(pid)
    return _level_state(p, mode, [int(x) for x in pairs.split(",") if x.strip().isdigit()])


@app.get("/api/projects/{pid}/level-demo")
def level_demo(pid: str, i: int = 1, version: str = "before", lmode: str = "", pairs: str = ""):
    """The end of song i then the start of song i+1: 'before' as it is, 'after' with the chosen leveling (the saved one unless lmode/pairs are given)."""
    p = _ensure_loud(pid)
    if not 1 <= i < len(p["tracks"]):
        raise HTTPException(404, "pick a song that has another song after it")
    mode, saved = _level.settings_of(p)
    if lmode:
        mode, saved = lmode, [int(x) for x in pairs.split(",") if x.strip().isdigit()]
    a, b = p["tracks"][i - 1], p["tracks"][i]
    neutral = {"whole": 0.0, "start": 0.0, "end": 0.0}
    if version == "after":
        st = _level_state(p, mode, saved)
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

    def change(p):
        p["level_mode"], p["level_pairs"], p["level_audio"] = mode, pairs, mode != "off"
    mutate(pid, change)
    return {"mode": mode, "pairs": pairs}


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


# ---------- your own titles: add, edit, hide ----------
class TitleText(BaseModel):
    title: str


def _bank():
    try:
        return json.loads((DATA / "title_bank.json").read_text())
    except (OSError, ValueError):
        return {"custom": [], "hidden": []}


def _save_bank(b):
    (DATA / "title_bank.json").write_text(json.dumps(b, indent=1, ensure_ascii=False))


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
    desc = p.get("description_override") or (publish.description_text(proj, title, ts, proj["theme"]) if p["tracks"] else "")
    return p, desc, title, opts, built


@app.get("/api/projects/{pid}/gpt-brief")
def gpt_brief(pid: str, question: str = ""):
    p, desc, title, opts, built = _brief_inputs(pid)
    if not p["tracks"]:
        raise HTTPException(400, "extract the songs first")
    return {"markdown": _gpt.build(p, desc, title, opts, built, question)}


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
