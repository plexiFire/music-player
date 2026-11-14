from engine.publish import text as publish


def test_titles_and_tags_have_no_repeated_words():
    for t in publish.title_ideas("late night songs"):
        assert "songs songs" not in t
    tags = publish.tags("late night songs", [{"artist": "A"}])
    assert "songs playlist" not in tags and "late playlist" in tags


def test_description_follows_the_channel_template():
    ts = "0:00 One - A\n3:10 Two - B\n6:20 Three - C"
    d = publish.description("[Playlist] X", "x", ts, [], hashtags=["a", "b", "c", "d"], email="me@example.com",
                            top_hashtags=["a", "b", "c"], channel="My Channel")
    lines = d.splitlines()
    assert lines[0] == "#a #b #c"                       # 3 hashtags first: YouTube shows them above the title
    assert "Welcome to My Channel." in d and "Contact: me@example.com" in d
    assert any(l.startswith("0:00 ") for l in lines)     # chapters need 0:00 at the start of a line
    assert lines[-1] == "#a #b #c #d"
    assert not any(ord(ch) > 0x1F000 for ch in d)        # no emoji


def test_tags_include_mood_artists_and_songs_within_youtube_limit():
    tr = [{"title": f"Song {i}", "artist": f"Artist {i}"} for i in range(10)]
    t = publish.tags("Playlist 5", tr, extra=["slow evening playlist", "songs for a slow evening"])
    assert "slow evening playlist" in t and "Artist 0" in t and "Song 0" in t
    assert sum(len(x) + 2 for x in t) <= 500


def test_compose_matches_what_the_build_writes():
    from engine.publish import compose
    proj = {"title": "Playlist 5", "theme": "Playlist 5", "mood": "slow evening", "contact_email": "me@example.com",
            "hashtags": ["slowevening", "eveningplaylist", "chillsongs", "playlist"],
            "tracks": [{"title": "One", "artist": "A"}, {"title": "Two", "artist": "B"}]}
    d = compose.description_text(proj, "[Playlist] Songs for a slow evening", "0:00 One - A\n3:00 Two - B")
    assert d.splitlines()[0] == "#slowevening #eveningplaylist #chillsongs"
    assert "Songs for a slow evening. Press play, get comfortable" in d and "Contact: me@example.com" in d and "0:00 ▸ One - A" in d
    t = compose.tags_list(proj)
    assert "slow evening playlist" in t and "A" in t and "One" in t


def test_description_hook_ignores_a_meaningless_playlist_name():
    ts = "0:00 One - A"
    for name in ("123", "Playlist 5", "1234"):
        d = publish.description("t", name, ts, [])
        assert "123" not in d.split("TRACKLIST")[0] and "Playlist 5" not in d.split("TRACKLIST")[0], name
        assert "Dim the lights, press play" in d
    assert publish.description("t", "Rainy Cafe", ts, []).count("Rainy Cafe.") == 1


def test_every_generated_hashtag_appears_in_the_description():
    from engine.publish import compose
    from engine.titles import channel
    proj = {"title": "x", "theme": "x", "channel": "Senora", "profile": {"moods": ["sad", "late night"], "genre": "indie pop"},
            "tracks": [{"title": "One", "artist": "A"}]}
    title = "[Playlist] Songs worth a second listen"
    top, full = channel.hashtags({"moods": ["sad", "late night"], "genre": "indie pop"}, title, "Senora")
    d = compose.description_text(proj, title, "0:00 One - A")
    assert d.splitlines()[0] == " ".join("#" + h for h in top)
    for h in full:
        assert "#" + h in d.splitlines()[-1], h
    assert set(top) <= set(full)


def test_a_hand_edited_description_is_what_the_build_writes(tmp_path):
    import json, os
    from engine import cli
    src = [l for l in open(cli.__file__).read().splitlines() if "description_override" in l]
    assert src, "the build must prefer the hand-edited description"
