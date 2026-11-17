"""Send one playlist to GitHub for rendering, and bring the finished video back. Your computer only downloads and uploads;
GitHub's machine does the heavy rendering. Nothing needs a token: the songs travel through git (the same SSH login you use to push),
and GitHub's own workflow publishes the finished video as a release, which this computer downloads without a login.

  ./start_senora send <playlist project.json> [folder for the files]
"""
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
OWNER_REPO = os.environ.get("SENORA_REPO", "plexiFire/music-player")
DOWNLOADS = Path(os.environ.get("SENORA_VIDEOS", Path.home() / "Movies" / "Senora"))
SETTINGS = ("mood", "channel", "hashtags", "disc", "background", "watermark", "thumbs_selected", "thumb_text", "level_audio", "level_mode",
            "level_pairs", "level_adjust", "youtube_title", "description_override", "stars", "spin_secs")


def git(*args, cwd=None):
    r = subprocess.run(["git", "-c", "user.name=senora-helper", "-c", "user.email=senora-helper@users.noreply.github.com", *args],
                       cwd=cwd, capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if r.returncode:
        raise RuntimeError(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def remote_url():
    """Where the repo lives: SENORA_GIT_REMOTE, else the address saved at install time, else this folder's own `origin`."""
    if os.environ.get("SENORA_GIT_REMOTE"):
        return os.environ["SENORA_GIT_REMOTE"]
    f = REPO_ROOT / ".senora_remote"
    if f.is_file():
        return f.read_text().strip()
    try:
        return git("remote", "get-url", "origin", cwd=REPO_ROOT).strip()
    except RuntimeError:
        raise RuntimeError("do not know where to send the songs: run  ./start_senora install-helper  once, from the Senora folder")


def _prep_cover(src: Path, dst_dir: Path, idx: int) -> str:
    """Copy cover into job folder; downscale >200 KB PNGs to crisp 800x800 Q92 JPEG (~15x smaller upload, zero visual loss)."""
    if src.stat().st_size > 200_000:
        try:
            from PIL import Image
            cn = f"cover{idx:02d}.jpg"
            im = Image.open(src).convert("RGB")
            im.thumbnail((800, 800), Image.Resampling.LANCZOS)
            im.save(dst_dir / cn, "JPEG", quality=92, optimize=True)
            return cn
        except Exception:
            pass
    cn = f"cover{idx:02d}{src.suffix}"
    shutil.copy(src, dst_dir / cn)
    return cn


def _prep_audio(src: Path, dst_dir: Path, idx: int) -> str:
    """Copy audio into job folder untouched (zero extra lossy re-encoding)."""
    an = f"song{idx:02d}{src.suffix}"
    shutil.copy(src, dst_dir / an)
    return an


def build_job(project_path, job_id, dest, preview=False, no_llm=False):
    proj = json.loads(Path(project_path).read_text())
    valid = []
    for i, t in enumerate(proj["tracks"], 1):
        if not (t.get("audio") and t.get("cover")) or t.get("error"):
            continue
        a, c = Path(t["audio"]), Path(t["cover"])
        if not (a.is_file() and c.is_file()):
            continue
        valid.append((i, t, a, c))
    if not valid:
        sys.exit("No finished songs in this playlist: extract it first.")

    def _work(item):
        i, t, a, c = item
        an = _prep_audio(a, dest, i)
        cn = _prep_cover(c, dest, i)
        return {"title": t.get("title", ""), "artist": t.get("artist", ""), "duration": t.get("duration") or 0,
                "audio": an, "cover": cn}

    with ThreadPoolExecutor(max_workers=min(4, len(valid))) as pool:
        tracks = list(pool.map(_work, valid))

    job = {"name": proj.get("name") or proj.get("title") or "Playlist", "authorized": True, "links": [],
           "tracks": tracks, "settings": {k: proj[k] for k in SETTINGS if k in proj}, "preview": bool(preview), "no_llm": bool(no_llm)}
    (dest / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1))
    return job, len(tracks)


def _iso_to_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def github_run_stage(send_tag):
    """Query GitHub Actions API for the real status & active step of this render run."""
    try:
        runs = gh_api("GET", f"/actions/workflows/render-job.yml/runs?branch={send_tag}&per_page=1").get("workflow_runs", [])
        if not runs:
            return {"phase": "setup", "pct": 21, "detail": "GitHub Actions: waiting for workflow to start..."}
        r = runs[0]
        st = r.get("status")
        concl = r.get("conclusion")
        if st == "completed" and concl in ("failure", "cancelled", "timed_out"):
            return {"phase": "failed", "detail": f"GitHub Actions render {concl}. Check Actions tab."}
        if st == "queued":
            return {"phase": "setup", "pct": 22, "detail": "GitHub Actions: queued (waiting for runner)..."}
        if st == "in_progress":
            jobs = gh_api("GET", f"/actions/runs/{r['id']}/jobs").get("jobs", [])
            if jobs:
                steps = jobs[0].get("steps", [])
                active = next((s for s in steps if s.get("status") == "in_progress"), None)
                if active:
                    name = active.get("name") or ""
                    low = name.lower()
                    if "publish" in low:
                        return {"phase": "publish", "pct": 94, "detail": "GitHub Actions: publishing finished video release..."}
                    if "render" in low:
                        rs = _iso_to_ts(active.get("started_at"))
                        mins = int(max(0, time.time() - rs) / 60) if rs else 0
                        return {"phase": "render", "render_started": rs, "detail": f"GitHub Actions: rendering video ({mins} min elapsed)..."}
                    return {"phase": "setup", "pct": 26, "detail": f"GitHub Actions: {name}..."}
        return {"phase": "setup", "pct": 24, "detail": "GitHub Actions: starting runner..."}
    except Exception:
        return None


def wait_for_release(tag, poll=10, timeout=6 * 3600, log=print, on_stage=None):
    """Returns all the release's files once the video is among them."""
    url = f"https://api.github.com/repos/{OWNER_REPO}/releases/tags/{tag}"
    send_tag = tag.replace("job-", "send-") if tag.startswith("job-") else ""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            from engine import procs
            procs.check()                                       # you pressed Stop (or the helper is off): stop GitHub's render too
        except ImportError:
            pass
        except procs.Cancelled:
            cancel_render(tag.replace("job-", ""), log)
            raise
        try:
            headers = {"Accept": "application/vnd.github+json", "User-Agent": "senora-helper"}
            if _token():
                headers["Authorization"] = f"Bearer {_token()}"
            req = Request(url, headers=headers)
            rel = json.loads(urlopen(req, timeout=30).read())
            assets = rel.get("assets", [])
            if any(a["name"].endswith(".mp4") for a in assets):
                return assets
        except Exception:
            pass
        st_info = github_run_stage(send_tag) if send_tag else None
        if st_info:
            if st_info.get("phase") == "failed":
                raise RuntimeError(st_info["detail"])
            if on_stage:
                kw = {"phase": st_info["phase"]}
                if "pct" in st_info:
                    kw["pct"] = st_info["pct"]
                if st_info.get("render_started"):
                    kw["render_started"] = st_info["render_started"]
                on_stage(**kw)
            log(st_info["detail"])
        else:
            log(f"rendering on GitHub... {int((time.time() - t0) / 60)} min so far")
        for _ in range(int(poll)):                              # wait in small steps so Stop answers quickly
            time.sleep(1)
            try:
                from engine import procs
                procs.check()
            except ImportError:
                pass
            except procs.Cancelled:
                cancel_render(tag.replace("job-", ""), log)
                raise
    raise SystemExit("Still not finished after a long time: check the Actions tab on GitHub.")


TOKEN_FILE = Path.home() / ".senora_helper" / "github_token"


def _token():
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError:
        return ""


def gh_api(method, path, body=None):
    """A call to GitHub's API. The token is only sent to GitHub, and is never printed."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "senora-helper", "X-GitHub-Api-Version": "2022-11-28"}
    if _token():
        headers["Authorization"] = f"Bearer {_token()}"
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    req = Request(f"https://api.github.com/repos/{OWNER_REPO}{path}", data=data, method=method, headers=headers)
    with urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def render_runs(statuses=("queued", "in_progress")):
    """The render runs on GitHub that are waiting or working right now."""
    out = []
    for st in statuses:
        out += gh_api("GET", f"/actions/workflows/render-job.yml/runs?status={st}&per_page=20").get("workflow_runs", [])
    return out


def cancel_render(job_id, log=print):
    """Stop the GitHub render of this job: cancel its run and remove its tag, so nothing keeps running or is left behind."""
    tag = f"send-{job_id}"
    try:
        for r in render_runs(("queued", "in_progress")):
            if r.get("head_branch") == tag:
                gh_api("POST", f"/actions/runs/{r['id']}/cancel")
                log("GitHub render cancelled")
        gh_api("DELETE", f"/git/refs/tags/{tag}")
        try:
            git("push", "origin", "--delete", tag, cwd=REPO_ROOT)
        except Exception:
            pass
    except Exception as e:                                       # a missing token or a network error must not hide the stop
        log(f"could not cancel on GitHub ({e.__class__.__name__}): cancel it in the Actions tab")


def cancel_all_renders(log=print):
    """Stop EVERY render of ours that is waiting or working on GitHub (only one is allowed at a time anyway). Used by Stop."""
    try:
        for r in render_runs(("queued", "in_progress")):
            tag = r.get("head_branch") or ""
            if tag.startswith("send-"):
                gh_api("POST", f"/actions/runs/{r['id']}/cancel")
                gh_api("DELETE", f"/git/refs/tags/{tag}")
                try:
                    git("push", "origin", "--delete", tag, cwd=REPO_ROOT)
                except Exception:
                    pass
                log(f"GitHub render {tag} cancelled")
    except Exception as e:
        log(f"could not cancel on GitHub ({e.__class__.__name__}): cancel it in the Actions tab")


def check_one_at_a_time(log=print):
    """Only one render at a time: a new one waits here if another is still running on GitHub."""
    try:
        busy = render_runs()
    except Exception:
        return                                                  # cannot ask GitHub right now: the local check still applies
    if busy:
        raise RuntimeError("another render is still running on GitHub: wait for it to finish or press Stop on it first")


def download(asset, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "senora-helper"}
    if _token():
        headers["Authorization"] = f"Bearer {_token()}"
    req = Request(asset["browser_download_url"], headers=headers)
    with urlopen(req, timeout=600) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    return dst


def send(project_path, dest_dir=None, log=print, preview=False, no_llm=False, job_id=None, on_stage=None):
    """Songs go by git into a short-lived copy of the repo (this computer's own folder does not need to be a git folder)."""
    import tempfile
    job_id = job_id or time.strftime("%Y%m%d-%H%M%S")
    tag = f"send-{job_id}"                                  # a tag, not a branch: GitHub shows a pull-request banner for every new branch
    check_one_at_a_time(log)
    stage = on_stage or (lambda **kw: None)
    tmp = Path(tempfile.mkdtemp(prefix="senora-job-"))
    try:
        stage(phase="upload", pct=4)
        log("getting the latest code from GitHub ...")
        repo = tmp / "repo"
        git("clone", "-q", "--depth", "1", "--single-branch", "--branch", "main", remote_url(), str(repo))
        folder = repo / "jobs" / job_id
        folder.mkdir(parents=True)
        stage(phase="upload", pct=9)
        log("optimizing and copying songs & covers ...")
        job, n = build_job(project_path, job_id, folder, preview, no_llm)
        total_mb = sum(f.stat().st_size for f in folder.iterdir() if f.is_file()) / (1024 * 1024)
        stage(phase="upload", pct=13)
        log(f"{n} songs, {sum(t['duration'] for t in job['tracks']) / 60:.1f} min ({total_mb:.1f} MB): uploading to GitHub ...")
        git("add", "-f", f"jobs/{job_id}", cwd=repo)                  # -f: a folder of songs must go in even if some rule ignores it
        staged = set(git("diff", "--cached", "--name-only", cwd=repo).split())
        missing = [f for t in job["tracks"] for f in (t["audio"], t["cover"]) if f"jobs/{job_id}/{f}" not in staged]
        if missing:                                              # a rule like *.mp3 in .gitignore must never drop songs without a word
            raise RuntimeError(f"git did not take these files: {', '.join(missing[:4])}. Nothing was sent.")
        git("commit", "-q", "-m", f"render job {job_id}", cwd=repo)
        # Skip zlib compression & delta search on already-compressed MP3/JPG media for much faster git push
        git("-c", "pack.compression=0", "-c", "pack.window=0", "push", "-q", "origin", f"HEAD:refs/tags/{tag}", cwd=repo)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)                 # the temporary copy and the song files in it are gone
    stage(phase="setup", pct=20)
    log("Upload complete! Waiting for GitHub Actions runner ...")
    assets = wait_for_release(f"job-{job_id}", log=log, on_stage=stage)
    dest = Path(dest_dir) if dest_dir else DOWNLOADS / job_id
    dest.mkdir(parents=True, exist_ok=True)
    stage(phase="publish", pct=96)
    log("saving metadata and thumbnails (video stays in GitHub cloud) ...")
    remote_meta = {}
    for a in assets:
        remote_meta[a["name"]] = {"url": a.get("browser_download_url", ""), "size": a.get("size", 0), "tag": f"job-{job_id}"}
        if not a["name"].endswith(".mp4"):
            download(a, dest / a["name"])
    (dest / "remote_assets.json").write_text(json.dumps(remote_meta, indent=2))
    log(f"done: {dest}")
    return dest


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        sys.exit("Usage: start_senora send <playlist project.json>")
    send(argv[0], argv[1] if len(argv) > 1 else None)


if __name__ == "__main__":
    main()
