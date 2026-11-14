import os
import shutil
import socket
import threading
import time

import pytest

from helper import agent as H
from server import app as A
from server.agent import Agent
from server.helper import Helper

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")


def test_a_pairing_code_works_once_and_a_wrong_or_old_one_is_refused(tmp_path):
    a = Agent(tmp_path)
    code, _ = a.new_code()
    token = a.pair(code)
    assert a.check(token) and not a.check("nope") and not a.check("")
    with pytest.raises(ValueError):
        a.pair(code)                                             # a code is good once
    with pytest.raises(ValueError):
        a.pair("WRONG1")
    code2, _ = a.new_code()
    a.codes[code2] = time.time() - 1                              # expired
    with pytest.raises(ValueError):
        a.pair(code2)
    assert code not in (tmp_path / "agent.json").read_text() and token not in (tmp_path / "agent.json").read_text()   # only a hash is stored
    a.revoke_all()
    assert not a.check(token)


def test_a_claimed_task_goes_back_when_the_helper_vanished(tmp_path):
    a = Agent(tmp_path)
    tid = a.enqueue("p", "https://youtu.be/aaaaaaaaaaa", 1)
    assert a.claim()["id"] == tid and a.claim() is None
    a.tasks[tid]["claimed_at"] -= 1000
    a.requeue_lost(300)
    assert a.get(tid)["state"] == "pending"


class FakeImporter:
    """Stands in for the real download: writes an audio and a cover file where the helper asks."""
    @staticmethod
    def import_one(link, audio_dir, workdir, idx, **k):
        if link.endswith("bbbbbbbbbbb"):
            raise RuntimeError("blocked by the video site")
        a, c = os.path.join(audio_dir, f"song{idx}.wav"), os.path.join(workdir, f"cover{idx}.png")
        shutil.copy(f"{SAMPLES}/tone1.wav", a)
        shutil.copy(f"{SAMPLES}/cover1.png", c)
        return [{"title": "Song A", "artist": "X", "audio": a, "cover": c, "duration": 3.0, "source_link": link, "audio_source": "link"}]


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    import uvicorn
    monkeypatch.setattr(A, "DATA", tmp_path)
    monkeypatch.setattr(A, "MODE", "cloud")
    monkeypatch.setattr(A, "HELPER", Helper(tmp_path / "h.json"))
    monkeypatch.setattr(A, "AGENT", Agent(tmp_path / "_agent"))
    monkeypatch.setattr(H, "HOME", tmp_path / "helper_home")
    monkeypatch.setenv("SENORA_PASSWORD", "pw")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(A.app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    th.join(5)


def test_a_hosted_page_gets_its_songs_from_your_computer_and_the_helper_cleans_up_after_the_playlist_is_finished(hosted, tmp_path):
    base = hosted
    import requests
    code = requests.post(base + "/api/helper/pair", auth=("me", "pw")).json()["code"]          # you press Connect my computer on the page
    token = H.pair(base, code)
    c = H.Client(base, token)
    assert H.load_config()["token"] == token

    pid = A._new_project("p", ["https://youtu.be/aaaaaaaaaaa", "https://youtu.be/bbbbbbbbbbb"])
    jid = A.new_job("extract", pid)
    t = threading.Thread(target=A._extract, args=(jid, pid))
    t.start()
    for _ in range(40):                                           # the helper picks the songs up one after the other
        H.run(c, once=True, importer=FakeImporter, log=lambda m: None)
        if not t.is_alive():
            break
        time.sleep(0.3)
    t.join(20)
    assert not t.is_alive()
    A.set_job(jid, state="done")                                  # run_bg would have said so

    songs = A.JOBS[jid]["songs"]
    assert [x["state"] for x in songs] == ["done", "failed"] and "blocked" in songs[1]["error"]
    tr = [x for x in A.load(pid)["tracks"] if x.get("audio")][0]
    assert tr["from_helper"] and os.path.isfile(tr["audio"]) and tr["audio"].startswith(str(A.pdir(pid)))   # the page keeps its own copy
    local = H.local_dir(pid)
    assert local.is_dir() and any((local / "audio").iterdir())                                                # the helper keeps its copy while you work

    assert H.clean_finished(c) == []                                                                            # not finished yet: nothing is removed
    assert local.is_dir()
    A.mutate(pid, lambda p: p.__setitem__("finished", True))
    assert H.clean_finished(c) == [pid] and not local.exists()                                                   # the playlist ended: local copies go
    assert os.path.isfile(tr["audio"])                                                                           # the page's copy stays


def test_a_helper_with_a_wrong_token_is_refused_and_extract_waits_visibly_when_nothing_is_connected(hosted):
    with pytest.raises(RuntimeError, match="401"):
        H.Client(hosted, "bad").call("GET", "/api/agent/next")
    import requests
    s = requests.get(hosted + "/api/helper", auth=("me", "pw")).json()
    assert s["mode"] == "cloud" and not s["connected"] and "Connect my computer" in s["message"]


def test_a_hosted_page_needs_a_password_and_the_helper_path_needs_only_its_token(hosted, monkeypatch):
    import base64
    import requests
    monkeypatch.delenv("SENORA_PASSWORD", raising=False)
    assert requests.get(hosted + "/api/helper").status_code == 503                 # no password set on the host: nothing is served
    monkeypatch.setenv("SENORA_PASSWORD", "open-sesame")
    assert requests.get(hosted + "/api/helper").status_code == 401
    assert requests.get(hosted + "/api/helper", headers={"Authorization": "Basic " + base64.b64encode(b"me:wrong").decode()}).status_code == 401
    assert requests.get(hosted + "/api/helper", headers={"Authorization": "Basic " + base64.b64encode(b"me:open-sesame").decode()}).status_code == 200
    assert requests.get(hosted + "/api/agent/next", headers={"X-Agent-Token": "bad"}).status_code == 401   # reaches the token check, not the password


def test_on_your_own_computer_no_password_is_asked():
    assert A.MODE == "local"                                       # the default: nothing is blocked


def test_the_connect_link_is_read_and_anything_odd_is_refused():
    assert H.parse_url("senora-helper://connect?server=https%3A%2F%2Fmy.page%2F&code=ABC234") == ("https://my.page", "ABC234")
    for bad in ("https://evil/connect?server=https://x&code=1", "senora-helper://run?server=https://x", "senora-helper://connect?server=file:///etc&code=1"):
        with pytest.raises(ValueError):
            H.parse_url(bad)


def test_the_helper_stops_by_itself_when_it_has_had_nothing_to_do(hosted):
    import requests
    code = requests.post(hosted + "/api/helper/pair", auth=("me", "pw")).json()["code"]
    c = H.Client(hosted, H.pair(hosted, code))
    t0 = time.time()
    msgs = []
    H.run(c, poll=0.1, importer=FakeImporter, log=msgs.append, idle_exit=0.5)
    assert time.time() - t0 < 5 and any("stops now" in m for m in msgs)


def test_render_on_github_sends_the_playlist_and_the_finished_files_come_back_into_it(tmp_path, monkeypatch):
    import helper.send as S
    monkeypatch.setattr(A, "DATA", tmp_path)
    monkeypatch.setattr(A, "MODE", "local")
    pid = A._new_project("p", [])
    A.mutate(pid, lambda p: p["tracks"].append({"title": "x", "audio": "a.wav", "cover": "c.png"}))

    def fake_send(project_path, dest_dir=None, log=print, **options):
        log("rendering on GitHub...")
        d = Path(dest_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "list.mp4").write_bytes(b"video")
        (d / "list.thumbnail.jpg").write_bytes(b"jpg")
        return d
    from pathlib import Path
    monkeypatch.setattr(S, "send", fake_send)
    r = A.render_on_github(pid)
    for _ in range(50):
        if A.JOBS[r["job"]]["state"] != "running":
            break
        time.sleep(0.1)
    assert A.JOBS[r["job"]]["state"] == "done" and "rendering on GitHub" in A.JOBS[r["job"]]["message"] or A.JOBS[r["job"]]["state"] == "done"
    assert sorted(A.rendered(pid)["files"]) == ["list.mp4", "list.thumbnail.jpg"]
    assert A.rendered_file(pid, "list.mp4").path.endswith("list.mp4")


def test_stop_ends_the_wait_for_the_github_render(tmp_path, monkeypatch):
    import threading as th
    import helper.send as S
    from engine import procs
    monkeypatch.setattr(S, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("not yet")))
    ev = th.Event()
    out = {}

    def run():
        procs.bind(ev)
        try:
            S.wait_for_release("job-x", poll=5, timeout=60, log=lambda m: None)
        except procs.Cancelled:
            out["stopped"] = True
    t = th.Thread(target=run)
    t.start()
    time.sleep(1.2)
    ev.set()
    t.join(8)
    assert out.get("stopped") and not t.is_alive()                 # it noticed within a couple of seconds, not after 5 minutes


