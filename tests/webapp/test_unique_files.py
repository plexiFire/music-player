import json
import subprocess
import time

import pytest
from PIL import Image

from server import app as A

PID = "99999999"


def make(tmp_path, monkeypatch, n=5, audio=False):
    monkeypatch.setattr(A, "DATA", tmp_path)
    d = tmp_path / PID
    for sub in ("audio", "work", "out"):
        (d / sub).mkdir(parents=True)
    tracks, links = [], []
    for i in range(1, n + 1):
        link = f"https://youtu.be/{chr(64 + i) * 11}"
        links.append(link)
        cover = d / "work" / f"cover{i:02d}.png"
        Image.new("RGB", (40, 40), (i * 40, 20, 20)).save(cover)
        t = {"title": f"S{i}", "artist": "", "audio": f"/x/{i}.mp3", "cover": str(cover), "duration": 100.0, "from_link": link, "source_link": link,
             "image_source": f"link thumbnail: {link}"}
        if audio:
            f = d / "audio" / f"orig{i}.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + 40 * i}:duration=30", str(f)], check=True)
            t["audio"], t["duration"] = str(f), 30.0
        tracks.append(t)
    json.dump({"id": PID, "name": "t", "title": "t", "theme": "t", "created": time.time(), "links": links, "tracks": tracks, "rights_confirmed": True},
              open(d / "project.json", "w"))
    return d


def test_a_song_added_after_one_was_removed_never_reuses_a_cover_number(tmp_path, monkeypatch):
    d = make(tmp_path, monkeypatch)                                  # five songs, covers 01..05, no 'next_index' (an older project)
    A.remove_track(PID, 4)                                           # four songs left: the old 'songs + 1' would pick 5 again
    assert A._next_cover_index(d, A.load(PID)) == 6
    A.undo_remove_track(PID)
    assert A._next_cover_index(d, A.load(PID)) == 6
    (d / "work" / "cover09.png").write_bytes(b"x")                    # a file of a song that is long gone still counts
    assert A._next_cover_index(d, A.load(PID)) == 10


def test_extraction_after_a_removal_hands_the_importer_a_fresh_number(tmp_path, monkeypatch):
    make(tmp_path, monkeypatch)
    seen = []

    def fake(link, audio_dir, workdir, idx=1, **kw):
        seen.append(idx)
        return [{"title": "New", "artist": "", "audio": f"/x/new{idx}.mp3", "cover": f"/x/c{idx}.png", "duration": 50.0, "source_link": link}]
    monkeypatch.setattr(A.importer, "import_one", fake)
    monkeypatch.setattr(A, "_suggest_cut", lambda t: None)
    monkeypatch.setattr(A._mb, "fix_artists", lambda tracks: [])
    monkeypatch.setattr(A._profile, "build", lambda tracks, **kw: {"genres": [], "moods": [], "mood": "", "hashtags": []})
    A.remove_track(PID, 4)
    A.set_links(PID, A.Links(links=A.load(PID)["links"][:4] + ["https://youtu.be/" + "Z" * 11]))
    jid = A.extract(PID, A.Extract(rights_confirmed=True))["job"]
    for _ in range(100):
        if A.JOBS[jid]["state"] != "running":
            break
        time.sleep(0.05)
    assert seen == [6]                                               # not 5: cover05.png belongs to another song
    assert all(t.get("uid") for t in A.load(PID)["tracks"] if t["title"] == "New")


def test_cut_files_are_named_by_the_song_not_by_its_place(tmp_path, monkeypatch):
    make(tmp_path, monkeypatch, n=2, audio=True)
    first = A.trim_track(PID, 1, A.Trim(start=5.0, end=25.0))["audio"]
    A.remove_track(PID, 1)                                           # the other song is now number 1
    second = A.trim_track(PID, 1, A.Trim(start=3.0, end=20.0))["audio"]
    assert first != second and "trim_" in first and "trim_" in second
    import os
    assert os.path.exists(first) and os.path.exists(second)           # the first song's cut was not overwritten by the second's


def test_two_songs_on_one_cover_file_get_their_own_pictures_again(tmp_path, monkeypatch):
    d = make(tmp_path, monkeypatch, n=2)
    p = A.load(PID)
    shared = p["tracks"][1]["cover"]
    p["tracks"][0]["cover"] = shared                                 # the damage: both point at cover02.png
    p["tracks"][0]["image_source"] = "link thumbnail: https://youtu.be/AAAAAAAAAAA"
    json.dump(p, open(d / "project.json", "w"))
    asked = []

    def fake(url, out):
        asked.append(url)
        Image.new("RGB", (30, 30), (200, 10 * len(asked), 10)).save(out)
        return out
    monkeypatch.setattr(A.importer, "_square_png_from_url", fake)
    got = A.get_project(PID)["tracks"]
    assert got[0]["cover"] != got[1]["cover"] and all(__import__("os").path.exists(t["cover"]) for t in got)
    assert any("AAAAAAAAAAA" in u for u in asked) and any("BBBBBBBBBBB" in u for u in asked)     # each from its own video
    assert len(asked) == 2
    A.get_project(PID)
    assert len(asked) == 2                                           # fixed once, not on every open


def test_an_uploaded_picture_is_never_replaced_by_the_repair(tmp_path, monkeypatch):
    d = make(tmp_path, monkeypatch, n=2)
    p = A.load(PID)
    p["tracks"][0]["cover"] = p["tracks"][1]["cover"]
    p["tracks"][0]["image_source"] = "upload: mine.png"
    p["tracks"][1]["image_source"] = "upload: mine.png"
    json.dump(p, open(d / "project.json", "w"))
    monkeypatch.setattr(A.importer, "_square_png_from_url", lambda *a: (_ for _ in ()).throw(AssertionError("must not download")))
    A.get_project(PID)
