"""Keeps track of the helper programs (ffmpeg) a build starts, so that stopping a build, closing the server or a crash
never leaves them running in the background (a forgotten ffmpeg is what makes the computer hot)."""
import atexit
import os
import signal
import subprocess
import threading

_live = set()
_lock = threading.Lock()
_local = threading.local()


class Cancelled(Exception):
    pass


def bind(event):
    """Called at the start of a background job: this thread now stops when `event` is set."""
    _local.event = event


def check():
    ev = getattr(_local, "event", None)
    if ev is not None and ev.is_set():
        raise Cancelled("stopped by you")


def start(cmd, **kw):
    check()
    p = subprocess.Popen(cmd, **kw)
    with _lock:
        _live.add(p)
    return p


def done(p):
    with _lock:
        _live.discard(p)


def kill(p):
    if p.poll() is None:
        try:
            p.kill()
            p.wait(5)
        except Exception:
            pass
    done(p)


def kill_all():
    with _lock:
        ps = list(_live)
    for p in ps:
        kill(p)


def orphans(marker):
    """ffmpeg programs left over by a server that was killed hard (parent gone, command mentions `marker`): stop them."""
    out = subprocess.run(["ps", "-Ao", "pid,ppid,command"], capture_output=True, text=True).stdout
    n = 0
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[1] == "1" and "ffmpeg" in parts[2] and marker in parts[2]:
            try:
                os.kill(int(parts[0]), signal.SIGKILL)
                n += 1
            except OSError:
                pass
    return n


atexit.register(kill_all)
