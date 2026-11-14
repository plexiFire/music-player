"""Headless build for the cloud (GitHub Actions or any Linux box): one job file in, finished files out.

job.json (made by the UI's "Download job file for cloud build", or written by hand):
{
  "name": "My playlist",
  "links": ["https://youtu.be/...", "..."],              # in play order (YouTube links or local audio files)
  "authorized": true,                                     # you confirm you own / are licensed to use these songs (required)
  "settings": {"mood": "", "channel": "Senora", "disc": "vinyl", "background": {"mode": "cover"},
               "thumbs_selected": [{"family": "night", "variant": "blue"}], "level_audio": false, "youtube_title": "",
               "description_override": ""},
  "preview": false, "offline": false, "no_llm": false
}
The contact e-mail is NOT part of the job (public repos show job inputs): it comes from the SENORA_CONTACT_EMAIL environment
variable / secret. The Groq key comes from GROQ_API_KEY. Outputs land in --out: <name>.mp4, .thumbnail*.jpg, .description.txt,
.titles.txt and summary.json."""
import argparse
import json
import os
import re
import sys

from .playlist import importer
from .sources import musicbrainz, ytdlp

SETTING_KEYS = ("mood", "channel", "hashtags", "disc", "background", "watermark", "thumbs_selected", "level_audio",
                "youtube_title", "description_override", "stars", "spin_secs")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "playlist"


def validate(job):
    """Plain-words problems with a job file, [] if it is fine."""
    problems = []
    if not job.get("links"):
        problems.append("the job has no links")
    if job.get("authorized") is not True:
        problems.append('set "authorized": true to confirm you own or are licensed to use these songs')
    if len(job.get("links", [])) > 40:
        problems.append("more than 40 links: split it into several jobs")
    return problems


def run(job, out_dir, workdir=None):
    """Import every link, apply the settings, build. Returns the summary dict (also written to out_dir/summary.json)."""
    from . import cli
    from .titles import profile as prof

    problems = validate(job)
    if problems:
        raise SystemExit("Job refused: " + "; ".join(problems))
    name = job.get("name") or "Playlist"
    out_dir = os.path.abspath(out_dir)
    work = os.path.abspath(workdir or os.path.join(out_dir, "_work"))
    os.makedirs(out_dir, exist_ok=True)
    audio_dir, cover_dir = os.path.join(work, "audio"), os.path.join(work, "covers")
    project_path = os.path.join(work, "project.json")
    offline = bool(job.get("offline"))

    tracks, skipped = [], []
    for link in job["links"]:
        try:
            got = importer.import_one(link, audio_dir, cover_dir, len(tracks) + 1, "mp3", False, True, not offline, None, None,
                                      trim=False, cover=None)
        except (ytdlp.NotAuthorized, RuntimeError, ValueError) as e:
            skipped.append({"link": link, "error": str(e).splitlines()[-1][:200]})
            print(f"SKIPPED {link}: {e}", file=sys.stderr)
            continue
        tracks += got
    tracks = [t for t in tracks if t.get("audio") and t.get("cover")]
    if not tracks:
        raise SystemExit("No song could be imported: " + json.dumps(skipped))
    if not offline:
        try:
            musicbrainz.fix_artists(tracks)
        except Exception:
            pass
    importer.add_to_project(project_path, tracks, title=name)
    project = json.load(open(project_path))
    project.update({"name": name, "title": name, "theme": name, "rights_confirmed": True})
    for k in SETTING_KEYS:
        if k in (job.get("settings") or {}):
            project[k] = job["settings"][k]
    project["contact_email"] = os.environ.get("SENORA_CONTACT_EMAIL", "")
    project["channel"] = project.get("channel") or "Senora"
    if not project.get("mood") and not offline:
        try:
            project["profile"] = prof.build(project["tracks"], online=True, use_llm=not job.get("no_llm"))
        except Exception as e:
            print(f"NOTE: genre/mood detection skipped ({type(e).__name__})", file=sys.stderr)
    json.dump(project, open(project_path, "w"), indent=1, ensure_ascii=False)

    out_video = os.path.join(out_dir, f"{slug(name)}.mp4")
    ns = argparse.Namespace(project=project_path, out=out_video, preview=bool(job.get("preview")), offline=offline,
                            no_llm=bool(job.get("no_llm")))
    cli.cmd_build(ns)

    stem = os.path.splitext(out_video)[0]
    files = sorted(f for f in os.listdir(out_dir) if f.startswith(os.path.basename(stem)))
    title = open(stem + ".titles.txt").read().strip().splitlines()[0]
    summary = {"name": name, "title": title, "songs": [{"title": t["title"], "artist": t.get("artist", "")} for t in project["tracks"]],
               "skipped": skipped, "files": files, "duration_minutes": round(sum(t.get("duration") or 0 for t in project["tracks"]) / 60, 1)}
    json.dump(summary, open(os.path.join(out_dir, "summary.json"), "w"), indent=1, ensure_ascii=False)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(prog="senora-cloud")
    ap.add_argument("job", help="job.json")
    ap.add_argument("--out", default="out", help="folder for the finished files")
    ap.add_argument("--work", help="scratch folder (default: <out>/_work)")
    a = ap.parse_args(argv)
    s = run(json.load(open(a.job)), a.out, a.work)
    print(json.dumps({k: s[k] for k in ("title", "duration_minutes", "files")}, indent=1))


if __name__ == "__main__":
    main()
