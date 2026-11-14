import json
import subprocess
import time

import pytest

from server import app as A

PID = "cccccccc"


@pytest.fixture()
def song(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DATA", tmp_path)
    d = tmp_path / PID
    for sub in ("audio", "work", "out"):
        (d / sub).mkdir(parents=True)
    src = d / "audio" / "orig.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=40", str(src)], check=True)
    json.dump({"id": PID, "name": "t", "title": "t", "theme": "t", "created": time.time(), "links": [], "rights_confirmed": True,
               "tracks": [{"title": "S", "artist": "", "audio": str(src), "duration": 40.0, "cover": None}]}, open(d / "project.json", "w"))
    return src


def test_a_cut_uses_the_times_of_the_audio_you_hear_and_a_second_cut_stays_on_the_original_timeline(song):
    t = A.trim_track(PID, 1, A.Trim(start=5.0, end=35.0))                  # first cut: original 5 -> 35
    assert t["trim"]["start"] == 5.0 and t["trim"]["end"] == 35.0 and abs(t["duration"] - 30.0) < 0.3
    t = A.trim_track(PID, 1, A.Trim(start=2.0, end=12.0))                  # now typed against the 30 s audio you hear
    assert t["trim"]["start"] == 7.0 and t["trim"]["end"] == 17.0 and abs(t["duration"] - 10.0) < 0.3
    assert t["audio_original"] == str(song)                                # the original is still the very first file
    t = A.restore_track(PID, 1)
    assert "trim" not in t and abs(t["duration"] - 40.0) < 0.3


def test_cut_limits_are_checked_against_the_audio_you_hear(song):
    A.trim_track(PID, 1, A.Trim(start=10.0, end=30.0))                     # 20 s now
    with pytest.raises(A.HTTPException):
        A.trim_track(PID, 1, A.Trim(start=1.0, end=4.0))                   # under 5 s
    t = A.trim_track(PID, 1, A.Trim(start=0.0, end=500.0))                 # 'until' beyond the end is clamped to what you hear
    assert t["trim"]["end"] == 30.0


def test_a_cut_made_by_the_old_code_is_repaired_from_the_saved_original_when_the_project_opens(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[1] / "media"))
    from test_cut_tail import peaks, song
    monkeypatch.setattr(A, "DATA", tmp_path)
    d = tmp_path / "eeeeeeee"
    for sub in ("audio", "work", "out"):
        (d / sub).mkdir(parents=True)
    src = song(d / "audio")
    damaged = str(d / "audio" / "track01_trimmed.mp3")        # what the old code wrote: the last 12 s silent
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", "-map", "0:a:0", "-to", "30.000", "-ss", "12.000", "-af",
                    "afade=t=in:d=0.1,afade=t=out:st=17.500:d=0.5", "-ar", "48000", "-c:a", "libmp3lame", "-q:a", "2", damaged], check=True)
    assert peaks(damaged)[-8:].max() < 0.05
    json.dump({"id": "eeeeeeee", "name": "t", "title": "t", "theme": "t", "created": time.time(), "links": [], "rights_confirmed": True,
               "tracks": [{"title": "S", "artist": "", "audio": damaged, "audio_original": src, "duration": 18.0, "cover": None,
                           "trim": {"start": 12.0, "end": 30.0, "by": "manual"}}]}, open(d / "project.json", "w"))
    p = A.get_project("eeeeeeee")
    t = p["tracks"][0]
    assert t["trim"]["v"] == 2 and t["audio"] == damaged and abs(t["duration"] - 18.0) < 0.3
    assert peaks(damaged)[-8:].min() > 0.5                    # the loud ending is back
    assert A.get_project("eeeeeeee")["tracks"][0]["trim"]["v"] == 2   # and it is not redone every time
