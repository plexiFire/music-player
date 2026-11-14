"""Send one playlist to GitHub for rendering, and bring the finished video back. Your computer only downloads and uploads;
GitHub's machine does the heavy rendering. Nothing needs a token: the songs travel through git (the same SSH login you use to push),
and GitHub's own workflow publishes the finished video as a release, which this computer downloads without a login.

  ./start_senora send <playlist project.json>
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


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=check, capture_output=True, text=True).stdout


def build_job(project_path, job_id, dest):
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
           "tracks": tracks, "settings": {k: proj[k] for k in SETTINGS if k in proj}, "preview": False}
    (dest / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1))
    return job, len(tracks)


def wait_for_release(tag, poll=30, timeout=6 * 3600, log=print):
    url = f"https://api.github.com/repos/{OWNER_REPO}/releases/tags/{tag}"
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            req = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "senora-helper"})
            rel = json.loads(urlopen(req, timeout=30).read())
            mp4 = [a for a in rel.get("assets", []) if a["name"].endswith(".mp4")]
            if mp4:
                return mp4[0]
        except Exception:
            pass
        log(f"  rendering on GitHub... {int((time.time() - t0) / 60)} min so far")
        time.sleep(poll)
    raise SystemExit("Still not finished after a long time: check the Actions tab on GitHub.")


def download(asset, name):
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    dst = DOWNLOADS / name
    req = Request(asset["browser_download_url"], headers={"User-Agent": "senora-helper"})
    with urlopen(req, timeout=600) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    return dst


def send(project_path, log=print):
    job_id = time.strftime("%Y%m%d-%H%M%S")
    branch = f"job/{job_id}"
    folder = REPO_ROOT / "jobs" / job_id
    folder.mkdir(parents=True)
    log("1/4 copying the songs and cover pictures ...")
    job, n = build_job(project_path, job_id, folder)
    log(f"    {n} songs, {sum(t['duration'] for t in job['tracks']) / 60:.1f} minutes")
    log("2/4 sending them to GitHub ...")
    git("checkout", "-q", "-b", branch)
    git("add", str(folder.relative_to(REPO_ROOT)))
    git("commit", "-q", "-m", f"render job {job_id}")
    git("push", "-q", "origin", branch)
    git("checkout", "-q", "main")
    shutil.rmtree(folder)                                      # the copies on your computer are now the ones GitHub has
    log("3/4 GitHub renders it (you can close this window; run the same command later to pick up the video)")
    asset = wait_for_release(f"job-{job_id}", log=log)
    log("4/4 downloading the video ...")
    dst = download(asset, asset["name"])
    log(f"done: {dst}")
    return dst


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        sys.exit("Usage: start_senora send <playlist project.json>")
    send(argv[0])


if __name__ == "__main__":
    main()