def test_sending_works_from_a_folder_that_is_not_a_git_folder_and_leaves_no_copy_behind(tmp_path, monkeypatch):
    import json as _json
    import subprocess as sp
    import helper.send as S
    bare, seed = tmp_path / "origin.git", tmp_path / "seed"
    sp.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed.mkdir()
    (seed / "requirements.txt").write_text("x\n")
    (seed / ".gitignore").write_text("jobs/\n")                   # even if the repo ignores jobs/, the songs must still go
    for c in (["init", "-q", "-b", "main"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed"],
              ["push", "-q", str(bare), "main"]):
        sp.run(["git", *c], cwd=seed, check=True)
    monkeypatch.setenv("SENORA_GIT_REMOTE", str(bare))
    monkeypatch.setattr(S, "REPO_ROOT", tmp_path / "not-a-git-folder")
    proj = {"name": "p", "tracks": [{"title": "S", "artist": "A", "audio": f"{SAMPLES}/tone1.wav", "cover": f"{SAMPLES}/cover1.png", "duration": 3.0}]}
    (tmp_path / "project.json").write_text(_json.dumps(proj))
    monkeypatch.setattr(S, "wait_for_release", lambda tag, **k: [{"name": "x.mp4", "browser_download_url": "file:///nothing"}])
    monkeypatch.setattr(S, "download", lambda asset, dst: dst)
    before = set(os.listdir(tempfile_dir := __import__("tempfile").gettempdir()))
    S.send(str(tmp_path / "project.json"), str(tmp_path / "out"), log=lambda m: None, preview=True)
    branches = sp.run(["git", "branch", "--list", "job/*"], cwd=bare, capture_output=True, text=True).stdout
    assert "job/" in branches                                                       # the branch with the songs reached the remote
    job_id = branches.strip().lstrip("* ").split("job/")[1]
    files = sp.run(["git", "ls-tree", "-r", "--name-only", f"job/{job_id}"], cwd=bare, capture_output=True, text=True).stdout
    assert f"jobs/{job_id}/job.json" in files and f"jobs/{job_id}/song01.wav" in files and "requirements.txt" in files   # the code is there too
    assert _json.loads(sp.run(["git", "show", f"job/{job_id}:jobs/{job_id}/job.json"], cwd=bare, capture_output=True, text=True).stdout)["preview"] is True
    assert not [d for d in set(os.listdir(tempfile_dir)) - before if d.startswith("senora-job-")]    # the temporary copy is gone
