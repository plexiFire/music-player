from engine.sources import musicbrainz as mb


def test_uploader_labels_are_recognised():
    assert mb.looks_like_source("Anime Ringtones, Anytunz") and mb.looks_like_source("") and mb.looks_like_source("Foo - Topic")
    assert not mb.looks_like_source("Gigi Perez") and not mb.looks_like_source("Billie Eilish")


def _fake(monkeypatch, recordings):
    class R:
        status_code = 200
        def json(self): return {"recordings": recordings}
    monkeypatch.setattr(mb.requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(mb.time, "sleep", lambda *_: None)


def test_covers_and_ambiguous_matches_are_never_used(monkeypatch):
    _fake(monkeypatch, [{"score": 100, "title": "FE!N (8-Bit Travis Scott Emulation)", "artist-credit": [{"name": "8-Bit Arcade"}]}])
    assert mb.lookup("FE!N", "Travis Scott Nokia Ringtone") is None
    assert mb.lookup("Unforgettable", "") is None                       # short title with no clue: no guess


def test_real_artist_replaces_an_uploader_label_and_unknown_uploaders_are_dropped(monkeypatch):
    _fake(monkeypatch, [{"score": 100, "title": "Sailor Song", "artist-credit": [{"name": "Gigi Perez"}], "tags": [{"name": "indie pop"}]}])
    t = [{"title": "Sailor Song Official Video", "artist": "Random Records"}, {"title": "Gigi Perez", "artist": "Anime Ringtones"}]
    mb.fix_artists(t)
    assert t[0]["artist"] == "Gigi Perez" and "indie pop" in t[0]["web_tags"]
    _fake(monkeypatch, [])
    t2 = [{"title": "Some Long Title Here", "artist": "Anytunz Ringtones"}]
    mb.fix_artists(t2)
    assert t2[0]["artist"] == ""                                         # the uploader is never shown as the artist
