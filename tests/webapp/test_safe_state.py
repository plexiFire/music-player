import json
import os
import subprocess
import time

import pytest

from engine import cli
from engine.video import render
from server import app as A

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")


def sample_project(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    tracks = [{"title": f"Song {i}", "artist": "Band", "audio": f"{SAMPLES}/tone{i}.wav", "cover": f"{SAMPLES}/cover{i}.png", "duration": 3.0}
              for i in (1, 2, 3)]
    proj = {"title": "t", "theme": "t", "name": "t", "channel": "Senora", "mood": "slow, calm", "disc": "vinyl", "tracks": tracks}
    path = work / "project.json"
    json.dump(proj, open(path, "w"))
    return path, proj


def build(path, out):
    import argparse
    cli.cmd_build(argparse.Namespace(project=str(path), out=str(out), preview=True, offline=True, no_llm=True))


def test_changing_thumbnails_or_text_never_renders_the_video_again_but_changing_the_look_does(tmp_path, monkeypatch):
    path, proj = sample_project(tmp_path)
    out = tmp_path / "out" / "v.mp4"
    out.parent.mkdir()
    calls = []
    real = render.render
    monkeypatch.setattr(render, "render", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    build(path, out)
    assert len(calls) == 1 and out.exists() and not any(f.name.endswith(".part.mp4") for f in out.parent.iterdir())
    stamp = out.stat().st_mtime_ns
    proj["thumbs_selected"] = [{"family": "night", "variant": "blue"}, {"family": "swirl", "variant": "mono"}]
    proj["youtube_title"] = "[Playlist] Songs for a quiet night"
    json.dump(proj, open(path, "w"))
    build(path, out)
    assert len(calls) == 1 and out.stat().st_mtime_ns == stamp               # the video was reused, not made again
    assert (out.parent / "v.thumbnail-A.jpg").exists() and (out.parent / "v.thumbnail-B.jpg").exists()
    assert "quiet night" in (out.parent / "v.titles.txt").read_text()
    proj["thumbs_selected"] = proj["thumbs_selected"][:1]                     # drop B: its old file must not stay behind
    json.dump(proj, open(path, "w"))
    build(path, out)
    assert len(calls) == 1 and not (out.parent / "v.thumbnail-B.jpg").exists()
    proj["disc"] = "plain"                                                    # a look change DOES need a new video
    json.dump(proj, open(path, "w"))
    build(path, out)
    assert len(calls) == 2
    names = {f.name for f in out.parent.iterdir() if not f.name.startswith(".")}
    assert "v.mp4" in names and not any(n.endswith(".part.mp4") for n in names)


def test_settings_changed_while_the_video_is_being_made_still_apply_to_the_next_stages(tmp_path, monkeypatch):
    path, proj = sample_project(tmp_path)
    out = tmp_path / "out" / "v.mp4"
    out.parent.mkdir()
    real = render.render

    def slow_video(*a, **k):
        res = real(*a, **k)
        p = json.load(open(path))                                              # you pick a thumbnail and a title while the video is being made
        p["thumbs_selected"] = [{"family": "poster", "variant": "ink"}]
        p["youtube_title"] = "[Playlist] Picked during the render"
        json.dump(p, open(path, "w"))
        return res
    monkeypatch.setattr(render, "render", slow_video)
    build(path, out)
    assert (out.parent / "v.thumbnail-A.jpg").exists()
    assert "Picked during the render" in (out.parent / "v.titles.txt").read_text()


def test_a_crash_while_rendering_never_leaves_something_that_looks_like_a_finished_video(tmp_path, monkeypatch):
    path, proj = sample_project(tmp_path)
    out = tmp_path / "v.mp4"

    (tmp_path / "w").mkdir()

    def dies(cmd, *a, **k):
        open(cmd[-1], "wb").write(b"half a video")                              # ffmpeg got this far, then the computer stopped
        raise RuntimeError("stopped")
    monkeypatch.setattr(render, "run_ffmpeg", dies)
    with pytest.raises(RuntimeError):
        render.render(proj, str(out), preview=True, work_dir=str(tmp_path / "w"))
    assert not out.exists() and (tmp_path / "v.mp4.part.mp4").exists()


def test_the_home_page_and_outputs_ignore_half_written_and_hidden_files(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DATA", tmp_path)
    d = tmp_path / "abababab"
    (d / "out").mkdir(parents=True)
    json.dump({"id": "abababab", "name": "x", "links": [], "tracks": [], "created": time.time()}, open(d / "project.json", "w"))
    (d / "out" / "x.mp4.part.mp4").write_bytes(b"half")
    (d / "out" / ".x.build.json").write_text("{}")
    card = A.home()[0]
    assert card["built"] is False and card["video"] is None
    assert A.outputs("abababab") == []


def test_a_job_is_remembered_across_a_restart_and_a_running_one_is_marked_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DATA", tmp_path)
    running, finished = A.new_job("build", "abababab"), A.new_job("extract", "abababab")
    A.set_job(running, message="stage 1/4: video")
    A.set_job(finished, state="done", message="done")
    A.JOBS.clear()                                                             # the server restarted
    A._recover_jobs()
    j = A.job(running)
    assert j["state"] == "interrupted" and "press the button again" in j["message"]
    assert A.job(finished)["state"] == "done"
    with pytest.raises(A.HTTPException):
        A.job("00000000")


def test_a_project_file_damaged_by_a_crash_comes_back_from_its_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DATA", tmp_path)
    d = tmp_path / "cdcdcdcd"
    d.mkdir()
    A.save("cdcdcdcd", {"id": "cdcdcdcd", "name": "first", "links": [], "tracks": []})
    A.save("cdcdcdcd", {"id": "cdcdcdcd", "name": "second", "links": [], "tracks": []})
    assert (d / "project.json.bak").exists()
    (d / "project.json").write_text('{"id": "cdcd')                             # the computer stopped in the middle of a write
    p = A.load("cdcdcdcd")
    assert p["name"] == "first"                                                 # the version before the broken write
    assert json.loads((d / "project.json").read_text())["name"] == "first"      # and the file is repaired


def test_where_you_were_is_remembered_and_a_deleted_playlist_sends_you_home(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DATA", tmp_path)
    d = tmp_path / "efefefef"
    d.mkdir()
    json.dump({"id": "efefefef", "name": "x", "links": [], "tracks": []}, open(d / "project.json", "w"))
    A.put_ui_state(A.UiState(mode="pl", pid="efefefef", step=2, scroll=640))
    assert A.get_ui_state() == {"mode": "pl", "pid": "efefefef", "step": 2, "catId": "", "scroll": 640}
    import shutil
    shutil.rmtree(d)
    assert A.get_ui_state() == {"mode": "lib"}
    A.put_ui_state(A.UiState(mode="lib", catId="sad-songs", step=9, pid="../etc"))
    st = A.get_ui_state()
    assert st["catId"] == "sad-songs" and st["step"] == 3 and st["pid"] == ""   # step limited, a path-like id refused


def test_stop_ends_the_helper_programs_so_nothing_keeps_the_computer_busy(tmp_path, monkeypatch):
    import subprocess
    from engine import procs
    monkeypatch.setattr(A, "DATA", tmp_path)

    def long_job(jid):
        p = procs.start(["sleep", "60"])
        try:
            while p.poll() is None:
                time.sleep(0.2)
                procs.check()
        except procs.Cancelled:
            procs.kill(p)
            raise
    jid = A.new_job("build", "abababab")
    A.run_bg(jid, long_job)
    time.sleep(0.6)
    assert A.stop_job(jid) == {"stopped": True}
    for _ in range(40):
        if A.JOBS[jid]["state"] != "running":
            break
        time.sleep(0.2)
    assert A.JOBS[jid]["state"] == "stopped" and "Stopped by you" in A.JOBS[jid]["message"]
    left = subprocess.run(["pgrep", "-f", "sleep 60"], capture_output=True, text=True).stdout.split()
    assert left == []


def test_orphaned_ffmpeg_of_a_killed_server_is_ended_at_start(tmp_path):
    import subprocess
    from engine import procs
    fake = tmp_path / "ffmpeg"                                   # a stand-in that is named like ffmpeg
    fake.write_text("#!/bin/sh\nsleep 61\n")
    fake.chmod(0o755)
    sub = subprocess.Popen(["sh", "-c", f"{fake} 61 &"])         # started and left behind: its parent is gone, like after a hard kill
    sub.wait()
    time.sleep(0.5)
    assert procs.orphans(str(tmp_path)) == 1
    time.sleep(0.3)
    assert str(fake) not in subprocess.run(["ps", "-Ao", "command"], capture_output=True, text=True).stdout
