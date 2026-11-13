from engine.sources import metadata


def test_clean_title_strips_noise():
    assert metadata.clean_title("Artist - Song (Official Video)") == "Artist - Song"
    assert metadata.clean_title("Song [Lyrics] - Topic") == "Song"


def test_hires_artwork_url():
    u = "https://is1.mzstatic.com/image/thumb/abc/24UM.rgb.jpg/100x100bb.jpg"
    assert metadata.hires(u).endswith("/1200x1200bb.jpg")


def test_display_title_drops_unrequested_version_tags():
    f = metadata.display_title
    assert f("WILDFLOWER (Artist of the Year 2024 Live)", "Billie Eilish - WILDFLOWER") == "WILDFLOWER"
    assert f("Song (Live)", "Artist - Song (Live)") == "Song (Live)"


def test_clean_title_drops_keyword_suffix_and_invisible_chars():
    assert metadata.clean_title("Gata only ringtone | ringtone | iphone x") == "Gata only ringtone"
    assert metadata.clean_title("RINGTONE​ BOOK") == "RINGTONE BOOK"
