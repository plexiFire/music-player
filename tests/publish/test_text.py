from engine.publish import text as publish


def test_titles_and_tags_have_no_repeated_words():
    for t in publish.title_ideas("late night songs"):
        assert "songs songs" not in t
    tags = publish.tags("late night songs", [{"artist": "A"}])
    assert "songs playlist" not in tags and "late playlist" in tags
