"""The 'local helper': this computer fetching songs from YouTube for a playlist. It is switched on or off from the page, works only
while a fetch is needed, and keeps a list of exactly which files it downloaded so that cleaning up can never touch anything else."""
import json
import os
from pathlib import Path


class Helper:
    def __init__(self, path):
        self.path = Path(path)

    def is_on(self):
        try:
            return bool(json.loads(self.path.read_text()).get("on", True))
        except (OSError, ValueError):
            return True                                   # on by default when Senora runs on your own computer

    def set(self, on):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"on": bool(on)}))
        os.replace(tmp, self.path)


def files_of(tracks):
    """The audio and cover files of freshly fetched tracks (what the helper downloaded)."""
    out = []
    for t in tracks:
        for k in ("audio", "cover"):
            if t.get(k):
                out.append(t[k])
    return out


def cleanup(project_dir, project):
    """Remove the local copies the helper downloaded, but only for songs the cloud has confirmed (track['uploaded'] is true), and only
    files that are in the helper's own list and inside this playlist's folder. Returns the files removed.
    Nothing is removed when nothing was confirmed uploaded, so a playlist that lives only on this computer is never emptied."""
    root = Path(project_dir).resolve()
    confirmed = {t.get("audio") for t in project.get("tracks", []) if t.get("uploaded")}
    confirmed |= {t.get("cover") for t in project.get("tracks", []) if t.get("uploaded")}
    removed = []
    for f in project.get("downloaded", []):
        if f not in confirmed:
            continue
        p = Path(f).resolve()
        if root in p.parents and p.is_file():
            p.unlink()
            removed.append(str(p))
    return removed
