"""The Senora helper: runs on YOUR computer and fetches songs for a hosted Senora page.
It connects OUT to the page (nothing to open on your router), asks for work, downloads each song on your own connection, uploads the
files, and keeps its own local copies in ~/.senora_helper/work/<playlist> until that playlist is finished; then it deletes only those."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

import requests

HOME = Path(os.environ.get("SENORA_HELPER_HOME", Path.home() / ".senora_helper"))


def load_config():
    try:
        return json.loads((HOME / "config.json").read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    HOME.mkdir(parents=True, exist_ok=True)
    f = HOME / "config.json"
    f.write_text(json.dumps(cfg))
    os.chmod(f, 0o600)                       # the token is only for this computer


class Client:
    def __init__(self, base, token=""):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method, path, **kw):
        r = requests.request(method, self.base + path, headers={"X-Agent-Token": self.token}, timeout=60, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise RuntimeError(f"{r.status_code}: {detail}")
        return r.json()


def pair(base, code):
    c = Client(base)
    token = c.call("POST", "/api/agent/pair", json={"code": code})["token"]
    save_config({"server": base.rstrip("/"), "token": token})
    return token


def local_dir(pid):
    safe = "".join(ch for ch in pid if ch.isalnum() or ch in "-_")
    return HOME / "work" / safe


def fetch_task(c, task, importer=None):
    """Download one link here, keep the files here, upload them to the page."""
    if importer is None:
        from engine.playlist import importer
    base = local_dir(task["pid"])
    (base / "audio").mkdir(parents=True, exist_ok=True)
    (base / "work").mkdir(parents=True, exist_ok=True)
    c.call("POST", f"/api/agent/tasks/{task['id']}/progress", json={"message": "downloading on your computer"})
    tracks = importer.import_one(task["link"], str(base / "audio"), str(base / "work"), task["idx"], authorized=True, lookup=True)
    meta, files = [], []
    for t in tracks:
        m = {k: v for k, v in t.items() if k not in ("audio", "cover", "trim")}
        for field, kind in (("audio", "audio_name"), ("cover", "cover_name")):
            f = t.get(field)
            if f and os.path.isfile(f):
                m[kind] = os.path.basename(f)
                files.append(f)
        meta.append(m)
    c.call("POST", f"/api/agent/tasks/{task['id']}/progress", json={"message": "uploading"})
    handles = [open(f, "rb") for f in files]
    try:
        c.call("POST", f"/api/agent/tasks/{task['id']}/result", data={"meta": json.dumps(meta, default=str)},
               files=[("files", (os.path.basename(f), h)) for f, h in zip(files, handles)])
    finally:
        for h in handles:
            h.close()


def clean_finished(c):
    """Delete this helper's own local copies for playlists that are finished. Only folders inside ~/.senora_helper/work are touched."""
    removed = []
    for pid in c.call("GET", "/api/agent/finished")["playlists"]:
        d = local_dir(pid).resolve()
        if (HOME / "work").resolve() in d.parents and d.is_dir():
            shutil.rmtree(d)
            removed.append(pid)
    return removed


def run(c, once=False, poll=3, importer=None, log=print):
    last_clean = 0.0
    while True:
        try:
            task = c.call("GET", "/api/agent/next")["task"]
            if task:
                log(f"fetching {task['link']}")
                try:
                    fetch_task(c, task, importer)
                    log("  done")
                except Exception as e:
                    log(f"  failed: {e}")
                    c.call("POST", f"/api/agent/tasks/{task['id']}/fail", json={"error": str(e)})
            if time.time() - last_clean > 30:
                last_clean = time.time()
                for pid in clean_finished(c):
                    log(f"finished playlist {pid}: removed my local copies")
        except requests.RequestException as e:
            log(f"cannot reach the page ({e}); trying again")
        except RuntimeError as e:
            log(str(e))
            if str(e).startswith("401"):
                sys.exit("This computer is no longer connected. Pair it again: start_senora helper <page address>")
        if once:
            return
        time.sleep(poll)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="start_senora helper", description="Fetch songs for a hosted Senora page, on this computer.")
    ap.add_argument("server", nargs="?", help="the page address, e.g. https://your-senora.example (not needed after the first time)")
    ap.add_argument("--code", help="the one-time code shown by the page (asked for if missing)")
    a = ap.parse_args(argv)
    cfg = load_config()
    server = (a.server or cfg.get("server") or "").rstrip("/")
    if not server:
        sys.exit("Give the page address once:  start_senora helper https://your-senora.example")
    if not cfg.get("token") or cfg.get("server") != server or a.code:
        code = a.code or input("Code shown on the page (press Connect my computer): ")
        pair(server, code)
        print("Connected.")
        cfg = load_config()
    print(f"Helper running for {server}. It works only when a song has to be fetched. Press Ctrl+C to stop.")
    try:
        run(Client(server, cfg["token"]))
    except KeyboardInterrupt:
        print("Stopped.")
