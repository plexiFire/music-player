import json
import time

import pytest

from server import app as A

PID = "bbbbbbbb"


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DATA", tmp_path)
    d = tmp_path / PID
    for sub in ("audio", "work", "out"):
        (d / sub).mkdir(parents=True)
    json.dump({"id": PID, "name": "t", "title": "t", "theme": "t", "created": time.time(), "links": ["https://youtu.be/" + "A" * 11], "rights_confirmed": True,
               "mood": "calm", "channel": "Senora", "tracks": [{"title": "S", "artist": "B", "audio": "/x.mp3", "cover": None, "duration": 200.0,
                                                               "from_link": "https://youtu.be/" + "A" * 11}]}, open(d / "project.json", "w"))
    monkeypatch.setattr(A, "suggest_titles", lambda *a, **k: {"titles": [
        {"title": "[Playlist] Songs that take you back", "score": 80, "source": "channel", "reasons": []},
        {"title": "[Playlist] Hide me please", "score": 70, "source": "channel", "reasons": []}], "warnings": []})
    return tmp_path


def test_your_own_titles_can_be_added_edited_and_deleted_and_suggestions_can_be_crossed_out(data):
    cid = A.title_add(A.TitleText(title="  [Playlist]   Songs for my   people ")).get("custom")[0]["id"]
    assert A.title_add(A.TitleText(title="[playlist] songs for my people"))["custom"].__len__() == 1       # no duplicates
    r = A.preview(PID, A.PreviewReq())
    assert r["titles"][0] == {"title": "[Playlist] Songs for my people", "score": 100, "source": "mine", "id": cid}
    assert r["chosen"] == "[Playlist] Songs that take you back"                                           # your list does not change the default pick
    A.title_edit(cid, A.TitleText(title="[Playlist] Songs for my crew"))
    assert A.preview(PID, A.PreviewReq())["titles"][0]["title"] == "[Playlist] Songs for my crew"
    A.title_hide(A.TitleText(title="[Playlist] Hide me please"))                                         # cross out a suggested title
    titles = [t["title"] for t in A.preview(PID, A.PreviewReq())["titles"]]
    assert "[Playlist] Hide me please" not in titles and A.title_bank()["hidden"] == 1
    A.title_restore()
    assert "[Playlist] Hide me please" in [t["title"] for t in A.preview(PID, A.PreviewReq())["titles"]]
    A.title_delete(cid)
    assert A.title_bank()["custom"] == []
    with pytest.raises(A.HTTPException):
        A.title_add(A.TitleText(title="x"))
    with pytest.raises(A.HTTPException):
        A.title_edit("nope", A.TitleText(title="[Playlist] fine title"))


def test_crossing_out_your_own_title_deletes_it(data):
    A.title_add(A.TitleText(title="[Playlist] Mine"))
    r = A.title_hide(A.TitleText(title="[Playlist] Mine"))
    assert r["custom"] == [] and r["hidden"] == 0


def test_the_gpt_brief_and_pack_come_from_the_project_without_audio(data):
    md = A.gpt_brief(PID, "Is it good?")["markdown"]
    assert "songs: 1, total length 3:20" in md
    assert "MY QUESTION: Is it good?" in md and ".mp3" not in md
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(A.gpt_pack(PID).body))
    assert "brief.md" in z.namelist() and not any(n.endswith((".mp3", ".mp4", ".wav")) for n in z.namelist())


def test_the_brief_is_also_a_plain_md_download(data):
    r = A.gpt_brief_file(PID, "Is it good?")
    assert r.headers["content-disposition"].endswith('senora-brief.md"') and r.media_type.startswith("text/markdown")
    assert b"MY QUESTION: Is it good?" in r.body and b".mp3" not in r.body
