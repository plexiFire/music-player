import json
import time

import pytest

from server import app as A
from server.helper import Helper, cleanup, files_of


def test_the_helper_is_on_by_default_and_the_switch_is_remembered(tmp_path):
    h = Helper(tmp_path / "h.json")
    assert h.is_on()
    h.set(False)
    assert not Helper(tmp_path / "h.json").is_on()
    h.set(True)
    assert Helper(tmp_path / "h.json").is_on()


def test_extract_refuses_with_a_plain_message_when_the_helper_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DATA", tmp_path)
    monkeypatch.setattr(A, "HELPER", Helper(tmp_path / "h.json"))
    pid = A._new_project("p", ["https://youtu.be/aaaaaaaaaaa"])
    A.HELPER.set(False)
    with pytest.raises(A.HTTPException) as e:
        A.extract(pid, A.Extract(rights_confirmed=True, force=False))
    assert "helper is off" in e.value.detail.lower()


def test_status_says_it_waits_until_a_song_has_to_be_fetched(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "HELPER", Helper(tmp_path / "h.json"))
    s = A.helper_status()
    assert s["on"] and not s["busy"] and "Waiting" in s["message"]
    A.helper_set(A.HelperReq(on=False))
    assert A.helper_status()["message"] == "Off"


def test_cleanup_removes_only_confirmed_uploaded_downloads_inside_the_playlist_folder(tmp_path):
    d = tmp_path / "pl"
    (d / "audio").mkdir(parents=True)
    mine, kept, outside = d / "audio" / "a.mp3", d / "audio" / "b.mp3", tmp_path / "yours.mp3"
    for f in (mine, kept, outside):
        f.write_bytes(b"x")
    proj = {"tracks": [{"audio": str(mine), "uploaded": True}, {"audio": str(kept)}, {"audio": str(outside), "uploaded": True}],
            "downloaded": [str(mine), str(kept)]}                       # `outside` is not in the helper's own list
    removed = cleanup(d, proj)
    assert removed == [str(mine.resolve())]
    assert not mine.exists() and kept.exists() and outside.exists()


def test_cleanup_does_nothing_when_nothing_was_confirmed_uploaded(tmp_path):
    d = tmp_path / "pl"
    (d / "audio").mkdir(parents=True)
    f = d / "audio" / "a.mp3"
    f.write_bytes(b"x")
    assert cleanup(d, {"tracks": [{"audio": str(f)}], "downloaded": [str(f)]}) == []
    assert f.exists()


def test_a_fetch_records_progress_per_song_and_what_it_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DATA", tmp_path)
    monkeypatch.setattr(A, "HELPER", Helper(tmp_path / "h.json"))
    links = ["https://youtu.be/aaaaaaaaaaa", "https://youtu.be/bbbbbbbbbbb"]
    pid = A._new_project("p", links)
    d = A.pdir(pid)
    (d / "audio").mkdir(exist_ok=True)

    def fake_import(link, audio_dir, workdir, idx, **k):
        if link.endswith("bbbbbbbbbbb"):
            raise RuntimeError("blocked")
        f = d / "audio" / "a.mp3"
        f.write_bytes(b"x")
        return [{"title": "Song A", "artist": "x", "audio": str(f), "cover": None, "duration": 3.0, "source_link": link}]
    monkeypatch.setattr(A.importer, "import_one", fake_import)
    jid = A.new_job("extract", pid)
    A._extract(jid, pid)
    songs = A.JOBS[jid]["songs"]
    assert [x["state"] for x in songs] == ["done", "failed"] and songs[0]["title"] == "Song A" and "blocked" in songs[1]["error"]
    assert A.load(pid)["downloaded"] == [str(d / "audio" / "a.mp3")]
