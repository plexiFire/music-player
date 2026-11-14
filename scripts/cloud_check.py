"""Measures what a cloud runner can do, so you know what to expect before trusting it with real playlists.

  python scripts/cloud_check.py --minutes 3 [--url https://www.youtube.com/watch?v=jNQXAC9IVRw] [--preview]

1. YouTube from this machine: can yt-dlp read a video's details and download its audio? (Datacenter IPs are sometimes blocked.)
2. Render speed: builds a synthetic playlist of the given length at the real settings and times it, then estimates a 20-minute video.
Prints a Markdown report (also appended to $GITHUB_STEP_SUMMARY when run in GitHub Actions). Exit code 0 even when YouTube is blocked:
that is a finding, not a failure."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)


def youtube_check(url):
    rows = []
    t = time.time()
    r = subprocess.run([shutil.which("yt-dlp") or "yt-dlp", "-J", "--no-playlist", "--no-warnings", url], capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, timeout=120)
    if r.returncode == 0:
        j = json.loads(r.stdout)
        rows.append(("read video details", "OK", f"{j.get('title', '')[:40]!r} in {time.time() - t:.1f}s"))
    else:
        rows.append(("read video details", "BLOCKED", (r.stderr.strip().splitlines() or ["?"])[-1][:140]))
        return rows
    d = tempfile.mkdtemp()
    t = time.time()
    r = subprocess.run([shutil.which("yt-dlp") or "yt-dlp", "-f", "bestaudio/best", "--no-playlist", "--no-warnings", "-o", f"{d}/a.%(ext)s", url],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
    files = os.listdir(d)
    if r.returncode == 0 and files:
        rows.append(("download audio", "OK", f"{os.path.getsize(os.path.join(d, files[0])) / 1e6:.1f} MB in {time.time() - t:.1f}s"))
    else:
        rows.append(("download audio", "BLOCKED", (r.stderr.strip().splitlines() or ["?"])[-1][:140]))
    shutil.rmtree(d, ignore_errors=True)
    return rows


def render_check(minutes, preview):
    from engine import cloud
    d = tempfile.mkdtemp()
    per = max(20, int(minutes * 60 / 3))
    links = []
    for i, f in enumerate((220, 262, 330), 1):                          # three synthetic songs, so no network is needed
        p = os.path.join(d, f"song{i}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={f}:duration={per}", "-af", "volume=3", p], check=True)
        links.append(p)
    job = {"name": "Cloud check", "links": links, "authorized": True, "offline": True, "no_llm": True, "preview": preview,
           "settings": {"mood": "slow, calm", "channel": "Senora"}}
    t = time.time()
    summary = cloud.run(job, os.path.join(d, "out"), os.path.join(d, "work"))
    took = time.time() - t
    video_s = summary["duration_minutes"] * 60
    factor = took / max(1.0, video_s)
    return {"video_minutes": summary["duration_minutes"], "took_minutes": round(took / 60, 1), "factor": round(factor, 2),
            "est_20min": round(20 * factor, 1), "cpus": os.cpu_count(), "preview": preview}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=3)
    ap.add_argument("--url", default="https://www.youtube.com/watch?v=jNQXAC9IVRw")
    ap.add_argument("--preview", action="store_true", help="720p preview instead of the final 1080p")
    ap.add_argument("--skip-youtube", action="store_true")
    a = ap.parse_args()
    lines = ["## Senora cloud check", ""]
    if not a.skip_youtube:
        lines += ["### YouTube from this machine", "", "| step | result | detail |", "|---|---|---|"]
        try:
            lines += [f"| {s} | {r} | {d} |" for s, r, d in youtube_check(a.url)]
        except Exception as e:
            lines.append(f"| check | ERROR | {type(e).__name__}: {e} |")
        lines.append("")
    rc = render_check(a.minutes, a.preview)
    lines += ["### Render speed", "",
              f"- built a **{rc['video_minutes']} min** video ({'720p preview' if rc['preview'] else 'final 1080p'}) on **{rc['cpus']} CPUs** in **{rc['took_minutes']} min**",
              f"- that is **{rc['factor']}x** the video length (lower is faster)",
              f"- so a **20 min** video would take about **{rc['est_20min']} min** here (a rough guess: songs, covers and loudness change it)"]
    report = "\n".join(lines)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(report + "\n")


if __name__ == "__main__":
    main()
