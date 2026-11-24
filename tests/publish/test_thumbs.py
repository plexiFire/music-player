import os

import pytest
from PIL import Image

from engine.publish import thumbs

SAMPLES = os.path.join(os.path.dirname(__file__), "..", "..", "samples")
COVERS = [f"{SAMPLES}/cover1.png", f"{SAMPLES}/cover2.png"]
CTX = {"moods": ["sad", "nostalgic"], "title": "[Playlist] Songs that make everything feel softer than before", "minutes": 17.3}


def test_every_family_and_colour_renders_dark_enough_and_under_youtubes_size_limit(tmp_path):
    for fam in thumbs.FAMILIES:
        assert len(fam["variants"]) >= 6 and fam["id"] in thumbs.REFERENCE
        for v in fam["variants"]:
            im = thumbs.render(fam["id"], v, COVERS, CTX, (640, 360))           # fewer covers than slots: they repeat, no crash
            assert im.size == (640, 360)
    big = thumbs.render("nocturne", "rain_window", COVERS, CTX, (1280, 720))
    path = thumbs.save_jpeg(big, str(tmp_path / "t.jpg"))
    assert os.path.getsize(path) < 2_000_000 and Image.open(path).size == (1280, 720)


def test_header_text_is_always_playlist_and_concept_comes_from_the_mood_not_the_name():
    assert thumbs.HEADER == "PlayList"
    assert thumbs.concept_for(["sad"])[0] == "Soft Goodbyes"
    assert thumbs.concept_for(["late night"])[0] == "Still Awake"
    assert thumbs.concept_for([])[0]                               # unknown mood: still a sensible phrase


def test_a_long_title_is_wrapped_and_shrunk_to_fit():
    lines, f = thumbs.fit_lines("SONGS THAT MAKE EVERYTHING FEEL SOFTER THAN BEFORE", 1180, 100, 52, "Montserrat.ttf", 800)
    from PIL import ImageDraw
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    assert 1 <= len(lines) <= 3 and all(d.textlength(x, font=f) <= 1180 for x in lines)


def test_unknown_style_is_refused_and_cache_key_changes_with_the_inputs():
    with pytest.raises(ValueError):
        thumbs.render("nocturne", "no-such-colour", COVERS, CTX)
    a = thumbs.cache_key("nocturne", "rain_window", COVERS, CTX, (640, 360))
    assert a == thumbs.cache_key("nocturne", "rain_window", COVERS, CTX, (640, 360))
    assert a != thumbs.cache_key("nocturne", "rain_window", COVERS, {**CTX, "moods": ["happy"]}, (640, 360))


def test_no_text_on_a_thumbnail_is_copied_from_the_reference_thumbnails_of_other_channels():
    mine = [c[1] for c in thumbs.CONCEPT] + [x for c in thumbs.CONCEPT for x in c[2]] + [thumbs.concept_for([])[0], *thumbs.concept_for([])[1]]
    bad = {t.lower() for t in thumbs.REFERENCE_TEXTS}
    assert not [t for t in mine if t.lower() in bad]


def test_your_own_thumbnail_words_replace_the_automatic_phrase():
    assert thumbs.concept_text({"thumb_text": "  My   own words ", "moods": ["sad"]}) == "My own words"
    assert thumbs.concept_text({"thumb_text": "", "moods": ["sad"]}) == "Soft Goodbyes"
    a = thumbs.cache_key("nocturne", "rain_window", COVERS, {**CTX, "thumb_text": "one"}, (640, 360))
    assert a != thumbs.cache_key("nocturne", "rain_window", COVERS, {**CTX, "thumb_text": "two"}, (640, 360))


def test_every_line_of_a_long_title_fits_inside_its_box_and_nothing_touches_the_bottom_bar():
    box_w, box_h = 1180, 240
    for title in ("Songs that make everything feel softer than before", "The only music you need to relax", "x", "A" * 80):
        lines, f = thumbs.fit_box(title.upper(), box_w, box_h, 100, 40, "Montserrat.ttf", 800, max_lines=3, spacing=1.04)
        from PIL import ImageDraw
        d = ImageDraw.Draw(Image.new("L", (1, 1)))
        assert len(lines) <= 3 and all(d.textlength(x, font=f) <= box_w for x in lines) or f.size == 40       # shrinks first; 40 px is the floor
        assert len(lines) * f.size * 1.04 <= box_h or f.size == 40


