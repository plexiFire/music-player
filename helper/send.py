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


def build_job(project_path, job_id, dest, preview=False, no_llm=False):
    proj = json.loads(Path(project_path).read_text())
    tracks = []
    for i, t in enumerate(proj["tracks"], 1):
        if not (t.get("audio") and t.get("cover")) or t.get("error"):
            continue
        a, c = Path(t["audio"]), Path(t["cover"])
        if not (a.is_file() and c.is_file()):
            continue
        an, cn = f"song{i:02d}{a.suffix}", f"cover{i:02d}{c.suffix}"
        shutil.copy(a, dest / an)
        shutil.copy(c, dest / cn)
        tracks.append({"title": t.get("title", ""), "artist": t.get("artist", ""), "duration": t.get("duration") or 0,
                       "audio": an, "cover": cn})                 # relative to the job file's own folder
    if not tracks:
        sys.exit("No finished songs in this playlist: extract it first.")
    job = {"name": proj.get("name") or proj.get("title") or "Playlist", "authorized": True, "links": [],
           "tracks": tracks, "settings": {k: proj[k] for k in SETTINGS if k in proj}, "preview": bool(preview), "no_llm": bool(no_llm)}
    (dest / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1))
    return job, len(tracks)


def wait_for_release(tag, poll=30, timeout=6 * 3600, log=print):
    """Returns all the release's files once the video is among them."""
    url = f"https://api.github.com/repos/{OWNER_REPO}/releases/tags/{tag}"
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
            req = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "senora-helper"})
            rel = json.loads(urlopen(req, timeout=30).read())
            assets = rel.get("assets", [])
            if any(a["name"].endswith(".mp4") for a in assets):
                return assets
        except Exception:
            pass
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
    """Stop the GitHub render of this job: cancel its run and remove its branch, so nothing keeps running or is left behind."""
    branch = f"job/{job_id}"
    try:
        for r in render_runs(("queued", "in_progress")):
            if r.get("head_branch") == branch:
                gh_api("POST", f"/actions/runs/{r['id']}/cancel")
                log("GitHub render cancelled")
        gh_api("DELETE", f"/git/refs/heads/{branch}")
    except Exception as e:                                       # a missing token or a network error must not hide the stop
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
    req = Request(asset["browser_download_url"], headers={"User-Agent": "senora-helper"})
    with urlopen(req, timeout=600) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    return dst


def send(project_path, dest_dir=None, log=print, preview=False, no_llm=False):
    """Songs go by git into a short-lived copy of the repo (this computer's own folder does not need to be a git folder)."""
    import tempfile
    job_id = time.strftime("%Y%m%d-%H%M%S")
    branch = f"job/{job_id}"
    check_one_at_a_time(log)
    tmp = Path(tempfile.mkdtemp(prefix="senora-job-"))
    try:
        log("getting the latest code from GitHub ...")
        repo = tmp / "repo"
        git("clone", "-q", "--depth", "1", "--branch", "main", remote_url(), str(repo))
        folder = repo / "jobs" / job_id
        folder.mkdir(parents=True)
        log("copying the songs and cover pictures ...")
        job, n = build_job(project_path, job_id, folder, preview, no_llm)
        log(f"{n} songs, {sum(t['duration'] for t in job['tracks']) / 60:.1f} minutes: sending them to GitHub ...")
        git("checkout", "-q", "-b", branch, cwd=repo)
        git("add", "-f", f"jobs/{job_id}", cwd=repo)                  # -f: a folder of songs must go in even if some rule ignores it
        git("commit", "-q", "-m", f"render job {job_id}", cwd=repo)
        git("push", "-q", "origin", branch, cwd=repo)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)                 # the temporary copy and the song files in it are gone
    log("GitHub is rendering it (this takes a while)")
    assets = wait_for_release(f"job-{job_id}", log=log)
    dest = Path(dest_dir) if dest_dir else DOWNLOADS / job_id
    log("downloading the video, thumbnail and text ...")
    for a in assets:
        download(a, dest / a["name"])
    log(f"done: {dest}")
    return dest


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        sys.exit("Usage: start_senora send <playlist project.json>")
    send(argv[0], argv[1] if len(argv) > 1 else None)


if __name__ == "__main__":
    main()
