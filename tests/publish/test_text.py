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
