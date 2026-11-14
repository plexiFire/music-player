"""The link between the hosted page and the helper on your own computer.
The page never talks to YouTube: it puts a 'fetch this song' request in a queue, the helper (your Mac, which connects OUT to the page, so no
ports are opened) picks it up, downloads the song on your own connection and uploads the files. Pairing uses a short one-time code, and the
helper then holds its own token, which can be revoked. Only a hash of the token is kept here."""
import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

CODE_LIFE = 600        # seconds a pairing code works
ALIVE = 30             # the helper counts as connected when it was seen this recently


class Agent:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.codes = {}                      # code -> expiry time
        self.tasks = {}                      # task id -> task
        self.seen = 0.0

    # ---- pairing and tokens ----
    def _cfg(self):
        try:
            return json.loads((self.root / "agent.json").read_text())
        except (OSError, ValueError):
            return {"tokens": []}

    def _save(self, cfg):
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "agent.json.tmp"
        tmp.write_text(json.dumps(cfg))
        os.replace(tmp, self.root / "agent.json")

    def new_code(self):
        with self.lock:
            now = time.time()
            self.codes = {c: t for c, t in self.codes.items() if t > now}
            code = "".join(secrets.choice("23456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6))
            self.codes[code] = now + CODE_LIFE
            return code, CODE_LIFE

    def pair(self, code):
        """Trade a valid one-time code for a token (shown once; only its hash is stored)."""
        with self.lock:
            code = (code or "").strip().upper()
            if self.codes.pop(code, 0) < time.time():
                raise ValueError("that code is wrong or has expired: get a new one on the page")
            token = secrets.token_urlsafe(32)
            cfg = self._cfg()
            cfg["tokens"].append(hashlib.sha256(token.encode()).hexdigest())
            self._save(cfg)
            self.seen = time.time()
            return token

    def check(self, token):
        if not token:
            return False
        h = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            ok = h in self._cfg()["tokens"]
            if ok:
                self.seen = time.time()
            return ok

    def revoke_all(self):
        with self.lock:
            self._save({"tokens": []})
            self.seen = 0.0

    def connected(self):
        return time.time() - self.seen < ALIVE

    # ---- the queue ----
    def enqueue(self, pid, link, idx):
        with self.lock:
            tid = secrets.token_hex(4)
            self.tasks[tid] = {"id": tid, "pid": pid, "link": link, "idx": idx, "state": "pending", "message": "waiting for your computer",
                               "created": time.time(), "tracks": None, "error": ""}
            return tid

    def claim(self):
        with self.lock:
            for t in sorted(self.tasks.values(), key=lambda t: t["created"]):
                if t["state"] == "pending":
                    t["state"], t["message"], t["claimed_at"] = "claimed", "your computer is fetching it", time.time()
                    return dict(t)
            return None

    def get(self, tid):
        with self.lock:
            t = self.tasks.get(tid)
            return dict(t) if t else None

    def update(self, tid, **kw):
        with self.lock:
            if tid not in self.tasks:
                raise KeyError(tid)
            self.tasks[tid].update(kw)

    def requeue_lost(self, older_than=300):
        """A claimed task whose helper vanished (closed laptop) goes back in the queue."""
        with self.lock:
            now = time.time()
            for t in self.tasks.values():
                if t["state"] == "claimed" and now - t.get("claimed_at", t["created"]) > older_than and not self.connected():
                    t["state"], t["message"] = "pending", "waiting for your computer"
