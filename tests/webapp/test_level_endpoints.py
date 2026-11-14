import json
import subprocess
import time

import pytest

from engine import cloud
from engine.media import level
from server import app as A

PID = "ffffffff"


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DATA", tmp_path)
    d = tmp_path / PID
    for sub in ("audio", "work", "out"):
        (d / sub).mkdir(parents=True)
    tracks = []
    for i, vol in enumerate((3, 0.6, 3), 1):                    # loud, quiet, loud: boundary 1->2 and 2->3 both jump
        f = d / "audio" / f"s{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + 50 * i}:duration=24", "-af", f"volume={vol}", str(f)], check=True)
        tracks.append({"title": f"S{i}", "artist": "", "audio": str(f), "duration": 24.0, "cover": None})
    json.dump({"id": PID, "name": "t", "title": "t", "theme": "t", "created": time.time(), "links": [], "rights_confirmed": True, "tracks": tracks},
              open(d / "project.json", "w"))
    return tmp_path


def test_loudness_gives_the_graph_the_jumps_and_a_plan_for_any_choice(project):
    r = A.loudness(PID)
    assert len(r["curves"]) == 3 and len(r["curves"][0]) == 48 and r["mode"] == "off" and r["pairs"] == []
    assert r["boundaries"][0]["jump"] > 8 and r["boundaries"][1]["jump"] < -8
    assert r["after"] == r["curves"]                              # off: nothing changes
    st = A.loudness_plan(PID, "pairs", "1")                       # tick only the first boundary
    assert abs(st["boundaries"][0]["jump_after"]) < 0.5           # that jump is gone ...
    assert st["boundaries"][1]["jump_after"] == st["boundaries"][1]["jump"]       # ... the other one is exactly as it was
    assert st["plan"][1]["end"] == 0.0 and st["plan"][1]["start"] > 3
    whole = A.loudness_plan(PID, "whole", "")
    assert whole["plan"][0]["whole"] < 0 < whole["plan"][1]["whole"]
    with pytest.raises(A.HTTPException):
        A.loudness_plan(PID, "banana", "")


def test_choices_are_saved_and_reflected_and_a_cut_refreshes_the_graph(project):
    A.set_leveling(PID, A.LevelSwitch(mode="pairs", pairs=[2, 1, 1]))
    p = A.load(PID)
    assert (p["level_mode"], p["level_pairs"], p["level_audio"]) == ("pairs", [1, 2], True)
    assert A.loudness(PID)["pairs"] == [1, 2]
    A.set_leveling(PID, A.LevelSwitch(on=True))                   # the older on/off switch still works: it means "whole"
    assert A.load(PID)["level_mode"] == "whole"
    A.set_leveling(PID, A.LevelSwitch(mode="off"))
    assert A.load(PID)["level_audio"] is False
    A.trim_track(PID, 1, A.Trim(start=4.0, end=20.0))             # song 1 is now 16 s: the graph must follow
    assert len(A.loudness(PID)["curves"][0]) == 32
    with pytest.raises(A.HTTPException):
        A.set_leveling(PID, A.LevelSwitch(mode="banana"))


def test_the_listening_clip_after_has_a_smaller_jump_than_before(project):
    before = A.level_demo(PID, 1, "before", "pairs", "1").path
    after = A.level_demo(PID, 1, "after", "pairs", "1").path
    cb, ca = level.curve(str(before)), level.curve(str(after))
    half = len(cb) // 2
    jump = lambda c: sum(c[:half]) / half - sum(c[half:]) / (len(c) - half)
    assert jump(ca) < jump(cb) - 4


def test_a_cloud_job_with_chosen_boundaries_renders_with_only_those_songs_changed(tmp_path):
    songs = []
    for i, vol in enumerate((3, 0.6, 3), 1):
        f = tmp_path / f"c{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + 50 * i}:duration=24", "-af", f"volume={vol}", str(f)], check=True)
        songs.append(str(f))
    job = {"name": "Level job", "authorized": True, "offline": True, "no_llm": True, "preview": True, "links": songs,
           "settings": {"mood": "calm", "level_mode": "pairs", "level_pairs": [1]}}
    cloud.run(job, str(tmp_path / "out"), str(tmp_path / "work"))
    made = sorted(p.name for p in (tmp_path / "work" / "work" / "leveled").glob("*.mp3"))
    assert len(made) == 2 and all("c3" not in m for m in made)    # only songs 1 and 2 were touched (boundary 1); song 3 is the original
