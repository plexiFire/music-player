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


def parse_url(u):
    """senora-helper://connect?server=https://page&code=ABC123  ->  (server, code). Anything else is refused."""
    from urllib.parse import parse_qs, urlparse
    p = urlparse(u)
    q = parse_qs(p.query)
    server = (q.get("server") or [""])[0].rstrip("/")
    code = (q.get("code") or [""])[0]
    if p.scheme != "senora-helper" or p.netloc != "connect" or not server.startswith(("http://", "https://")):
        raise ValueError("this is not a Senora connect link")
    return server, code


def confirm_server(server):
    """Ask on this computer before connecting to a page it has not met: a web page must not be able to point the helper at any server."""
    import subprocess
    msg = f"Let this computer fetch songs for the Senora page at:\n\n{server}\n\nOnly connect if this is YOUR page."
    r = subprocess.run(["osascript", "-e", f'display dialog {json.dumps(msg)} buttons {{"Cancel", "Connect"}} default button "Cancel" with title "Senora Helper"'],
                       capture_output=True, text=True)
    return r.returncode == 0 and "Connect" in r.stdout


def run(c, once=False, poll=3, importer=None, log=print, idle_exit=None):
    last_clean = 0.0
    last_work = time.time()
    while True:
        if idle_exit and time.time() - last_work > idle_exit:
            log("nothing to fetch for a while: the helper stops now (press Connect my computer on the page to start it again)")
            return
        try:
            task = c.call("GET", "/api/agent/next")["task"]
            if task:
                last_work = time.time()
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
    ap.add_argument("--url", help="a senora-helper:// link from the page's Connect button")
    a = ap.parse_args(argv)
    cfg = load_config()
    from_button = bool(a.url)
    code = a.code
    if a.url:
        try:
            a.server, code = parse_url(a.url)
        except ValueError as e:
            sys.exit(str(e))
    server = (a.server or cfg.get("server") or "").rstrip("/")
    if not server:
        sys.exit("Give the page address once:  start_senora helper https://your-senora.example")
    if not cfg.get("token") or cfg.get("server") != server or code:
        if from_button and cfg.get("server") != server and not confirm_server(server):
            sys.exit("Cancelled: not connected.")
        code = code or input("Code shown on the page (press Connect my computer): ")
        pair(server, code)
        print("Connected.")
        cfg = load_config()
    print(f"Helper running for {server}. It works only when a song has to be fetched. Press Ctrl+C to stop.")
    try:
        run(Client(server, cfg["token"]), idle_exit=1800 if from_button else None)
    except KeyboardInterrupt:
        print("Stopped.")
