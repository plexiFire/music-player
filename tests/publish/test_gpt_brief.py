from engine.publish import gpt_brief


def project():
    return {"channel": "Senora", "contact_email": "me@example.com", "disc": "vinyl", "level_audio": False,
            "background": {"mode": "sky", "color": "night"}, "profile": {"genres": ["indie pop"], "moods": ["chill", "nostalgic"], "source": ["audio", "groq"]},
            "thumbs_selected": [{"family": "night", "variant": "blue"}, {"family": "swirl", "variant": "mono"}],
            "tracks": [{"title": "Sailor Song", "artist": "Gigi Perez", "duration": 211.0, "source_link": "https://youtu.be/XXKXpf7xFC4", "web_tags": ["indie"],
                        "cover": "/Users/someone/private/cover.png", "audio": "/Users/someone/private/a.mp3"},
                       {"title": "Back to friends", "artist": "sombr", "duration": 199.0, "source_link": "https://youtu.be/fOQ_-gZsnYQ"}]}


def test_the_brief_has_everything_gpt_needs_and_nothing_private():
    desc = "#chillmusic #lofiplaylist #aestheticplaylist\n\nWelcome to Senora.\n\nSongs that take you back.\n\nContact: me@example.com\n\n#senoraplaylist #chillmusic #indiepop\n"
    md = gpt_brief.build(project(), desc, "[Playlist] Songs that take you back", [{"title": "[Playlist] Songs worth hearing again", "score": 80, "source": "channel"}],
                         ["x.mp4", "x.thumbnail-A.jpg"], "Is my title too generic?")
    for needle in ("## What I want from you", "MY QUESTION: Is my title too generic?", "songs: 2, total length 6:50", "| 2 | 3:31 | Back to friends | sombr | 3:19 |",
                   "genre: indie pop", "mood: chill, nostalgic", "Chosen: **[Playlist] Songs that take you back**", "Songs worth hearing again",
                   "A: style 'night', colour 'blue'", "Late Night Melodies", "3,840,035", "-0.48", "More than 60 hashtags", "#senoraplaylist #chillmusic #indiepop",
                   "https://youtu.be/XXKXpf7xFC4", "[Playlist] When music is all you need"):
        assert needle in md, needle
    assert "me@example.com" not in md and "<my contact email>" in md                  # the e-mail is replaced
    assert "/Users/" not in md and ".mp3" not in md                                    # no local paths, no audio


def test_an_unbuilt_playlist_still_makes_a_brief():
    md = gpt_brief.build({"tracks": [], "channel": ""}, "", "[Playlist] x", [], [])
    assert "not built yet" in md and "No thumbnail styles chosen yet." in md


def test_time_format():
    assert gpt_brief.mmss(61) == "1:01" and gpt_brief.mmss(3725) == "1:02:05" and gpt_brief.mmss(None) == "0:00"