CAPS = {"aura": 6, "prism": 6, "silk": 6, "nocturne": 6, "wave": 4, "horizon": 4,
        "night": 8, "swirl": 12, "sunset": 12, "bold": 8}


def _many_covers(tmp_path, n):
    covers = []
    for i in range(n):
        f = tmp_path / f"c{i}.png"
        Image.new("RGB", (40, 40), (i * 20 % 256, 50, 90)).save(f)
        covers.append(str(f))
    return covers


def test_every_style_uses_exactly_as_many_covers_as_you_have_up_to_its_limit_and_never_repeats_one(monkeypatch, tmp_path):
    covers = _many_covers(tmp_path, 14)
    placed, cropped = [], []
    real_place, real_crop = thumbs.place_cover, thumbs.fill_crop
    monkeypatch.setattr(thumbs, "place_cover", lambda base, path, *a, **k: (placed.append(path), real_place(base, path, *a, **k))[1])
    monkeypatch.setattr(thumbs, "fill_crop", lambda path, *a: (cropped.append(path), real_crop(path, *a))[1])
    for fam, v in (("aura", "teal"), ("prism", "twilight"), ("silk", "silver_beam"), ("nocturne", "rain_window"),
                   ("wave", "silver"), ("horizon", "crimson"),
                   ("night", "blue"), ("swirl", "mono"), ("sunset", "orange"), ("bold", "mono")):
        for n in (1, 2, 3, 4, 5, 6, 7, 9, 14):
            placed.clear()
            cropped.clear()
            thumbs.render(fam, v, covers[:n], CTX, (320, 180))
            shown = set(placed)
            cap = CAPS[fam]
            assert len(shown) == min(n, cap), (fam, n, len(shown))            # all of yours, none twice, no empty slot


def test_with_more_songs_than_fit_the_covers_are_spread_over_the_whole_playlist(monkeypatch, tmp_path):
    covers = _many_covers(tmp_path, 14)
    placed = []
    real = thumbs.place_cover
    monkeypatch.setattr(thumbs, "place_cover", lambda base, path, *a, **k: (placed.append(path), real(base, path, *a, **k))[1])
    thumbs.render("nocturne", "rain_window", covers, CTX, (320, 180))
    assert placed[0] == covers[0] and placed[-1] == covers[-1] and len(placed) == 6


def test_rows_are_balanced_and_old_style_names_still_work(tmp_path):
    assert [thumbs.grid_rows(n) for n in (3, 4, 5, 6, 7, 9)] == [[3], [2, 2], [3, 2], [3, 3], [4, 3], [3, 3, 3]]
    for old in ("record", "cascade", "hero", "filmstrip", "pastel", "sky", "season",
                "eclipse", "poster", "room", "strip", "chrome", "tracklist"):  # removed/light styles: saved picks still render cleanly
        assert thumbs.render(old, "blue", COVERS, CTX, (320, 180)).size == (320, 180)
    assert thumbs.resolve("record", "nonsense") == ("nocturne", "rain_window")
    assert [f["id"] for f in thumbs.FAMILIES[:4]] == ["aura", "prism", "silk", "nocturne"]
    with pytest.raises(ValueError):
        thumbs.render("nothing", "blue", COVERS, CTX)


def test_the_track_list_style_shows_the_song_names(tmp_path):
    covers = _many_covers(tmp_path, 4)
    a = thumbs.cache_key("tracklist", "blue", covers, {**CTX, "tracks": ["A", "B", "C", "D"]}, (320, 180))
    assert a != thumbs.cache_key("tracklist", "blue", covers, {**CTX, "tracks": ["A", "B", "C", "X"]}, (320, 180))


def test_a_long_title_on_the_big_bold_style_stays_above_the_badge_and_progress_bar():
    import numpy as np
    img = thumbs.render("bold", "blue", COVERS, {**CTX, "title": "[Playlist] The only music you need to relax to tonight, always", "minutes": 19.5}, (1280, 720))
    a = np.asarray(img).astype(int)
    band = a[int(720 * 0.86):int(720 * 0.97), int(1280 * 0.05):int(1280 * 0.80)]                        # between the title box and the bottom bar
    assert (band.min(axis=2) > 235).sum() == 0                                                         # no white text pixels down there
