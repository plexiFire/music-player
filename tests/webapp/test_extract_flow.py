import json
import time

import pytest

from server import app as A

PID = "aaaaaaaa"
LINK = lambda c: f"https://youtu.be/{c * 11}"


@pytest.fixture()
def proj(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DATA", tmp_path)
    d = tmp_path / PID
    for sub in ("audio", "work", "out"):
        (d / sub).mkdir(parents=True)
    json.dump({"id": PID, "name": "t", "title": "t", "theme": "t", "created": time.time(), "links": [LINK("A"), LINK("B"), LINK("C")],
               "tracks": [], "rights_confirmed": True}, open(d / "project.json", "w"))
    calls = []

    def fake_import(link, audio_dir, workdir, idx=1, **kw):
        calls.append(link)
        time.sleep(0.25)
        return [{"title": f"song {link[-1]}", "artist": "", "audio": f"/x/{idx}.mp3", "cover": "/x/c.png", "duration": 100.0, "source_link": link}]

    monkeypatch.setattr(A.importer, "import_one", fake_import)
    monkeypatch.setattr(A, "_suggest_cut", lambda t: None)
    monkeypatch.setattr(A._mb, "fix_artists", lambda tracks: [])
    monkeypatch.setattr(A._profile, "build", lambda tracks, **kw: {"genres": [], "moods": ["calm"], "mood": "calm", "hashtags": []})
    return calls


def wait(jid):
    for _ in range(100):
        if A.JOBS[jid]["state"] != "running":
            return A.JOBS[jid]
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_editing_links_while_extracting_loses_nothing_and_brings_nothing_back(proj):
    r = A.extract(PID, A.Extract(rights_confirmed=True))
    time.sleep(0.35)                                                    # song A is done, B is downloading
    A.set_links(PID, A.Links(links=[LINK("C"), LINK("A"), LINK("D")]))   # B removed, C moved first, D added
    assert wait(r["job"])["state"] == "done"
    p = A.with_estimate(A.load(PID))
    assert [t["from_link"][-1] for t in p["tracks"]] == ["C", "A"]      # B never comes back, order follows the new links
    assert [x["status"] for x in p["plan"]["rows"]] == ["done", "done", "pending"] and p["plan"]["pending"] == 1
    assert LINK("B") not in proj or proj.count(LINK("B")) <= 1           # the removed link was at most already in flight
    before = list(proj)
    wait(A.extract(PID, A.Extract(rights_confirmed=True))["job"])
    assert proj[len(before):] == [LINK("D")]                             # only the new song was extracted, A and C were not repeated
    p = A.with_estimate(A.load(PID))
    assert [t["from_link"][-1] for t in p["tracks"]] == ["C", "A", "D"] and p["plan"]["pending"] == 0 and p["total_seconds"] == 300.0
    assert p["profile"]["mood"] == "calm"


def test_a_second_extract_request_joins_the_running_one(proj):
    first = A.extract(PID, A.Extract(rights_confirmed=True))
    again = A.extract(PID, A.Extract(rights_confirmed=True))
    assert again["job"] == first["job"] and again["already_running"]
    wait(first["job"])


def test_a_song_can_be_removed_and_put_back_and_build_waits_for_missing_songs(proj):
    wait(A.extract(PID, A.Extract(rights_confirmed=True))["job"])
    p = A.remove_track(PID, 2)
    assert [t["from_link"][-1] for t in p["tracks"]] == ["A", "C"] and LINK("B") not in p["links"] and p["plan"]["pending"] == 0
    p = A.undo_remove_track(PID)
    assert [t["from_link"][-1] for t in p["tracks"]] == ["A", "B", "C"] and p["links"][1] == LINK("B")
    A.set_links(PID, A.Links(links=[LINK("A"), LINK("B"), LINK("C"), LINK("E")]))
    with pytest.raises(A.HTTPException) as e:
        A.build(PID, A.BuildReq())
    assert e.value.status_code == 400 and "not extracted yet" in e.value.detail
    with pytest.raises(A.HTTPException):
        A.remove_track(PID, 99)
