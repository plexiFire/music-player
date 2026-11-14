import pytest

from server.library import Library, preset_categories


def fake(link):
    if "bad" in link:
        raise RuntimeError("ERROR: [generic] 'bad' is not a valid URL")
    n = link.rsplit("/", 1)[-1]
    return {"id": n, "title": f"Song {n}", "artist": "Band", "duration": 200, "cover_url": "http://x/y.jpg",
            "views": 1000, "web_tags": ["indie", "sad"], "source_link": link}


def test_presets_cover_the_categories_the_user_listed():
    names = {c["name"].lower() for c in preset_categories()}
    for want in ("gym songs", "morning walk songs", "late night songs", "dark night songs", "sad songs"):
        assert want in names
    assert len(names) >= 40 and len({c["id"] for c in preset_categories()}) == len(preset_categories())


def test_add_songs_dedupes_reports_bad_links_and_remembers(tmp_path):
    lib = Library(tmp_path / "lib.json")
    added, problems = lib.add_songs("sad-songs", ["http://y/a", "http://y/a", "http://y/bad", "http://y/b"], fake)
    assert [s["title"] for s in added] == ["Song a", "Song b"]
    assert {p["error"] for p in problems} == {"already in this category", "this does not look like a song link"}
    assert Library(tmp_path / "lib.json").songs("sad-songs")[0]["artist"] == "Band"        # survives a restart
    st = lib.stats("sad-songs")
    assert st["songs"] == 2 and st["minutes"] == 6.7 and st["top_artists"][0] == ("Band", 2) and not st["ready"]


def test_copy_move_remove_custom_categories_and_make_playlist_marks_use(tmp_path):
    lib = Library(tmp_path / "lib.json")
    lib.add_songs("gym-songs", ["http://y/a"], fake)
    sid = lib.songs("gym-songs")[0]["id"]
    lib.copy_song("gym-songs", sid, "running")
    lib.copy_song("gym-songs", sid, "running")                       # copying twice does not duplicate
    assert len(lib.songs("running")) == 1 and len(lib.songs("gym-songs")) == 1
    lib.copy_song("gym-songs", sid, "late-night-songs", move=True)
    assert lib.songs("gym-songs") == [] and len(lib.songs("late-night-songs")) == 1
    cid = lib.add_category("Rainy walks")
    with pytest.raises(ValueError):
        lib.add_category("rainy  walks")                             # same name again
    lib.delete_category("gym-songs")                                 # a built-in one is only hidden (it can be brought back)
    assert all(c["id"] != "gym-songs" for c in lib.categories())
    lib.restore_defaults()
    lib.add_songs(cid, ["http://y/z"], fake)
    lib.mark_used(cid, {lib.songs(cid)[0]["id"]}, "My list")
    assert lib.stats(cid)["never_used"] == 0
    lib.delete_category(cid)
    with pytest.raises(KeyError):
        lib.songs(cid)
    with pytest.raises(KeyError):
        lib.add_songs("no-such-category", ["http://y/a"], fake)


def test_error_messages_are_in_plain_words():
    from server.library import friendly_error
    assert "not a bot" in friendly_error("ERROR: [youtube] x: Sign in to confirm you’re not a bot")
    assert "private" in friendly_error("ERROR: Private video. Sign in if you've been granted access")
    assert "playlist" in friendly_error("this is a playlist")
    assert "does not look like a song link" in friendly_error("'x' is not a valid URL")


def test_a_link_yt_dlp_cannot_read_falls_back_to_youtubes_public_title_lookup(monkeypatch):
    from server import app as A
    monkeypatch.setattr(A.ytdlp, "info", lambda link: (_ for _ in ()).throw(RuntimeError("Sign in to confirm you're not a bot")))

    class R:
        def raise_for_status(self): pass
        def json(self): return {"title": "Gigi Perez - Sailor Song"}
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    m = A._fetch_meta("https://youtu.be/abcdefghijk?si=zzz")
    assert (m["artist"], m["title"], m["id"]) == ("Gigi Perez", "Sailor Song", "abcdefghijk")
    assert m["cover_url"].endswith("/abcdefghijk/hqdefault.jpg")


def test_built_in_categories_can_be_renamed_removed_and_brought_back(tmp_path):
    from server.library import Library
    lib = Library(tmp_path / "lib.json")
    names = lambda: {c["id"]: c["name"] for c in lib.categories()}
    assert "sad-songs" in names()
    lib.rename_category("sad-songs", "Rainy day songs")
    assert names()["sad-songs"] == "Rainy day songs"                      # same id, so its songs stay with it
    lib.delete_category("heartbreak")
    assert "heartbreak" not in names()
    with pytest.raises(KeyError):
        lib.songs("heartbreak")
    lib.restore_defaults()
    assert names()["heartbreak"] == "Heartbreak" and names()["sad-songs"] == "Rainy day songs"   # only removed ones return; your rename stays


def test_your_own_category_can_be_renamed_but_not_to_a_name_that_is_taken(tmp_path):
    from server.library import Library
    lib = Library(tmp_path / "lib.json")
    cid = lib.add_category("rainy walks")
    lib.rename_category(cid, "Walks in the rain")
    assert next(c for c in lib.categories() if c["id"] == cid)["name"] == "Walks in the rain"
    with pytest.raises(ValueError):
        lib.rename_category(cid, "sad songs")
    with pytest.raises(ValueError):
        lib.rename_category(cid, "  ")
    lib.delete_category(cid)
    assert all(c["id"] != cid for c in lib.categories())
