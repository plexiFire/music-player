import os

import pytest
from PIL import Image

from engine.publish import thumbs

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")
COVERS = [f"{SAMPLES}/cover1.png", f"{SAMPLES}/cover2.png"]
CTX = {"moods": ["sad", "nostalgic"], "title": "[Playlist] Songs that make everything feel softer than before", "minutes": 17.3}


def test_every_family_and_colour_renders_dark_enough_and_under_youtubes_size_limit(tmp_path):
    for fam in thumbs.FAMILIES:
        assert len(fam["variants"]) == 6 and fam["id"] in thumbs.REFERENCE
        for v in fam["variants"]:
            im = thumbs.render(fam["id"], v, COVERS, CTX, (640, 360))           # fewer covers than slots: they repeat, no crash
            assert im.size == (640, 360)
    big = thumbs.render("night", "blue", COVERS, CTX, (1280, 720))
    path = thumbs.save_jpeg(big, str(tmp_path / "t.jpg"))
    assert os.path.getsize(path) < 2_000_000 and Image.open(path).size == (1280, 720)


def test_header_text_is_always_playlist_and_concept_comes_from_the_mood_not_the_name():
    assert thumbs.HEADER == "PlayList"
    assert thumbs.concept_for(["sad"])[0] == "Bittersweet Memories"
    assert thumbs.concept_for(["late night"])[0] == "Late Night Melodies"
    assert thumbs.concept_for([])[0]                               # unknown mood: still a sensible phrase


def test_a_long_title_is_wrapped_and_shrunk_to_fit():
    lines, f = thumbs.fit_lines("SONGS THAT MAKE EVERYTHING FEEL SOFTER THAN BEFORE", 1180, 100, 52, "Montserrat.ttf", 800)
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    assert 1 <= len(lines) <= 3 and all(d.textlength(x, font=f) <= 1180 for x in lines)


def test_unknown_style_is_refused_and_cache_key_changes_with_the_inputs():
    with pytest.raises(ValueError):
        thumbs.render("night", "no-such-colour", COVERS, CTX)
    a = thumbs.cache_key("night", "blue", COVERS, CTX, (640, 360))
    assert a == thumbs.cache_key("night", "blue", COVERS, CTX, (640, 360))
    assert a != thumbs.cache_key("night", "blue", COVERS, {**CTX, "moods": ["happy"]}, (640, 360))
